import asyncio
import os
import sys

# Ensure current directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from services.filter_service import filter_essay_text, count_words, is_probable_topic
from services.cache_service import compute_essay_hash
from services.worker import split_message_text, format_detailed_feedback
from services.queue_service import queue_service
from db.database import (
    init_db,
    upsert_user,
    upsert_group,
    check_and_increment_limits,
    get_session,
    get_group_topic,
    set_group_topic,
    clear_group_topic,
    set_group_user_role,
    remove_group_user_role,
    get_group_roles,
    check_user_role_in_group,
    get_group_topic_submissions,
    get_student_historical_scores,
    get_group_tracked_users,
    get_user_teacher_groups,
)
from db.models import User, Group, GroupTopic, GroupMemberRole, Essay
from services.report_service import (
    calculate_group_report_data,
    format_report_text,
    generate_report_chart,
    generate_report_excel,
)


async def run_tests():
    print("========================================")
    print("[TEST] RUNNING SYSTEM VERIFICATION TESTS")
    print("========================================")

    # 1. Filter Tests
    print("\n--- 1. Testing 3-tier Filter ---")

    # Command test
    is_v, reason, _, _, _, _ = filter_essay_text("/start")
    assert not is_v and reason == "Bot komandasi", f"Failed command check: {reason}"
    print("✅ Command filter passed")

    # Missing hashtag test
    sample_no_tag = "This is a very long essay text without any hashtag. " * 10
    is_v, reason, _, _, _, _ = filter_essay_text(sample_no_tag)
    assert not is_v and "Hashtag topilmadi" in reason, f"Failed missing tag check: {reason}"
    print("✅ Missing hashtag filter passed")

    # Short essay test
    sample_short = "#essay This is a short sentence."
    is_v, reason, _, count, _, _ = filter_essay_text(sample_short)
    assert not is_v and "qisqa" in reason, f"Failed short text check: {reason}"
    print(f"✅ Short essay filter passed ({count} words < 40)")

    # Valid essay with #essey test
    sample_essey = (
        "#essey Education is an important aspect of modern human society. "
        "Many governments invest substantial amounts of capital into primary and secondary schools. "
        "However, some critics argue that practical vocational training is significantly more beneficial "
        "for students who want to enter the real workforce immediately after graduation. "
        "In this essay, both sides will be discussed in comprehensive detail."
    )
    is_v, reason, clean_text, count, t_type, t_prompt = filter_essay_text(sample_essey)
    assert is_v, f"Failed valid #essey check: {reason}"
    assert "#essey" not in clean_text, "Hashtag was not stripped from clean_text"
    assert count >= 40, f"Word count unexpected: {count}"
    assert t_type == "Task 2"
    print(f"✅ Valid #essey filter passed ({count} words, {t_type})")

    # Valid essay with Topic prompt parsing
    sample_with_topic = (
        "#essay\n"
        "Topic: Should higher education be free for all citizens?\n"
        "Essay: Education is an important aspect of modern human society. "
        "Many governments invest substantial amounts of capital into primary and secondary schools. "
        "However, some critics argue that practical vocational training is significantly more beneficial "
        "for students who want to enter the real workforce immediately after graduation. "
        "In this essay, both sides will be discussed in comprehensive detail."
    )
    is_v_top, _, clean_body, _, t_type2, t_prompt2 = filter_essay_text(sample_with_topic)
    assert is_v_top and t_prompt2 == "Should higher education be free for all citizens?"
    print(f"✅ Question/Topic prompt extraction verified: '{t_prompt2[:30]}...'")

    # Verify #task2 alone is not treated as essay hashtag
    sample_task2_essay = sample_essey.replace("#essey", "#task2")
    is_v_t2, _, _, _, _, _ = filter_essay_text(sample_task2_essay)
    assert not is_v_t2, "#task2 should NOT be accepted by filter_essay_text (reserved for topics)"
    print("✅ #task2 reserved for topics (rejected as direct essay hashtag) verified")

    # Valid essay with #essay test
    sample_essay_var = sample_essey.replace("#essey", "#essay")
    is_v2, _, _, _, _, _ = filter_essay_text(sample_essay_var)
    assert is_v2, "Failed valid #essay check"
    print("✅ Valid #essay regex variation passed")

    # Valid essay with #insho test
    sample_insho_var = sample_essey.replace("#essey", "#insho")
    is_v3, _, _, _, _, _ = filter_essay_text(sample_insho_var)
    assert is_v3, "Failed valid #insho regex variation passed"
    print("✅ Valid #insho regex variation passed")

    # Rejected #task1 test
    sample_t1_var = sample_essey.replace("#essey", "#task1")
    is_v_t1, _, _, _, _, _ = filter_essay_text(sample_t1_var)
    assert not is_v_t1, "#task1 should be rejected now"
    print("✅ #task1 rejection verified (Only Task 2 allowed)")

    # Test IELTS prompt detection
    sample_prompt = (
        "In many countries, an increasing number of young people are leaving their hometowns "
        "to study or find work in other parts of the country or abroad. "
        "Do the advantages of this trend outweigh the disadvantages? "
        "Give reasons for your answer and include any relevant examples."
    )
    assert is_probable_topic(sample_prompt), "Failed to detect IELTS prompt"
    assert not is_probable_topic(sample_essey), "Full essay should not be detected as topic"
    print("✅ IELTS Topic prompt vs Essay detection passed")

    # 2. Hash & Cache consistency
    print("\n--- 2. Testing SHA-256 Hashing ---")
    hash1 = compute_essay_hash("  This Is An ESSAY!   With spaces. ")
    hash2 = compute_essay_hash("this is an essay! with spaces.")
    assert hash1 == hash2, f"Hash mismatch: {hash1} != {hash2}"
    print(f"✅ SHA-256 Normalization & Hash verified: {hash1[:16]}...")

    # 3. Message Splitter (4096 char safe chunking)
    print("\n--- 3. Testing 4096-Char Message Chunking ---")
    mock_feedback = {
        "word_count": 270,
        "overall": 6.5,
        "task_response": 6.5,
        "coherence": 6.0,
        "lexical": 7.0,
        "grammar": 6.0,
        "errors": [
            {"wrong": f"error_{i}", "correct": f"correct_{i}", "why_uz": f"O'zbekcha qoida tushuntirishi_{i}"}
            for i in range(20)
        ],
        "band7_advice": "Band 7 uchun tavsiyalar. " * 40,
    }
    report = format_detailed_feedback(mock_feedback, 270)
    chunks = split_message_text(report, max_length=1000)
    for i, c in enumerate(chunks):
        assert len(c) <= 1000, f"Chunk {i} exceeded max_length ({len(c)})"
    print(f"✅ Long report ({len(report)} chars) safely split into {len(chunks)} chunks")

    # 4. Database Tests
    print("\n--- 4. Testing Database Operations & Admin Whitelist ---")
    await init_db()
    admin_user_id = 7326292681
    test_user_id = 999888777
    test_chat_id = -100123456789

    await upsert_user(test_user_id, "test_student", "Test Student")
    await upsert_group(test_chat_id, "IELTS Study Group")

    # Verify admin user has unlimited access
    admin_allowed, _ = await check_and_increment_limits(admin_user_id, test_chat_id, is_private=False)
    assert admin_allowed, "Admin user limit check should always be True"
    print("✅ Admin user (7326292681) whitelist bypass verified")

    # Reset test_user_id daily usage in DB for test repeatability
    from sqlalchemy import delete
    from db.models import DailyUsage
    async with get_session() as session:
        await session.execute(delete(DailyUsage).where(DailyUsage.target_id == test_user_id))
        await session.commit()

    # Check and increment limits for regular user
    allowed, msg = await check_and_increment_limits(test_user_id, test_chat_id, is_private=False)
    assert allowed, f"Limit check failed: {msg}"
    print("✅ Regular database user, group, and daily limits verified")

    # Test GroupTopic functionality
    topic = await set_group_topic(test_chat_id, "Sample IELTS Topic Question", message_id=123, created_by=admin_user_id)
    assert topic.topic_text == "Sample IELTS Topic Question"
    fetched = await get_group_topic(test_chat_id)
    assert fetched is not None and fetched.topic_text == "Sample IELTS Topic Question"
    
    # Update topic
    updated = await set_group_topic(test_chat_id, "Updated Topic Question", message_id=124, created_by=admin_user_id)
    assert updated.topic_text == "Updated Topic Question"
    fetched_updated = await get_group_topic(test_chat_id)
    assert fetched_updated.topic_text == "Updated Topic Question"

    # Clear topic
    cleared = await clear_group_topic(test_chat_id)
    assert cleared
    assert await get_group_topic(test_chat_id) is None
    print("✅ GroupTopic database operations (set, get, update, clear) verified")

    # Test GroupMemberRole functionality (@username based)
    # Assign teacher role
    r_teacher = await set_group_user_role(test_chat_id, "mentor_john", role="teacher", assigned_by=admin_user_id)
    assert r_teacher.username == "mentor_john"
    assert r_teacher.role == "teacher"

    # Assign admin role
    r_admin = await set_group_user_role(test_chat_id, "@deputy_admin", role="admin", assigned_by=admin_user_id)
    assert r_admin.username == "deputy_admin"  # @ should be stripped and lowercased
    assert r_admin.role == "admin"

    # Verify check_user_role_in_group
    assert await check_user_role_in_group(test_chat_id, username="mentor_john") == "teacher"
    assert await check_user_role_in_group(test_chat_id, username="MENTOR_JOHN") == "teacher"  # case-insensitive
    assert await check_user_role_in_group(test_chat_id, username="deputy_admin") == "admin"
    assert await check_user_role_in_group(test_chat_id, username="random_student") is None

    # List roles
    roles = await get_group_roles(test_chat_id)
    assert len(roles) == 2
    assert any(r.username == "mentor_john" and r.role == "teacher" for r in roles)
    assert any(r.username == "deputy_admin" and r.role == "admin" for r in roles)

    # Remove role
    del_res = await remove_group_user_role(test_chat_id, "mentor_john")
    assert del_res is True
    assert await check_user_role_in_group(test_chat_id, username="mentor_john") is None
    roles_after = await get_group_roles(test_chat_id)
    assert len(roles_after) == 1
    print("✅ GroupMemberRole username-based operations (set, check, list, remove) verified")

    # 5. Queue & Worker Service
    print("\n--- 5. Testing Queue Service ---")
    task_payload = {
        "user_id": test_user_id,
        "user_mention": "@test_student",
        "chat_id": test_chat_id,
        "message_id": 101,
        "is_private": False,
        "essay_text": clean_text,
        "word_count": count,
    }
    q_len = await queue_service.enqueue(task_payload)
    assert q_len >= 1, f"Queue length should be >= 1, got {q_len}"
    print(f"✅ Enqueue verified (Queue size: {q_len})")

    dequeued_task = await queue_service.dequeue(timeout=1)
    assert dequeued_task is not None, "Failed to dequeue task"
    assert dequeued_task["user_id"] == test_user_id, "Dequeued payload mismatch"
    print("✅ Dequeue verified successfully")

    # 6. Teacher Report & Analytics Service
    print("\n--- 6. Testing Teacher Report, Visual Chart & Excel Export ---")
    import json
    from datetime import datetime, timezone

    # Setup active topic
    rep_topic = await set_group_topic(test_chat_id, "Should universities focus on practical employment skills?", message_id=500, created_by=admin_user_id)

    # Insert test users
    student_1_id = test_user_id  # 999888777
    student_2_id = 111222333
    student_3_id = 444555666  # will not submit

    await upsert_user(student_1_id, "student_one", "Student One")
    await upsert_user(student_2_id, "student_two", "Student Two")
    await upsert_user(student_3_id, "student_three", "Student Three")

    # Insert historical essay 1 for student 1 (band 6.0)
    fb_s1_old = json.dumps({"overall": 6.0, "task_response": 6.0, "coherence": 6.0, "lexical": 6.0, "grammar": 6.0})
    fb_s1_new = json.dumps({"overall": 6.5, "task_response": 6.5, "coherence": 6.5, "lexical": 7.0, "grammar": 6.0})
    fb_s2 = json.dumps({
        "current_overall_band": 7.5,
        "word_count": 290,
        "scores_by_official_descriptors": {
            "task_response": {"band": 7.5, "reason_uz": "Mavzu to'liq yoritilgan"},
            "coherence_cohesion": {"band": 7.5, "reason_uz": "Mantiqiy bog'lanish a'lo"},
            "lexical_resource": {"band": 8.0, "reason_uz": "Keng lug'at boyligi"},
            "grammatical_accuracy": {"band": 7.0, "reason_uz": "Kam grammatik xato"}
        }
    })

    from sqlalchemy import delete
    async with get_session() as session:
        await session.execute(delete(Essay).where(Essay.chat_id == test_chat_id))
        await session.commit()

    async with get_session() as session:
        # Prior essays (from 7 days ago)
        past_time = datetime(2026, 9, 1, 10, 0, 0)
        now_time = datetime(2026, 9, 10, 12, 0, 0)

        e_old = Essay(
            user_id=student_1_id,
            chat_id=test_chat_id,
            message_id=200,
            essay_hash="hash_old_1",
            original_text="Old essay body...",
            word_count=255,
            overall_band=6.0,
            feedback_json=fb_s1_old,
            created_at=past_time,
        )
        session.add(e_old)
        # Prior essay for student 3 (so student 3 is in tracked_users, but hasn't submitted for this topic)
        e_s3 = Essay(
            user_id=student_3_id,
            chat_id=test_chat_id,
            message_id=201,
            essay_hash="hash_s3",
            original_text="Student 3 older essay...",
            word_count=240,
            overall_band=5.5,
            feedback_json=fb_s1_old,
            created_at=past_time,
        )
        session.add(e_s3)
        await session.commit()

        # Current submissions for the active topic
        e_s1_current = Essay(
            user_id=student_1_id,
            chat_id=test_chat_id,
            message_id=501,
            essay_hash="hash_s1_curr",
            original_text="Current essay student 1...",
            word_count=275,
            overall_band=6.5,
            feedback_json=fb_s1_new,
            created_at=now_time,
        )
        e_s2_current = Essay(
            user_id=student_2_id,
            chat_id=test_chat_id,
            message_id=502,
            essay_hash="hash_s2_curr",
            original_text="Current essay student 2...",
            word_count=290,
            overall_band=7.5,
            feedback_json=fb_s2,
            created_at=now_time,
        )
        session.add(e_s1_current)
        session.add(e_s2_current)
        await session.commit()

    # Query submissions
    submissions = await get_group_topic_submissions(test_chat_id, since=rep_topic.created_at)
    assert len(submissions) >= 2, f"Expected at least 2 submissions, got {len(submissions)}"

    # Query historical scores map
    hist_map = {}
    for es, _ in submissions:
        hist_map[es.user_id] = await get_student_historical_scores(test_chat_id, es.user_id)

    # Tracked users
    tracked_users = await get_group_tracked_users(test_chat_id)
    assert any(u.id == student_3_id for u in tracked_users)

    # Calculate report data
    report_data = calculate_group_report_data(
        topic=rep_topic,
        submissions=submissions,
        historical_scores_map=hist_map,
        tracked_users=tracked_users,
        total_members_count=10,
    )

    assert report_data["submitted_count"] == 2
    assert report_data["total_members"] == 10
    assert report_data["not_submitted_count"] == 8
    assert report_data["max_band"] == 7.5
    assert report_data["min_band"] == 6.5
    assert report_data["average_band"] == 7.0

    # Student 2 should be ranked 1st with 7.5 and medal 🥇
    s_first = report_data["students"][0]
    assert s_first["user_id"] == student_2_id
    assert s_first["overall"] == 7.5
    assert s_first["medal"] == "🥇"
    assert s_first["trend"] == "new"
    assert s_first["tr"] == "7.5"
    assert s_first["cc"] == "7.5"
    assert s_first["lr"] == "8.0"
    assert s_first["gra"] == "7.0"

    # Student 1 should be ranked 2nd with 6.5, medal 🥈, and delta +0.5
    s_second = report_data["students"][1]
    assert s_second["user_id"] == student_1_id
    assert s_second["overall"] == 6.5
    assert s_second["medal"] == "🥈"
    assert s_second["trend"] == "up"
    assert s_second["delta"] == 0.5
    print("✅ Teacher Report data aggregation & progress dynamics (+0.5 growth) verified")
    print("✅ IELTS Criteria (TR, CC, LR, GRA) extracted accurately from descriptors")

    # Format text report
    text_report = format_report_text(report_data)
    assert "IELTS Task 2: Guruh Natijalari Hisoboti" in text_report
    assert "@student_two" in text_report and "7.5" in text_report
    assert "@student_one" in text_report and "6.5" in text_report
    assert "TR: 7.5 | CC: 7.5 | LR: 8.0 | GRA: 7.0" in text_report
    assert "📈 (+0.5)" in text_report
    assert "@student_three" in text_report  # in not_submitted list
    print("✅ Formatted Telegram HTML text report verified")

    # Test get_user_teacher_groups query
    t_groups = await get_user_teacher_groups("deputy_admin")
    assert any(gid == test_chat_id for gid, _ in t_groups)
    print("✅ Teacher Groups query (get_user_teacher_groups) verified")

    # Generate Chart Image (PNG)
    chart_png = generate_report_chart(report_data)
    assert isinstance(chart_png, bytes)
    assert len(chart_png) > 1000, "PNG image bytes too small"
    assert chart_png[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG header"
    print(f"✅ Matplotlib chart generation verified ({len(chart_png)} bytes PNG)")

    # Generate Excel Report (XLSX)
    excel_bytes = generate_report_excel(report_data)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 1000, "Excel bytes too small"
    assert excel_bytes[:4] == b"PK\x03\x04", "Invalid ZIP/XLSX header"
    print(f"✅ Excel spreadsheet export verified ({len(excel_bytes)} bytes XLSX)")

    print("\n========================================")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
    print("========================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
