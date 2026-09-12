import html
import json
import logging
from typing import Optional
from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from config import settings
from db.database import (
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
from db.models import Essay
from services.report_service import (
    calculate_group_report_data,
    format_report_text,
    generate_report_chart,
    generate_report_excel,
)
from services.filter_service import (
    filter_essay_text,
    count_words,
    is_probable_topic,
    HASHTAG_PATTERN,
    TOPIC_HASHTAG_PATTERN,
    MIN_WORD_COUNT,
    MAX_WORD_COUNT,
)
from services.queue_service import queue_service
from services.worker import format_detailed_feedback, split_message_text

logger = logging.getLogger(__name__)
router = Router()

# In-memory storage for pending topic replacements: chat_id -> dict
PENDING_TOPIC_REPLACEMENTS = {}


async def is_group_admin(bot: types.Bot, chat_id: int, user: Optional[types.User]) -> bool:
    """Checks if user has group administrator privileges."""
    if not user:
        return False
    if settings.is_admin(user.id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user.id)
        if member.status in ["creator", "administrator"]:
            return True
    except Exception:
        pass
    role = await check_user_role_in_group(chat_id, user.username, user.id)
    return role == "admin"


async def is_teacher_or_admin(bot: types.Bot, chat_id: int, user: Optional[types.User]) -> bool:
    """Checks if user is recognized as a teacher or admin in this group."""
    if not user:
        return False
    if settings.is_admin(user.id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user.id)
        if member.status in ["creator", "administrator"]:
            return True
    except Exception:
        pass
    role = await check_user_role_in_group(chat_id, user.username, user.id)
    return role in ["teacher", "admin"]


class EssayFSM(StatesGroup):
    waiting_for_task_type = State()
    waiting_for_prompt = State()
    waiting_for_essay = State()


def get_start_keyboard(is_teacher: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="✍️ Yangi insho tekshirish", callback_data="fsm:start_check"
            )
        ],
    ]
    if is_teacher:
        buttons.append([
            InlineKeyboardButton(
                text="🏫 Mening guruhlarim (Ustoz hisoboti)", callback_data="teacher:my_groups"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="ℹ️ Qoidalar va Yordam", callback_data="fsm:help"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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


def get_topic_replace_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Yangi savolga almashtirish",
                    callback_data="topic:confirm_replace",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish (Eski savol qolsin)",
                    callback_data="topic:cancel_replace",
                ),
            ],
        ]
    )


@router.message(CommandStart())
async def handle_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)

    # Deep linking check (e.g. /start report_12 or /start groupreport_-1001234)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("groupreport_"):
        gid_str = parts[1].replace("groupreport_", "")
        try:
            target_gid = int(gid_str)
            can_see = await is_teacher_or_admin(message.bot, target_gid, user)
            if can_see:
                load_msg = await message.answer("⏳ <i>Guruh hisoboti va grafiklar yuklanmoqda...</i>", parse_mode="HTML")
                await deliver_teacher_group_report(message.bot, user.id, target_gid, status_message=load_msg)
                return
            else:
                await message.answer("🚫 Ushbu guruh hisobotini faqat uning ustozi yoki admini ko'ra oladi.")
                return
        except Exception as e:
            logger.error(f"Error delivering deep-link group report: {e}", exc_info=True)

    if len(parts) > 1 and parts[1].startswith("report_"):
        essay_id_str = parts[1].replace("report_", "")
        if essay_id_str.isdigit():
            essay_id = int(essay_id_str)
            async with get_session() as session:
                essay = await session.get(Essay, essay_id)
                if not essay:
                    await message.answer(
                        "⚠️ <b>Hisobot topilmadi yoki oʻchirilgan boʻlishi mumkin.</b>",
                        parse_mode="HTML",
                    )
                    return

                # Check if current user is the essay author or admin
                user_id = user.id if user else 0
                if essay.user_id != user_id and not settings.is_admin(user_id):
                    await message.answer(
                        "🚫 <b>Ruxsat berilmadi!</b>\n\n"
                        "Bu sizga tegishli essay emas. Faqat insho yuborgan foydalanuvchi ushbu hisobotni koʻra oladi.",
                        parse_mode="HTML",
                    )
                    return

                if essay.feedback_json:
                    feedback = json.loads(essay.feedback_json)
                    report = format_detailed_feedback(feedback, essay.word_count)
                    chunks = split_message_text(report)
                    for chunk in chunks:
                        await message.answer(chunk, parse_mode="HTML")
                    return

    # If in a group, send a simple instructional message WITHOUT buttons
    if message.chat.type != ChatType.PRIVATE:
        await upsert_group(message.chat.id, message.chat.title)
        group_welcome_text = (
            f"Assalomu alaykum! 👋\n\n"
            f"🤖 <b>IELTS Writing AI Examiner</b> guruhingizda faol.\n\n"
            f"📌 <b>Ustoz uchun:</b> Yangi mavzu / savol kiritish uchun <code>/new [Savol]</code> yoki <code>#task2 [Savol matni]</code> yuboring.\n"
            f"✍️ <b>Oʻquvchilar uchun:</b> Savolga <b>Reply (Javob)</b> qilib insho yuboring yoki guruhga <code>#essay [insho]</code> deb tashlang.\n\n"
            f"<i>Bot insholarni avtomatik tekshirib, IELTS mezonlari boʻyicha baholab boradi.</i>"
        )
        await message.answer(group_welcome_text, parse_mode="HTML")
        return

    teacher_groups = await get_user_teacher_groups(user.username, user.id) if user else []
    is_teacher = len(teacher_groups) > 0

    welcome_text = (
        f"Assalomu alaykum, <b>{user.full_name if user else 'doʻstim'}</b>! 👋\n\n"
        f"Men <b>IELTS Writing AI Examiner</b> botiman.\n\n"
        f"🎯 <b>Imkoniyatlar:</b>\n"
        f"• <b>Shaxsiy chatda:</b> Pastdagi <b>«✍️ Yangi insho tekshirish»</b> tugmasini bosing — savol va inshoni bosqichma-bosqich yuboring.\n"
        f"• <b>Guruhda:</b> Ustoz <code>/new</code> yoki <code>#task2</code> bilan mavzu e'lon qiladi. O'quvchilar savolga <b>Reply</b> qilib yoki <code>#essay</code> bilan o'z insholarini yuborishadi!"
    )
    if is_teacher:
        welcome_text += (
            f"\n\n👨‍🏫 <b>Ustoz bo'limi:</b> Siz <b>{len(teacher_groups)} ta</b> guruhda ustoz/admin sifatida qayd etilgansiz. "
            f"Guruhdagi o'quvchilar natijalari, tahliliy grafik va Excel hisobotlarini olish uchun pastdagi <b>«🏫 Mening guruhlarim»</b> tugmasini bosing."
        )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_start_keyboard(is_teacher=is_teacher))


