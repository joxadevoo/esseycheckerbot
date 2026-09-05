import json
import logging
from typing import Optional
from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.database import (
    upsert_user,
    upsert_group,
    check_and_increment_limits,
    get_session,
)
from db.models import Essay
from services.filter_service import filter_essay_text, count_words
from services.queue_service import queue_service
from services.worker import format_detailed_feedback, split_message_text

logger = logging.getLogger(__name__)
router = Router()


class EssayFSM(StatesGroup):
    waiting_for_task_type = State()
    waiting_for_prompt = State()
    waiting_for_essay = State()


def get_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Yangi insho tekshirish", callback_data="fsm:start_check"
                )
            ],
            [
                InlineKeyboardButton(text="ℹ️ Qoidalar va Yordam", callback_data="fsm:help"),
            ],
        ]
    )


def get_task_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 IELTS Task 2 (Essay)", callback_data="task_type:Task 2"),
                InlineKeyboardButton(text="📊 IELTS Task 1 (Report)", callback_data="task_type:Task 1"),
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fsm:cancel")],
        ]
    )


def get_skip_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏩ Savolsiz davom etish", callback_data="prompt:skip"
                )
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fsm:cancel")],
        ]
    )


@router.message(CommandStart())
async def handle_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)

    # Deep linking check (e.g. /start report_12)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("report_"):
        essay_id_str = parts[1].replace("report_", "")
        if essay_id_str.isdigit():
            essay_id = int(essay_id_str)
            async with get_session() as session:
                essay = await session.get(Essay, essay_id)
                if essay and essay.feedback_json:
                    feedback = json.loads(essay.feedback_json)
                    report = format_detailed_feedback(feedback, essay.word_count)
                    chunks = split_message_text(report)
                    for chunk in chunks:
                        await message.answer(chunk, parse_mode="HTML")
                    return

    welcome_text = (
        f"Assalomu alaykum, <b>{user.full_name if user else 'doʻstim'}</b>! 👋\n\n"
        f"Men <b>IELTS Writing AI Examiner</b> botiman.\n\n"
        f"🎯 <b>Imkoniyatlar:</b>\n"
        f"• <b>Shaxsiy chatda:</b> Pastdagi <b>«✍️ Yangi insho tekshirish»</b> tugmasini bosing — savol va inshoni bosqichma-bosqich yuboring.\n"
        f"• <b>Guruhda:</b> Ustoz tashlagan savolga <b>Reply (Javob)</b> qilib `#task2 [insho]` yozing yoki bitta xabarda `Savol: ... Insho: ...` shaklida yuboring!"
    )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_start_keyboard())


@router.message(Command("check"))
@router.message(Command("new"))
async def handle_new_command(message: types.Message, state: FSMContext):
    if message.chat.type == ChatType.PRIVATE:
        await state.clear()
        await message.answer(
            "Qaysi topshiriq turini tekshirmoqchisiz?",
            reply_markup=get_task_type_keyboard(),
        )


@router.message(Command("help"))
async def handle_help(message: types.Message):
    help_text = (
        "ℹ️ <b>Yordam va Qoidalar:</b>\n\n"
        "1. <b>Guruhlarda ishlatish:</b>\n"
        "   • Ustoz bergan savolga <b>Reply</b> qilib `#task2 [insho]` yuboring.\n"
        "   • Yoki bitta xabarda yozing:\n"
        "     <code>#task2\nSavol: ...\nInsho: ...</code>\n\n"
        "2. <b>Shaxsiy chatda:</b>\n"
        "   • /new yoki «✍️ Yangi insho tekshirish» tugmasini bosing.\n\n"
        "3. <b>Rasmiy IELTS mezonlari:</b>\n"
        "   • Task 2 uchun 250+ so'z (kam bo'lsa Task Response 5.5 dan oshmaydi).\n"
        "   • Task 1 uchun 150+ so'z.\n"
    )
    await message.answer(help_text, parse_mode="HTML")


# ----------------------------------------------------
# FSM Callback & Message Handlers (Shaxsiy Chat uchun)
# ----------------------------------------------------

