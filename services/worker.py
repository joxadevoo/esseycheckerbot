import asyncio
import json
import logging
from typing import Dict, Any, List
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.database import save_essay_result
from services.cache_service import (
    compute_essay_hash,
    get_cached_evaluation,
    save_cached_evaluation,
)
from services.ai_service import ai_service
from services.queue_service import queue_service
from config import settings

logger = logging.getLogger(__name__)


def split_message_text(text: str, max_length: int = 3800) -> List[str]:
    """Splits long markdown/HTML text into safe chunks strictly under Telegram's limit."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_len = 0

    for line in lines:
        # If a single line itself exceeds max_length, split it into segments
        if len(line) > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            for i in range(0, len(line), max_length):
                chunks.append(line[i : i + max_length])
            continue

        if current_len + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = len(line) + 1
        else:
            current_chunk.append(line)
            current_len += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def format_detailed_feedback(feedback: Dict[str, Any], word_count: int) -> str:
    """Formats full IELTS feedback into a rich Telegram HTML report matching British Council descriptors."""
    task_type = feedback.get("task_type", "Task 2")
    overall = feedback.get("current_overall_band") or feedback.get("overall") or feedback.get("overall_band", "N/A")
    next_target = feedback.get("next_target_band")
    actual_words = feedback.get("word_count", word_count)
    meets_minimum = feedback.get("meets_minimum", True)
    min_req = 150 if "1" in str(task_type) else 250

    min_badge = "✅ Yetarli" if meets_minimum else f"⚠️ <b>{min_req} ta so'zdan kam (TR 5.5 cap qo'llandi)</b>"

    # Extract criteria details
    descriptors = feedback.get("scores_by_official_descriptors", {})

    def get_criterion_info(key, alt_key=None):
        data = descriptors.get(key) or descriptors.get(alt_key or key) or feedback.get(key) or feedback.get(alt_key or key)
        if isinstance(data, dict):
            band = data.get("band", "N/A")
            reason = data.get("reason_uz", "")
            return band, reason
        return data if data is not None else "N/A", ""

    tr_band, tr_reason = get_criterion_info("task_response", "task_achievement")
    cc_band, cc_reason = get_criterion_info("coherence_cohesion", "coherence")
    lr_band, lr_reason = get_criterion_info("lexical_resource", "lexical")
    gr_band, gr_reason = get_criterion_info("grammatical_accuracy", "grammar")

    errors = feedback.get("real_errors_only") or feedback.get("errors", [])
    weakest = feedback.get("weakest_criteria", [])
    advice = feedback.get("advice_for_next_0.5_band_uz") or feedback.get("band7_advice", "")

    model_name = feedback.get("_model") or (settings.OPENAI_MODEL if settings.AI_PROVIDER == "openai" else settings.GROQ_MODEL)
    model_badge = f" <code>[{model_name}]</code>" if model_name else ""

    report = [
        f"📊 <b>IELTS WRITING TAHLILI ({task_type})</b>{model_badge}",
        f"📝 <b>So'zlar soni:</b> {actual_words} ta ({min_badge})",
        f"🏆 <b>Umumiy Ball: Band {overall}</b>" + (f" <i>(Keyingi maqsad: Band {next_target})</i>\n" if next_target else "\n"),
        "<b>Mezonlar bo'yicha rasmiy baholar:</b>",
        f"• 📌 <b>Task Response:</b> Band {tr_band}" + (f"\n  <i>↳ {tr_reason}</i>" if tr_reason else ""),
        f"• 🔗 <b>Coherence & Cohesion:</b> Band {cc_band}" + (f"\n  <i>↳ {cc_reason}</i>" if cc_reason else ""),
        f"• 📚 <b>Lexical Resource:</b> Band {lr_band}" + (f"\n  <i>↳ {lr_reason}</i>" if lr_reason else ""),
        f"• ✍️ <b>Grammatical Accuracy:</b> Band {gr_band}" + (f"\n  <i>↳ {gr_reason}</i>" if gr_reason else "") + "\n",
    ]

    criterion_labels = {
        "task_response": "Task Response",
        "task_achievement": "Task Achievement",
        "coherence_cohesion": "Coherence & Cohesion",
        "lexical_resource": "Lexical Resource",
        "grammatical_accuracy": "Grammar Accuracy",
    }
    if weakest:
        weakest_str = ", ".join(criterion_labels.get(w, str(w)) for w in weakest)
        report.append(f"⚠️ <b>E'tibor qaratish kerak bo'lgan mezonlar:</b> {weakest_str}\n")
    else:
        report.append("🌟 <b>Barcha mezonlar birdek yuqori darajada muvozanatlashgan!</b>\n")

    if errors:
        report.append("🔍 <b>Aniqlangan real xatolar va qoidalar:</b>")
        for i, e in enumerate(errors[:8], 1):
            wrong = e.get("wrong") or e.get("original", "")
            correct = e.get("correct") or e.get("correction", "")
            rule = e.get("rule_uz") or e.get("why_uz") or e.get("explanation", "")
            report.append(
                f"{i}. ❌ <i>\"{wrong}\"</i>\n"
                f"   ✅ <b>{correct}</b>\n"
                f"   ℹ️ <i>{rule}</i>"
            )
        report.append("")
    else:
        report.append("✅ <i>Jiddiy grammatik yoki leksik xatolar topilmadi.</i>\n")

    if advice:
        target_str = f"Band {next_target}" if next_target else "+0.5 Ball"
        report.append(f"💡 <b>{target_str} ga chiqish uchun aniq maslahat:</b>\n{advice}\n")

    return "\n".join(report)


async def process_task(bot: Bot, task: Dict[str, Any], bot_username: str):
    user_id = task["user_id"]
    user_mention = task.get("user_mention", "Foydalanuvchi")
    chat_id = task["chat_id"]
    message_id = task["message_id"]
    is_private = task.get("is_private", False)
    essay_text = task["essay_text"]
    word_count = task.get("word_count", 0)
    task_type = task.get("task_type", "Task 2")
    task_prompt = task.get("task_prompt")

    try:
        essay_hash = compute_essay_hash(f"{task_type}:{task_prompt or ''}:{essay_text}")

        # Step 1: Check cache
        feedback = await get_cached_evaluation(essay_hash)

        # Step 2: If not in cache, call AI
        if not feedback:
            feedback = await ai_service.evaluate_essay(
                essay_text=essay_text,
                task_type=task_type,
                task_prompt=task_prompt,
                word_count=word_count,
            )
            await save_cached_evaluation(essay_hash, feedback)

        overall_band = (
            feedback.get("current_overall_band")
            or feedback.get("overall")
            or feedback.get("overall_band", 6.0)
        )

        # Step 3: Save to Database
        essay_id = await save_essay_result(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            essay_hash=essay_hash,
            text=essay_text,
            word_count=feedback.get("word_count", word_count),
            overall_band=float(overall_band) if overall_band != "N/A" else 0.0,
            feedback_json=json.dumps(feedback, ensure_ascii=False),
        )

        detailed_report = format_detailed_feedback(feedback, word_count)
        chunks = split_message_text(detailed_report)

        if is_private:
            # Direct PM: send full report chunks
            for chunk in chunks:
                await bot.send_message(chat_id=user_id, text=chunk, parse_mode="HTML")
        else:
            # Group chat: send concise public badge + reply_to_message_id
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📥 Batafsil hisobotni botda ko'rish",
                            url=f"https://t.me/{bot_username}?start=report_{essay_id}",
                        )
                    ]
                ]
            )

            badge_text = (
                f"✅ {user_mention}, inshoingiz muvaffaqiyatli tekshirildi!\n\n"
                f"🏆 <b>Umumiy Ball: Band {overall_band}</b>\n"
                f"📝 So'zlar soni: {word_count}\n\n"
                f"🔒 <i>Maxfiylik va qulaylik uchun batafsil xatolar hamda tavsiyalar shaxsiy profilingizga yuborildi.</i>"
            )

            await bot.send_message(
                chat_id=chat_id,
                text=badge_text,
                reply_to_message_id=message_id,
                parse_mode="HTML",
                reply_markup=kb,
            )

            # Also attempt to send directly to student's PM
            try:
                for chunk in chunks:
                    await bot.send_message(chat_id=user_id, text=chunk, parse_mode="HTML")
            except Exception as pm_err:
                logger.warning(
                    f"Could not send PM to user {user_id} (bot might not be started by user): {pm_err}"
                )

    except Exception as e:
        logger.error(f"Error processing essay task: {e}", exc_info=True)
        error_msg = (
            f"❌ {user_mention}, kechirasiz, inshoni tekshirishda xatolik yuz berdi.\n"
            f"Iltimos, birozdan so'ng qayta yuborib ko'ring."
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=error_msg,
                reply_to_message_id=message_id,
            )
        except Exception:
            pass


async def start_worker(bot: Bot, bot_username: str, worker_id: int = 1):
    """
    Decoupled Worker loop that continuously polls jobs from the queue.
    Can scale to N workers seamlessly.
    """
    logger.info(f"Worker #{worker_id} started and listening for jobs...")
    while True:
        try:
            task = await queue_service.dequeue(timeout=2)
            if task:
                logger.info(f"Worker #{worker_id} processing task from user {task.get('user_id')}")
                await process_task(bot, task, bot_username)
            else:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info(f"Worker #{worker_id} stopping...")
            break
        except Exception as e:
            logger.error(f"Worker #{worker_id} unhandled exception: {e}", exc_info=True)
            await asyncio.sleep(2)