@router.message(Command("check"))
@router.message(Command("new"))
async def handle_new_command(message: types.Message, state: FSMContext):
    if message.chat.type == ChatType.PRIVATE:
        await state.clear()
        await state.update_data(task_type="Task 2")
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            prompt_text = parts[1].strip()
            await state.update_data(prompt=prompt_text)
            await state.set_state(EssayFSM.waiting_for_essay)
            await message.answer(
                f"✅ <b>IELTS Task 2 savoli qabul qilindi:</b>\n<i>\"{prompt_text}\"</i>\n\n"
                "<b>2-Qadam:</b> Endi ushbu mavzu bo'yicha inshoingizni matn sifatida yuboring:\n"
                "(IELTS Task 2 uchun kamida 250 so'z yozish tavsiya etiladi)",
                parse_mode="HTML",
            )
            return

        await state.set_state(EssayFSM.waiting_for_prompt)
        prompt_msg = (
            "<b>✍️ Yangi tekshirish sessiyasi boshlandi!</b>\n\n"
            "<b>1-Qadam:</b> Insho mavzusi / savolini (Task 2 Prompt) yuboring.\n\n"
            "<i>💡 Savolni kiritish Task Response bahosini 100% aniq chiqarishga yordam beradi. Agar savol bo'lmasa, «Savolsiz davom etish» tugmasini bosing:</i>"
        )
        await message.answer(prompt_msg, parse_mode="HTML", reply_markup=get_skip_prompt_keyboard())
    else:
        user = message.from_user
        can_post = await is_teacher_or_admin(message.bot, message.chat.id, user)
        if not can_post:
            await message.reply(
                "🚫 <b>Guruhda yangi savol/sessiyani faqat Ustoz yoki Admin boshlashi mumkin.</b>\n\n"
                "Talabalar faol savolni ko'rish uchun <code>/topic</code> dan foydalanishlari, "
                "insho topshirish uchun esa faol savolga <b>Reply</b> qilishlari yoki <code>#essay</code> yozishlari mumkin.",
                parse_mode="HTML",
            )
            return

        parts = (message.text or "").split(maxsplit=1)
        prompt_text = None
        if len(parts) > 1 and parts[1].strip():
            prompt_text = parts[1].strip()
        elif message.reply_to_message and message.reply_to_message.text:
            prompt_text = message.reply_to_message.text.strip()

        if prompt_text:
            await process_new_group_topic(message, prompt_text)
        else:
            await message.reply(
                "✍️ <b>Yangi IELTS Task 2 savoli (sessiya)ni boshlash:</b>\n\n"
                "Savol matnini quyidagi usullardan biri orqali yuborishingiz mumkin:\n"
                "1️⃣ <code>/new [Savol matni]</code> (masalan: <code>/new Some people believe that...</code>)\n"
                "2️⃣ Ushbu xabarga <b>Reply (Javob berish)</b> qilib savol matnini yozing\n"
                "3️⃣ Yoki to'g'ridan-to'g'ri <code>#task2 [Savol matni]</code> deb yuboring.\n\n"
                "<i>Savol e'lon qilingach, bot talabalardan insholarni qabul qilishni boshlaydi.</i>",
                parse_mode="HTML",
            )


@router.message(Command("help"))
async def handle_help(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        help_text = (
            "ℹ️ <b>Guruhda botdan foydalanish:</b>\n\n"
            "1. <b>Ustoz:</b> Yangi savol/sessiya boshlash uchun <code>/new [Savol matni]</code> yoki <code>#task2 [Savol matni]</code> yuboradi.\n"
            "2. <b>O'quvchi:</b> Savolga <b>Reply</b> qilib insho yuboradi yoki guruhga <code>#essay [insho]</code> deb tashlaydi.\n"
            "3. <b>Faol mavzuni ko'rish:</b> <code>/topic</code>\n"
            "4. <b>Mavzuni to'xtatish:</b> <code>/stop</code> (faqat ustoz va adminlar)\n"
            "5. <b>Ustoz tayinlash:</b> <code>/ustoz @mentor</code> (faqat adminlar)\n\n"
            "<i>IELTS Task 2 mezonlari bo'yicha insho kamida 250 so'z bo'lishi tavsiya etiladi.</i>"
        )
    else:
        help_text = (
            "ℹ️ <b>Yordam va Qoidalar:</b>\n\n"
            "1. <b>Shaxsiy chatda:</b>\n"
            "   • /new yoki «✍️ Yangi insho tekshirish» tugmasini bosing.\n\n"
            "2. <b>Guruhlarda ishlatish:</b>\n"
            "   • Ustoz yangi savolni <code>/new [Savol]</code> yoki <code>#task2 [Savol]</code> deb tashlaydi.\n"
            "   • O'quvchilar o'sha savolga <b>Reply</b> qilib yoki <code>#essay</code> bilan insho yuboradi.\n\n"
            "3. <b>Rasmiy IELTS mezonlari:</b>\n"
            "   • Task 2 inshosi uchun 250+ so'z (kam bo'lsa Task Response 5.5 dan oshmaydi).\n"
        )
    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("topic"))