@router.callback_query(F.data == "fsm:start_check")
async def cb_start_check(query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text(
        "Qaysi topshiriq turini tekshirmoqchisiz?",
        reply_markup=get_task_type_keyboard(),
    )
    await query.answer()


@router.callback_query(F.data == "fsm:help")
async def cb_help(query: types.CallbackQuery):
    await query.answer()
    await handle_help(query.message)


@router.callback_query(F.data == "fsm:cancel")
async def cb_cancel(query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text("Tekshirish bekor qilindi.", reply_markup=get_start_keyboard())
    await query.answer()


@router.callback_query(F.data.startswith("task_type:"))
async def cb_task_type(query: types.CallbackQuery, state: FSMContext):
    task_type = query.data.split(":", 1)[1]
    await state.update_data(task_type=task_type)
    await state.set_state(EssayFSM.waiting_for_prompt)

    prompt_msg = (
        f"Tanlandi: <b>{task_type}</b> ✅\n\n"
        f"<b>1-Qadam:</b> Insho mavzusi / savolini (Task Prompt) yuboring.\n\n"
        f"<i>💡 Savolni kiritish Task Response bahosini 100% aniq chiqarishga yordam beradi. Agar savol bo'lmasa, «Savolsiz davom etish» tugmasini bosing:</i>"
    )
    await query.message.edit_text(prompt_msg, parse_mode="HTML", reply_markup=get_skip_prompt_keyboard())
    await query.answer()


@router.callback_query(F.data == "prompt:skip")
async def cb_skip_prompt(query: types.CallbackQuery, state: FSMContext):
    await state.update_data(task_prompt=None)
    await state.set_state(EssayFSM.waiting_for_essay)
    await query.message.edit_text(
        "<b>2-Qadam:</b> Endi yozgan inshoingiz matnini yuboring (kamida 40 ta so'z):",
        parse_mode="HTML",
    )
    await query.answer()


@router.message(EssayFSM.waiting_for_prompt, F.text)
async def handle_fsm_prompt_text(message: types.Message, state: FSMContext):
    prompt_text = message.text.strip()
    await state.update_data(task_prompt=prompt_text)
    await state.set_state(EssayFSM.waiting_for_essay)
    await message.reply(
        "Savol qabul qilindi! ✅\n\n"
        "<b>2-Qadam:</b> Endi yozgan inshoingiz matnini yuboring (kamida 40 ta so'z):",
        parse_mode="HTML",
    )


@router.message(EssayFSM.waiting_for_essay, F.text)
async def handle_fsm_essay_text(message: types.Message, state: FSMContext):
    user = message.from_user
    chat = message.chat
    essay_text = message.text.strip()
    words = count_words(essay_text)

    if words < 40:
        await message.reply(
            f"⚠️ Insho juda qisqa ({words} ta so'z). Kamida 40 ta so'z bo'lishi kerak. Iltimos to'liqroq yozib qayta yuboring:"
        )
        return

    data = await state.get_data()
    task_type = data.get("task_type", "Task 2")
    task_prompt = data.get("task_prompt")
    await state.clear()

    # Check daily usage limit
    user_id = user.id if user else 0
    is_allowed, limit_msg = await check_and_increment_limits(
        user_id=user_id, chat_id=chat.id, is_private=True
    )
    if not is_allowed:
        await message.reply(f"🚫 {limit_msg}")
        return

    user_mention = (
        f"@{user.username}"
        if (user and user.username)
        else (user.full_name if user else "Foydalanuvchi")
    )

    payload = {
        "user_id": user_id,
        "user_mention": user_mention,
        "chat_id": chat.id,
        "message_id": message.message_id,
        "is_private": True,
        "essay_text": essay_text,
        "word_count": words,
        "task_type": task_type,
        "task_prompt": task_prompt,
    }

    queue_pos = await queue_service.enqueue(payload)
    prompt_info = f"\n📌 <i>Savol: \"{task_prompt[:50]}...\"</i>" if task_prompt else ""
    await message.reply(
        f"📥 Inshoingiz qabul qilindi (<b>{task_type}</b>)!{prompt_info}\n"
        f"⏳ Siz navbatda: <b>#{queue_pos}</b>-o'rindasiz.\n\n"
        f"<i>AI Examiner tahlil qilmoqda, natija tayyor bo'lishi bilan yuboramiz...</i>",
        parse_mode="HTML",
    )


# ----------------------------------------------------
# Guruh va Umumiy Xabarlar Handler'i
# ----------------------------------------------------

@router.message(F.text)
async def handle_general_text_message(message: types.Message):
    user = message.from_user
    chat = message.chat
    text = message.text or ""
    is_private = chat.type == ChatType.PRIVATE

    if user:
        await upsert_user(user.id, user.username, user.full_name)
    if not is_private:
        await upsert_group(chat.id, chat.title)

    from services.filter_service import HASHTAG_PATTERN
    match = HASHTAG_PATTERN.search(text)
    is_reply = bool(message.reply_to_message and message.reply_to_message.text)
    replied_text = message.reply_to_message.text.strip() if is_reply else ""

    # ----------------------------------------------------
    # GURUHDA 1-HOLAT: Ustoz / Admin savol tashlaganda (#task2 ...)
    # ----------------------------------------------------
    if not is_private and match and not is_reply:
        clean_prompt = HASHTAG_PATTERN.sub("", text).strip()
        words = count_words(clean_prompt)
        # Agar so'zlar soni 5 dan 45 tagacha bo'lsa - bu insho emas, SAVOL/TOPIC!
        if 5 <= words < 40:
            matched_tag = match.group(1).lower()
            t_type = "Task 1" if matched_tag == "task1" else "Task 2"
            ack_topic = (
                f"📌 <b>Yangi IELTS topshirig'i ({t_type}) qabul qilindi!</b>\n\n"
                f"📝 <i>\"{clean_prompt}\"</i>\n\n"
                f"👇 Talabalar ushbu xabarga <b>Reply (Javob berish)</b> qilib o'z insholarini yozishlari mumkin. "
                f"Bot inshoni avtomatik tekshirib, IELTS mezonlari bo'yicha baholaydi."
            )
            await message.reply(ack_topic, parse_mode="HTML")
            return

    # ----------------------------------------------------
    # GURUHDA 2-HOLAT: Talaba savolga Reply qilib insho yuborganda
    # ----------------------------------------------------
    task_type = "Task 2"
    task_prompt = None
    clean_text = None
    word_count = 0

    if not is_private and is_reply:
        raw_words = count_words(text)
        # Reply qilingan xabarda mavzu yoki botning topshiriq xabari bormi?
        replied_has_tag = bool(HASHTAG_PATTERN.search(replied_text))
        is_bot_topic = "topshirig'i" in replied_text.lower() or "📝" in replied_text

        if raw_words >= 40 and (match or replied_has_tag or is_bot_topic):
            clean_text = HASHTAG_PATTERN.sub("", text).strip()
            word_count = count_words(clean_text)
            task_type = "Task 1" if "task 1" in replied_text.lower() or (match and "task1" in match.group(1).lower()) else "Task 2"

            # Savol matnini tozalab olish
            clean_prompt = HASHTAG_PATTERN.sub("", replied_text).strip()
            if '\"' in clean_prompt:
                parts = clean_prompt.split('\"')
                if len(parts) >= 2:
                    clean_prompt = parts[1]
            task_prompt = clean_prompt
            logger.info(f"Group Reply detected as essay! Prompt: {task_prompt[:40]}...")

    # Agar yuqoridagi Reply holati bo'lmasa, standart 3-tier filtrdan o'tkazamiz
    if clean_text is None:
        is_valid, reject_reason, clean_text, word_count, task_type, task_prompt = filter_essay_text(text)

        # Agar bu reply bo'lsa va task_prompt hali yo'q bo'lsa, reply_to_message dan olamiz
        if is_valid and not task_prompt and is_reply:
            if not replied_text.startswith("📥") and not replied_text.startswith("📊"):
                task_prompt = HASHTAG_PATTERN.sub("", replied_text).strip()

        # Guruhda insho bo'lmagan oddiy suhbatlarga jim turamiz
        if not is_private and not is_valid:
            return

        # Shaxsiy chatda hashtag bo'lmasa FSM menyusini chiqaramiz
        if is_private and not is_valid:
            if reject_reason != "Bot komandasi":
                await message.reply(
                    f"Assalomu alaykum! Insho tekshirish uchun pastdagi <b>«✍️ Yangi insho tekshirish»</b> tugmasini bosing yoki xabaringizga <code>#task2</code> (yoki <code>#essay</code>) hashtag qo'shing.",
                    parse_mode="HTML",
                    reply_markup=get_start_keyboard(),
                )
            return

    # Limit tekshiruvi (Admin 7326292681 uchun cheksiz)
    user_id = user.id if user else 0
    is_allowed, limit_msg = await check_and_increment_limits(
        user_id=user_id, chat_id=chat.id, is_private=is_private
    )
    if not is_allowed:
        await message.reply(f"🚫 {limit_msg}")
        return

    user_mention = (
        f"@{user.username}"
        if (user and user.username)
        else (user.full_name if user else "Foydalanuvchi")
    )

    payload = {
        "user_id": user_id,
        "user_mention": user_mention,
        "chat_id": chat.id,
        "message_id": message.message_id,
        "is_private": is_private,
        "essay_text": clean_text,
        "word_count": word_count,
        "task_type": task_type,
        "task_prompt": task_prompt,
    }

    queue_pos = await queue_service.enqueue(payload)

    if task_prompt:
        prompt_snippet = task_prompt[:45] + "..." if len(task_prompt) > 45 else task_prompt
        prompt_line = f"\n📌 <i>Mavzu: \"{prompt_snippet}\"</i>"
    else:
        prompt_line = "\n💡 <i>Maslahat: Savolga Reply qilib yuborsangiz, Task Response 100% aniq baholanadi.</i>"

    ack_text = (
        f"📥 {user_mention}, inshoingiz qabul qilindi (<b>{task_type}</b>)!{prompt_line}\n"
        f"⏳ Siz navbatda: <b>#{queue_pos}</b>-o'rindasiz.\n\n"
        f"<i>AI Examiner tahlil qilmoqda, natija tayyor bo'lishi bilan xabar beramiz...</i>"
    )
    await message.reply(ack_text, parse_mode="HTML")
