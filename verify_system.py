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

from services.filter_service import filter_essay_text, count_words
from services.cache_service import compute_essay_hash
from services.worker import split_message_text, format_detailed_feedback
from services.queue_service import queue_service
from db.database import init_db, upsert_user, upsert_group, check_and_increment_limits, get_session
from db.models import User, Group


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
        "#task2\n"
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

    print("\n========================================")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
    print("========================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