@router.message(Command("savol"))
async def handle_topic_command(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.reply("Ushbu buyruq guruhlarda faol mavzuni boshqarish uchun ishlatiladi.")
        return

    parts = (message.text or "").split(maxsplit=1)
    prompt_text = None
    if len(parts) > 1 and parts[1].strip():
        prompt_text = parts[1].strip()
    elif message.reply_to_message and message.reply_to_message.text:
        prompt_text = message.reply_to_message.text.strip()

    if prompt_text:
        can_post = await is_teacher_or_admin(message.bot, message.chat.id, message.from_user)
        if not can_post:
            await message.reply("🚫 Guruhda faqat Ustoz yoki Admin yangi mavzu kiritishi mumkin.")
            return
        await process_new_group_topic(message, prompt_text)
        return

    existing = await get_group_topic(message.chat.id)
    if not existing:
        await message.reply(
            "ℹ️ <b>Guruhda hozircha faol IELTS savoli belgilanmagan.</b>\n\n"
            "Ustoz yangi savol kiritish uchun <code>/new [Savol matni]</code> yoki <code>#task2 [Savol matni]</code> yuborishi mumkin.",
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"📌 <b>Guruhning hozirgi faol IELTS Task 2 savoli:</b>\n\n"
            f"📝 <i>\"{existing.topic_text}\"</i>\n\n"
            "🟢 <b>Holat:</b> Insholar qabul qilinmoqda (Bot kutyapti...)\n\n"
            "<i>Mavzuni yakunlash uchun: /stop</i>",
            parse_mode="HTML",
        )


@router.message(Command("stop"))
@router.message(Command("deltopic"))
@router.message(Command("stoptopic"))
@router.message(Command("yakunlash"))
async def handle_deltopic_command(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        return
    user = message.from_user
    can_stop = await is_teacher_or_admin(message.bot, message.chat.id, user)
    if not can_stop:
        await message.reply("🚫 Faqat guruh ustozi yoki admini mavzu qabulini yakunlashi mumkin.")
        return

    cleared = await clear_group_topic(message.chat.id)
    if cleared:
        await message.reply(
            "🛑 <b>IELTS Task 2 qabuli yakunlandi!</b>\n\n"
            "Ushbu mavzu bo'yicha insholarni qabul qilish to'xtatildi. Yangi topshiriq boshlash uchun ustoz yana <code>#task2 [Savol matni]</code> yuborishi mumkin.",
            parse_mode="HTML",
        )
    else:
        await message.reply("Guruhda hozircha faol savol mavjud emas.")


@router.message(Command("ustoz"))
async def handle_set_teacher_command(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.reply("Ushbu buyruq faqat guruhlarda ishlatiladi.")
        return

    user = message.from_user
    can_assign = await is_group_admin(message.bot, message.chat.id, user)
    if not can_assign:
        await message.reply("🚫 Faqat guruh adminlari ustoz tayinlashi mumkin.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "💡 <b>Ustoz tayinlash uchun username kiriting:</b>\n\n"
            "Masalan: <code>/ustoz @mentor</code>",
            parse_mode="HTML",
        )
        return

    target_username = parts[1].strip().lstrip("@")
    if not target_username:
        await message.reply("⚠️ Noto'g'ri username kiritildi.")
        return

    await set_group_user_role(
        chat_id=message.chat.id,
        username=target_username,
        role="teacher",
        assigned_by=user.id if user else None,
    )
    await message.reply(
        f"✅ <b>@{target_username}</b> ushbu guruhga rasmiy <b>Ustoz</b> sifatida biriktirildi!\n\n"
        f"Endi u yangi mavzu (<code>#task2</code>) kiritishi va savol qabulini yakunlashi (<code>/stop</code>) mumkin.",
        parse_mode="HTML",
    )


@router.message(Command("admin"))
async def handle_set_admin_command(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.reply("Ushbu buyruq faqat guruhlarda ishlatiladi.")
        return

    user = message.from_user
    can_assign = await is_group_admin(message.bot, message.chat.id, user)
    if not can_assign:
        await message.reply("🚫 Faqat guruh adminlari yangi admin tayinlashi mumkin.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "💡 <b>Admin tayinlash uchun username kiriting:</b>\n\n"
            "Masalan: <code>/admin @username</code>",
            parse_mode="HTML",
        )
        return

    target_username = parts[1].strip().lstrip("@")
    if not target_username:
        await message.reply("⚠️ Noto'g'ri username kiritildi.")
        return

    await set_group_user_role(
        chat_id=message.chat.id,
        username=target_username,
        role="admin",
        assigned_by=user.id if user else None,
    )
    await message.reply(
        f"✅ <b>@{target_username}</b> ushbu guruhga <b>Admin</b> sifatida biriktirildi!",
        parse_mode="HTML",
    )


@router.message(Command("delustoz"))
@router.message(Command("deladmin"))
async def handle_del_role_command(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    user = message.from_user
    can_assign = await is_group_admin(message.bot, message.chat.id, user)
    if not can_assign:
        await message.reply("🚫 Faqat guruh adminlari rollarni bekor qilishi mumkin.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "💡 <b>Rolni bekor qilish uchun username kiriting:</b>\n\n"
            "Masalan: <code>/delustoz @mentor</code>",
            parse_mode="HTML",
        )
        return

    target_username = parts[1].strip().lstrip("@")
    removed = await remove_group_user_role(message.chat.id, target_username)
    if removed:
        await message.reply(
            f"✅ <b>@{target_username}</b> roli bekor qilindi.",
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"⚠️ <b>@{target_username}</b> ushbu guruhda biriktirilgan rollarda topilmadi.",
            parse_mode="HTML",
        )


@router.message(Command("ustozlar"))
@router.message(Command("rollar"))
async def handle_list_roles_command(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    roles = await get_group_roles(message.chat.id)
    if not roles:
        await message.reply(
            "ℹ️ <b>Guruhda hozircha alohida ustoz/admin biriktirilmagan.</b>\n\n"
            "Telegram guruhining o'z adminlari avtomatik ravishda to'liq huquqqa ega.\n"
            "Yangi ustoz qo'shish uchun: <code>/ustoz @mentor</code>",
            parse_mode="HTML",
        )
        return

    teachers = [f"• @{r.username}" for r in roles if r.role == "teacher"]
    admins = [f"• @{r.username}" for r in roles if r.role == "admin"]

    lines = ["👥 <b>Guruhda tayinlangan ustoz va adminlar:</b>"]
    if teachers:
        lines.append("\n👨‍🏫 <b>Ustozlar:</b>")
        lines.extend(teachers)
    if admins:
        lines.append("\n🛡 <b>Adminlar:</b>")
        lines.extend(admins)

    lines.append("\n<i>Yangi qo'shish uchun: /ustoz @username</i>")
    await message.reply("\n".join(lines), parse_mode="HTML")


async def deliver_teacher_group_report(
    bot,
    target_user_id: int,
    group_chat_id: int,
    status_message: Optional[types.Message] = None,
):
    """Generates the full report for group_chat_id and delivers it directly to target_user_id's private chat."""
    # 1. Faol mavzuni olish (agar mavjud bo'lsa)
    active_topic = await get_group_topic(group_chat_id)
    topic_since = active_topic.created_at if active_topic else None

    # 2. Mavzu bo'yicha insholarni olish
    submissions = await get_group_topic_submissions(group_chat_id, since=topic_since)

    # 3. Guruhdagi barcha o'quvchilar va a'zolar soni
    tracked_users = await get_group_tracked_users(group_chat_id)

    # Telegram guruhidagi jami a'zolar sonini aniqlash
    total_members_count = None
    try:
        total_members_count = await bot.get_chat_member_count(group_chat_id)
    except Exception:
        pass

    # 4. O'quvchilarning oldingi ballari (tarixi)
    historical_scores_map = {}
    for essay, _ in submissions:
        uid = essay.user_id
        if uid not in historical_scores_map:
            scores = await get_student_historical_scores(group_chat_id, uid)
            historical_scores_map[uid] = scores

    # 5. Hisobot ma'lumotlarini hisoblash
    report_data = calculate_group_report_data(
        topic=active_topic,
        submissions=submissions,
        historical_scores_map=historical_scores_map,
        tracked_users=tracked_users,
        total_members_count=total_members_count,
    )

    # 6. Formatlash: Matn, Grafik (PNG), Excel (XLSX)
    report_text = format_report_text(report_data)
    chart_bytes = generate_report_chart(report_data)
    excel_bytes = generate_report_excel(report_data)

    # 7. Shaxsiy chatga yuborish
    # Rasm va xulosa matni
    chart_photo = BufferedInputFile(chart_bytes, filename="ielts_group_report.png")
    if len(report_text) <= 1024:
        await bot.send_photo(chat_id=target_user_id, photo=chart_photo, caption=report_text, parse_mode="HTML")
    else:
        await bot.send_photo(chat_id=target_user_id, photo=chart_photo)
        chunks = split_message_text(report_text, max_length=4000)
        for chunk in chunks:
            await bot.send_message(chat_id=target_user_id, text=chunk, parse_mode="HTML")

    # Excel hujjati va qaytish tugmalari
    doc_name = f"IELTS_Hisobot_{abs(group_chat_id)}.xlsx"
    excel_doc = BufferedInputFile(excel_bytes, filename=doc_name)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"teacher:report:{group_chat_id}"),
                InlineKeyboardButton(text="🔙 Guruhlarim ro'yxati", callback_data="teacher:my_groups"),
            ]
        ]
    )
    await bot.send_document(
        chat_id=target_user_id,
        document=excel_doc,
        caption="📊 <b>Batafsil Excel hisoboti</b> (baholar, mezonlar va so'zlar soni bilan)",
        parse_mode="HTML",
        reply_markup=kb,
    )

    if status_message:
        try:
            await status_message.delete()
        except Exception:
            pass


@router.message(Command("report"))
@router.message(Command("hisobot"))
@router.message(Command("stats"))
async def handle_report_command(message: types.Message):
    user = message.from_user
    bot = message.bot

    # 1-HOLAT: Shaxsiy chatda chaqirilsa
    if message.chat.type == ChatType.PRIVATE:
        await show_teacher_groups(message)
        return

    # 2-HOLAT: Guruhda chaqirilganda
    can_view = await is_teacher_or_admin(bot, message.chat.id, user)
    if not can_view:
        await message.reply(
            "🚫 Guruh hisobotini faqat <b>Ustoz</b> yoki <b>Admin</b> ko'rishi mumkin.",
            parse_mode="HTML",
        )
        return

    bot_user = await bot.get_me()
    bot_username = bot_user.username or "esseycheckerbot"

    # Guruhda katta hisobotlarni tashlamaymiz — shaxsiy chatga yuboramiz!
    status_msg = await message.reply("⏳ <i>Hisobot tayyorlanmoqda va shaxsiy chatingizga yuborilmoqda...</i>", parse_mode="HTML")

    try:
        # Shaxsiy chatga yuborishga urinib ko'ramiz:
        await deliver_teacher_group_report(bot, user.id, message.chat.id)
        mention = user.mention_html()
        await status_msg.edit_text(
            f"📩 <b>Hurmatli ustoz {mention}, guruh hisoboti, tahliliy grafik va Excel jadvali shaxsiy chatingizga yuborildi!</b>\n\n"
            f"👉 <a href=\"https://t.me/{bot_username}\">Botga o'tib hisobotni ko'rish</a>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Could not send PM report directly to teacher {user.id}: {e}")
        mention = user.mention_html()
        await status_msg.edit_text(
            f"⚠️ <b>Hurmatli ustoz {mention}, hisobotni shaxsiy chatingizda olishingiz uchun iltimos botga kiring va Start bosing:</b>\n\n"
            f"👉 <a href=\"https://t.me/{bot_username}?start=groupreport_{message.chat.id}\">Botni ochish va hisobotni olish</a>\n\n"
            f"<i>(Guruh umumiy xabarida o'quvchilar hisobotini ochiq qoldirmaslik uchun shaxsiy chatda beriladi).</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("mygroups"))
@router.message(Command("guruhlarim"))
@router.callback_query(F.data == "teacher:my_groups")
async def show_teacher_groups(event: types.Message | types.CallbackQuery):
    user = event.from_user
    is_callback = isinstance(event, types.CallbackQuery)

    groups = await get_user_teacher_groups(user.username, user.id)
    if not groups:
        text = (
            "ℹ️ <b>Siz hali birorta guruhda Ustoz yoki Admin sifatida biriktirilmagansiz.</b>\n\n"
            "Guruh admini sizni ustoz qilib belgilashi uchun guruhda quyidagicha yozishi lozim:\n"
            f"<code>/ustoz @{user.username or 'username'}</code>"
        )
        kb_no = get_start_keyboard(is_teacher=False)
        if is_callback:
            try:
                if event.message and event.message.text is not None:
                    await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb_no)
                else:
                    await event.message.answer(text, parse_mode="HTML", reply_markup=kb_no)
            except Exception:
                await event.message.answer(text, parse_mode="HTML", reply_markup=kb_no)
            await event.answer()
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=kb_no)
        return

    buttons = []
    for gid, gtitle in groups:
        buttons.append([
            InlineKeyboardButton(
                text=f"👥 {gtitle}",
                callback_data=f"teacher:report:{gid}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Bosh menyu", callback_data="teacher:back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    text = (
        "👨‍🏫 <b>Mening guruhlarim:</b>\n\n"
        "Siz quyidagi guruhlarda ustoz/admin sifatida qayd etilgansiz. "
        "O'quvchilar tahlili, grafik va Excel hisobotini shaxsiy chatingizda olish uchun kerakli guruhni tanlang:"
    )
    if is_callback:
        try:
            if event.message and event.message.text is not None:
                await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            else:
                await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("teacher:report:"))
async def cb_teacher_group_report(query: types.CallbackQuery):
    user = query.from_user
    bot = query.bot
    gid_str = query.data.replace("teacher:report:", "")
    try:
        gid = int(gid_str)
    except ValueError:
        await query.answer("Noto'g'ri guruh ID", show_alert=True)
        return

    can_see = await is_teacher_or_admin(bot, gid, user)
    if not can_see:
        await query.answer("Siz ushbu guruhda ustoz emassiz!", show_alert=True)
        return

    await query.answer("Hisobot yuklanmoqda...")
    load_msg = await query.message.answer("⏳ <i>Guruh hisoboti va grafiklar yuklanmoqda...</i>", parse_mode="HTML")
    try:
        await deliver_teacher_group_report(bot, user.id, gid, status_message=load_msg)
    except Exception as e:
        logger.error(f"Error delivering teacher group report: {e}", exc_info=True)
        await load_msg.edit_text(
            "⚠️ <b>Kechirasiz, hisobot tayyorlashda nosozlik yuz berdi.</b>\n"
            "Biz uni tuzatish ustida ishlayapmiz. Iltimos, birozdan so'ng qayta urinib ko'ring.",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "teacher:back_home")
async def cb_teacher_back_home(query: types.CallbackQuery):
    user = query.from_user
    teacher_groups = await get_user_teacher_groups(user.username, user.id)
    is_teacher = len(teacher_groups) > 0
    welcome_text = (
        f"Assalomu alaykum, <b>{user.full_name}</b>! 👋\n\n"
        f"Bosh menyuga qaytdingiz. Kerakli bo'limni tanlang:"
    )
    kb = get_start_keyboard(is_teacher=is_teacher)
    try:
        if query.message and query.message.text is not None:
            await query.message.edit_text(welcome_text, parse_mode="HTML", reply_markup=kb)
        else:
            await query.message.answer(welcome_text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.answer(welcome_text, parse_mode="HTML", reply_markup=kb)
    await query.answer()


# ----------------------------------------------------
# FSM Callback & Message Handlers (Shaxsiy Chat uchun)
# ----------------------------------------------------

@router.callback_query(F.data == "fsm:start_check")
async def cb_start_check(query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(task_type="Task 2")
    await state.set_state(EssayFSM.waiting_for_prompt)
    prompt_msg = (
        "<b>1-Qadam:</b> Insho mavzusi / savolini (Task 2 Prompt) yuboring.\n\n"
        "<i>💡 Savolni kiritish Task Response bahosini 100% aniq chiqarishga yordam beradi. Agar savol bo'lmasa, «Savolsiz davom etish» tugmasini bosing:</i>"
    )
    await query.message.edit_text(prompt_msg, parse_mode="HTML", reply_markup=get_skip_prompt_keyboard())
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


@router.callback_query(F.data.startswith("report:") | F.data.startswith("view_report:"))
async def cb_view_report(query: types.CallbackQuery):
    data = query.data or ""
    essay_id_str = data.split(":")[-1]
    if not essay_id_str.isdigit():
        await query.answer("Xatolik yuz berdi.", show_alert=True)
        return

    essay_id = int(essay_id_str)
    user = query.from_user
    user_id = user.id if user else 0

    async with get_session() as session:
        essay = await session.get(Essay, essay_id)
        if not essay:
            await query.answer("⚠️ Hisobot topilmadi.", show_alert=True)
            return

        if essay.user_id != user_id and not settings.is_admin(user_id):
            await query.answer(
                "🚫 Bu sizga tegishli essay emas! Sizda uni koʻrish uchun ruxsat yoʻq.",
                show_alert=True,
            )
            return

        if essay.feedback_json:
            feedback = json.loads(essay.feedback_json)
            report = format_detailed_feedback(feedback, essay.word_count)
            chunks = split_message_text(report)
            try:
                for chunk in chunks:
                    await query.bot.send_message(chat_id=user_id, text=chunk, parse_mode="HTML")
                await query.answer("✅ Toʻliq hisobot shaxsiy botingizga yuborildi!", show_alert=True)
            except Exception:
                bot_me = await query.bot.get_me()
                await query.answer(
                    f"⚠️ Hisobotni olish uchun avval botga kiring: @{bot_me.username}",
                    show_alert=True,
                )


@router.callback_query(F.data == "topic:confirm_replace")
async def cb_confirm_replace_topic(query: types.CallbackQuery):
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    pending = PENDING_TOPIC_REPLACEMENTS.get(chat_id)
    if not pending:
        await query.answer("Yangi savol topilmadi yoki eskirgan.", show_alert=True)
        return

    can_manage = await is_teacher_or_admin(query.bot, chat_id, query.from_user)
    if not can_manage:
        await query.answer(
            "Faqat ustoz yoki admin mavzuni almashtirishi mumkin!",
            show_alert=True,
        )
        return

    new_topic_text = pending["topic_text"]
    new_msg_id = pending.get("message_id")
    del PENDING_TOPIC_REPLACEMENTS[chat_id]

    ack_topic = (
        "✅ <b>Faol IELTS Task 2 savoli yangilandi!</b>\n\n"
        f"📝 <i>\"{new_topic_text}\"</i>\n\n"
        "🟢 <b>Holat:</b> Yangi mavzu bo'yicha insholar qabul qilinmoqda (Bot kutyapti...)\n\n"
        "👇 Talabalar ushbu xabarga <b>Reply</b> qilib yoki guruhga <code>#essay</code> bilan o'z insholarini yuborishlari mumkin."
    )
    await query.message.edit_text(ack_topic, parse_mode="HTML")
    await set_group_topic(
        chat_id=chat_id,
        topic_text=new_topic_text,
        message_id=new_msg_id,
        created_by=user_id,
        announcement_msg_id=query.message.message_id,
    )
    try:
        await query.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=query.message.message_id,
            disable_notification=True,
        )
    except Exception:
        pass
    await query.answer("Mavzu yangilandi!")


@router.callback_query(F.data == "topic:cancel_replace")
async def cb_cancel_replace_topic(query: types.CallbackQuery):
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    pending = PENDING_TOPIC_REPLACEMENTS.get(chat_id)
    if not pending:
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer()
        return

    can_manage = await is_teacher_or_admin(query.bot, chat_id, query.from_user)
    if not can_manage:
        await query.answer(
            "Faqat ustoz yoki admin buni bekor qilishi mumkin!",
            show_alert=True,
        )
        return

    del PENDING_TOPIC_REPLACEMENTS[chat_id]
    existing = await get_group_topic(chat_id)
    active_snippet = (
        f"\n\n📌 <b>Amaldagi faol mavzu:</b>\n<i>\"{existing.topic_text}\"</i>"
        if existing
        else ""
    )
    await query.message.edit_text(
        f"❌ Yangi savol bekor qilindi. Guruhda avvalgi faol savol o'z kuchida qoldi.{active_snippet}",
        parse_mode="HTML",
    )
    await query.answer("Bekor qilindi!")


@router.callback_query(F.data.startswith("task_type:"))
async def cb_task_type(query: types.CallbackQuery, state: FSMContext):
    await state.update_data(task_type="Task 2")
    await state.set_state(EssayFSM.waiting_for_prompt)

    prompt_msg = (
        "<b>1-Qadam:</b> Insho mavzusi / savolini (Task 2 Prompt) yuboring.\n\n"
        "<i>💡 Savolni kiritish Task Response bahosini 100% aniq chiqarishga yordam beradi. Agar savol bo'lmasa, «Savolsiz davom etish» tugmasini bosing:</i>"
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

    if words < MIN_WORD_COUNT:
        await message.reply(
            f"⚠️ Insho juda qisqa ({words} ta so'z). Kamida {MIN_WORD_COUNT} ta so'z bo'lishi kerak. Iltimos to'liqroq yozib qayta yuboring:"
        )
        return

    if words > MAX_WORD_COUNT:
        await message.reply(
            f"⚠️ Insho hajmi juda katta ({words} ta so'z). IELTS Task 2 inshosi {MAX_WORD_COUNT} ta so'zdan oshmasligi lozim. Iltimos, ixchamroq qilib qayta yuboring:"
        )
        return

    data = await state.get_data()
    task_type = data.get("task_type", "Task 2")
    task_prompt = data.get("task_prompt")

    # Anti-Spam / In-Flight lock check:
    user_id = user.id if user else 0
    if await queue_service.is_user_inflight(user_id):
        await message.reply(
            "⏳ <b>Inshoingiz hozir tekshirilmoqda!</b>\n\n"
            "Iltimos, avvalgi insho tahlili yakunlanishini kuting va shundan so'ng yangisini yuboring.",
            parse_mode="HTML",
        )
        return

    await state.clear()

    # Check daily usage limit
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

    await queue_service.set_user_inflight(user_id, ttl=45)
    queue_pos = await queue_service.enqueue(payload)
    prompt_info = f"\n📌 <i>Savol: \"{html.escape(task_prompt[:50])}...\"</i>" if task_prompt else ""
    await message.reply(
        f"📥 Inshoingiz qabul qilindi (<b>{task_type}</b>)!{prompt_info}\n"
        f"⏳ Siz navbatda: <b>#{queue_pos}</b>-o'rindasiz.\n\n"
        f"<i>AI Examiner tahlil qilmoqda, natija tayyor bo'lishi bilan yuboramiz...</i>",
        parse_mode="HTML",
    )


# ----------------------------------------------------
# Guruhda Yangi Savol (Topic) Boshqarish Funksiyasi
# ----------------------------------------------------

async def process_new_group_topic(message: types.Message, prompt_text: str):
    chat = message.chat
    user = message.from_user
    user_id = user.id if user else 0

    existing_topic = await get_group_topic(chat.id)
    if existing_topic:
        if existing_topic.topic_text.strip().lower() == prompt_text.strip().lower():
            await message.reply(
                "ℹ️ <b>Ushbu savol allaqachon guruhda faol holatda turibdi!</b>\n\n"
                "Bot talabalardan insholarni kutmoqda. Talabalar ushbu xabarga <b>Reply (Javob berish)</b> qilib yoki <code>#essay</code> bilan o'z insholarini yuborishlari mumkin.",
                parse_mode="HTML",
            )
            return

        PENDING_TOPIC_REPLACEMENTS[chat.id] = {
            "topic_text": prompt_text,
            "message_id": message.message_id,
            "user_id": user_id,
        }
        warn_text = (
            "⚠️ <b>Guruhda allaqachon faol savol mavjud!</b>\n\n"
            f"📌 <b>Hozirgi faol savol:</b>\n"
            f"<i>«{existing_topic.topic_text}»</i>\n\n"
            f"🆕 <b>Yangi yuborilgan savol:</b>\n"
            f"<i>«{prompt_text}»</i>\n\n"
            "Mavzuni yangisiga almashtirishni xohlaysizmi?"
        )
        await message.reply(
            warn_text,
            parse_mode="HTML",
            reply_markup=get_topic_replace_keyboard(),
        )
        return

    # Yangi savol e'lon qilinadi
    ack_topic = (
        "📌 <b>Yangi IELTS Task 2 topshirig'i qabul qilindi!</b>\n\n"
        f"📝 <i>\"{prompt_text}\"</i>\n\n"
        "🟢 <b>Holat:</b> Insholar qabul qilinmoqda (Bot kutyapti...)\n\n"
        "👇 Talabalar ushbu xabarga <b>Reply (Javob berish)</b> qilib yoki guruhga <code>#essay</code> bilan o'z insholarini yuborishlari mumkin. "
        "Bot inshoni avtomatik tekshirib, IELTS mezonlari bo'yicha baholaydi."
    )
    ack_msg = await message.reply(ack_topic, parse_mode="HTML")
    await set_group_topic(
        chat_id=chat.id,
        topic_text=prompt_text,
        message_id=message.message_id,
        created_by=user_id,
        announcement_msg_id=ack_msg.message_id,
    )
    try:
        await message.bot.pin_chat_message(
            chat_id=chat.id,
            message_id=ack_msg.message_id,
            disable_notification=True,
        )
    except Exception:
        pass


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

    essay_match = HASHTAG_PATTERN.search(text)
    topic_match = TOPIC_HASHTAG_PATTERN.search(text)
    is_reply = bool(message.reply_to_message and message.reply_to_message.text)
    replied_text = message.reply_to_message.text.strip() if is_reply else ""

    # ----------------------------------------------------
    # GURUHDA 1-HOLAT: Ustoz savol tashlaganda (#task2, #topic, #savol)
    # ----------------------------------------------------
    if not is_private and topic_match and not is_reply:
        clean_prompt = TOPIC_HASHTAG_PATTERN.sub("", text).strip()
        words = count_words(clean_prompt)
        # Agar so'zlar soni 120 dan ko'p bo'lsa, o'quvchi xato qilib inshoga #task2 qo'ygan:
        if words > 120:
            await message.reply(
                "💡 <b>Insho topshirish uchun:</b>\n\n"
                "Iltimos, ustoz bergan savolga <b>Reply (Javob berish)</b> qiling yoki inshoingizga <code>#essay</code> hashtag qo'shing.\n\n"
                "<i>(<code>#task2</code> faqat yangi savol kiritish uchun mo'ljallangan).</i>",
                parse_mode="HTML",
            )
            return

        can_post = await is_teacher_or_admin(message.bot, chat.id, user)
        if not can_post:
            await message.reply(
                "🚫 <b>Ruxsat berilmadi!</b>\n\n"
                "Guruhda faqat <b>Ustoz</b> yoki <b>Admin</b> yangi mavzu (<code>#task2</code>) kiritishi mumkin.\n\n"
                "💡 Talabalar berilgan savolga <b>Reply</b> qilib yoki <code>#essay</code> bilan insho topshirishlari mumkin.",
                parse_mode="HTML",
            )
            return

        if words >= 5:
            await process_new_group_topic(message, clean_prompt)
            return

    # ----------------------------------------------------
    # GURUHDA 1.5-HOLAT: Ustoz /new buyrug'i javobiga Reply qilib savol yuborganda
    # ----------------------------------------------------
    if (
        not is_private
        and is_reply
        and "Yangi IELTS Task 2 savoli (sessiya)ni boshlash" in replied_text
        and not essay_match
    ):
        clean_prompt = TOPIC_HASHTAG_PATTERN.sub("", text).strip()
        words = count_words(clean_prompt)
        if 5 <= words < 120:
            can_post = await is_teacher_or_admin(message.bot, chat.id, user)
            if can_post:
                await process_new_group_topic(message, clean_prompt)
                return

    # ----------------------------------------------------
    # GURUHDA 2-HOLAT: Talaba savolga Reply qilib insho yuborganda
    # (Hashtag shart emas! Reply qilsa kifoya yoki #essay bilan)
    # ----------------------------------------------------
    task_type = "Task 2"
    task_prompt = None
    clean_text = None
    word_count = 0

    if not is_private and is_reply:
        raw_words = count_words(text)
        replied_has_topic = bool(TOPIC_HASHTAG_PATTERN.search(replied_text))
        is_bot_topic = (
            "topshirig'i" in replied_text.lower()
            or "📝" in replied_text
            or "faol" in replied_text.lower()
        )
        active_topic = await get_group_topic(chat.id)

        # Agar Reply qilingan bo'lsa va 40+ so'z bo'lsa (savolga reply, bot e'loniga reply yoki faol mavzu mavjud):
        if raw_words >= MIN_WORD_COUNT and (replied_has_topic or is_bot_topic or active_topic or essay_match):
            clean_text = HASHTAG_PATTERN.sub("", text)
            clean_text = TOPIC_HASHTAG_PATTERN.sub("", clean_text).strip()
            word_count = count_words(clean_text)

            if word_count > MAX_WORD_COUNT:
                await message.reply(
                    f"⚠️ Insho hajmi juda katta ({word_count} ta so'z). IELTS Task 2 inshosi {MAX_WORD_COUNT} ta so'zdan oshmasligi lozim.",
                    reply_to_message_id=message.message_id,
                )
                return

            task_type = "Task 2"

            # Savol matnini reply qilingan xabardan ajratib olish
            clean_prompt = TOPIC_HASHTAG_PATTERN.sub("", replied_text).strip()
            clean_prompt = HASHTAG_PATTERN.sub("", clean_prompt).strip()
            if '\"' in clean_prompt:
                parts = clean_prompt.split('\"')
                if len(parts) >= 2:
                    clean_prompt = parts[1]
            elif "«" in clean_prompt and "»" in clean_prompt:
                parts = clean_prompt.split("«")
                if len(parts) >= 2:
                    clean_prompt = parts[1].split("»")[0]

            if clean_prompt and 5 <= count_words(clean_prompt) < 120:
                task_prompt = clean_prompt
            elif active_topic:
                task_prompt = active_topic.topic_text
            logger.info(f"Group Reply detected as essay! Prompt: {str(task_prompt)[:40]}...")

    # Agar yuqoridagi Reply holati bo'lmasa, standart 3-tier filtrdan o'tkazamiz (bunda #essay bo'lishi shart)
    if clean_text is None:
        is_valid, reject_reason, clean_text, word_count, task_type, task_prompt = filter_essay_text(text)

        # Agar bu reply bo'lsa va task_prompt hali yo'q bo'lsa, reply_to_message dan olamiz
        if is_valid and not task_prompt and is_reply:
            if not replied_text.startswith("📥") and not replied_text.startswith("📊"):
                task_prompt = HASHTAG_PATTERN.sub("", replied_text).strip()

        # Guruhda insho bo'lsa va hali task_prompt bo'lmasa, guruhning faol mavzusini biriktiramiz!
        if is_valid and not is_private and not task_prompt:
            active_topic = await get_group_topic(chat.id)
            if active_topic:
                task_prompt = active_topic.topic_text
                logger.info(f"Attached group active topic to standalone essay: {task_prompt[:40]}...")

        # Guruhda insho bo'lmagan oddiy suhbatlarga jim turamiz, lekin insho juda katta bo'lsa ogohlantiramiz
        if not is_private and not is_valid:
            if essay_match and "juda katta" in (reject_reason or ""):
                await message.reply(f"⚠️ {reject_reason}", reply_to_message_id=message.message_id)
            return

        # Shaxsiy chatda hashtag bo'lmasa FSM menyusini chiqaramiz
        if is_private and not is_valid:
            if reject_reason != "Bot komandasi":
                await message.reply(
                    f"Assalomu alaykum! Insho tekshirish uchun pastdagi <b>«✍️ Yangi insho tekshirish»</b> tugmasini bosing yoki xabaringizga <code>#essay</code> (yoki <code>#essey</code>) hashtag qo'shing.",
                    parse_mode="HTML",
                    reply_markup=get_start_keyboard(),
                )
            return

    # Agar reply orqali olingan inshoda ham task_prompt topilmagan bo'lsa, guruhning faol mavzusidan olamiz
    if not is_private and not task_prompt:
        active_topic = await get_group_topic(chat.id)
        if active_topic:
            task_prompt = active_topic.topic_text

    user_id = user.id if user else 0

    # Anti-Spam / In-Flight lock check:
    if await queue_service.is_user_inflight(user_id):
        user_mention = (
            f"@{user.username}"
            if (user and user.username)
            else (html.escape(user.full_name) if user else "Foydalanuvchi")
        )
        await message.reply(
            f"⏳ <b>{user_mention}, inshoingiz hozir tekshirilmoqda!</b>\n\n"
            "Iltimos, avvalgi insho tahlili yakunlanishini kuting va shundan so'ng yangisini yuboring.",
            reply_to_message_id=message.message_id,
            parse_mode="HTML",
        )
        return

    # Limit tekshiruvi (Admin 7326292681 uchun cheksiz)
    is_allowed, limit_msg = await check_and_increment_limits(
        user_id=user_id, chat_id=chat.id, is_private=is_private
    )
    if not is_allowed:
        await message.reply(f"🚫 {limit_msg}")
        return

    user_mention = (
        f"@{user.username}"
        if (user and user.username)
        else (html.escape(user.full_name) if user else "Foydalanuvchi")
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

    await queue_service.set_user_inflight(user_id, ttl=45)
    queue_pos = await queue_service.enqueue(payload)

    if task_prompt:
        prompt_snippet = task_prompt[:45] + "..." if len(task_prompt) > 45 else task_prompt
        prompt_line = f"\n📌 <i>Mavzu: \"{html.escape(prompt_snippet)}\"</i>"
    else:
        prompt_line = "\n💡 <i>Maslahat: Savolga Reply qilib yuborsangiz, Task Response 100% aniq baholanadi.</i>"

    ack_text = (
        f"📥 {user_mention}, inshoingiz qabul qilindi (<b>{task_type}</b>)!{prompt_line}\n"
        f"⏳ Siz navbatda: <b>#{queue_pos}</b>-o'rindasiz.\n\n"
        f"<i>AI Examiner tahlil qilmoqda, natija tayyor bo'lishi bilan xabar beramiz...</i>"
    )
    await message.reply(ack_text, parse_mode="HTML")
