import html
import logging
from datetime import datetime
from typing import Optional
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import settings
from db.database import (
    save_feedback,
    update_feedback_admin_msg,
    get_feedback_by_admin_msg,
    mark_feedback_answered,
    upsert_user,
)

logger = logging.getLogger(__name__)

feedback_router = Router()


class FeedbackFSM(StatesGroup):
    waiting_for_content = State()


def get_feedback_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="feedback:cancel",
                )
            ]
        ]
    )


def get_admin_ids() -> list[int]:
    """Returns the dedicated real developer/admin ID for feedback messages."""
    if hasattr(settings, "DEVELOPER_CHAT_ID") and settings.DEVELOPER_CHAT_ID:
        return [settings.DEVELOPER_CHAT_ID]
    return [7326292681]


@feedback_router.message(Command("feedback"))
@feedback_router.message(Command("aloqa"))
@feedback_router.message(Command("taklif"))
@feedback_router.message(Command("support"))
async def handle_feedback_command(message: types.Message, state: FSMContext):
    """Initiates feedback / support submission flow."""
    if message.chat.type != ChatType.PRIVATE:
        await message.reply(
            "ℹ️ Dasturchiga taklif yoki savol yo'llash uchun botning shaxsiy chatida /feedback yuboring."
        )
        return

    user = message.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)

    await state.set_state(FeedbackFSM.waiting_for_content)
    text = (
        "✍️ <b>Taklif, savol yoki hamkorlik bo'yicha murojaat</b>\n\n"
        "Fikringiz, botda uchragan xatoliklar (bug), yangi g'oyalar yoki hamkorlik takliflaringizni "
        "batafsil yozib yuboring.\n\n"
        "<i>Matn, rasm (skrinshot) yoki audio xabar yuborishingiz mumkin.</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_feedback_cancel_keyboard())


@feedback_router.callback_query(F.data == "feedback:start")
async def handle_feedback_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user = callback.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)

    await state.set_state(FeedbackFSM.waiting_for_content)
    text = (
        "✍️ <b>Taklif, savol yoki hamkorlik bo'yicha murojaat</b>\n\n"
        "Fikringiz, botda uchragan xatoliklar (bug), yangi g'oyalar yoki hamkorlik takliflaringizni "
        "batafsil yozib yuboring.\n\n"
        "<i>Matn, rasm (skrinshot) yoki audio xabar yuborishingiz mumkin.</i>"
    )
    await callback.message.answer(
        text, parse_mode="HTML", reply_markup=get_feedback_cancel_keyboard()
    )


@feedback_router.callback_query(F.data == "feedback:cancel")
async def handle_feedback_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Bekor qilindi")
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Murojaat yuborish bekor qilindi.</b>\n\n"
        "Istalgan vaqtda /start orqali asosiy menyuga qaytishingiz mumkin.",
        parse_mode="HTML",
    )


@feedback_router.message(FeedbackFSM.waiting_for_content, Command("cancel"))
@feedback_router.message(FeedbackFSM.waiting_for_content, Command("bekor"))
async def handle_feedback_text_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ <b>Murojaat bekor qilindi.</b>", parse_mode="HTML")


@feedback_router.message(FeedbackFSM.waiting_for_content)
async def process_feedback_content(message: types.Message, state: FSMContext):
    """Processes user feedback message and notifies admins."""
    user = message.from_user
    if not user:
        return

    admin_ids = get_admin_ids()
    user_name = html.escape(user.full_name or "Noma'lum foydalanuvchi")
    username_str = f"@{user.username}" if user.username else "Username yo'q"
    user_link = f"<a href=\"tg://user?id={user.id}\">{user_name}</a>"

    # Determine media type and message text
    media_type = "text"
    content_text = message.text or message.caption or ""

    if message.photo:
        media_type = "photo"
    elif message.voice:
        media_type = "voice"
    elif message.video:
        media_type = "video"
    elif message.document:
        media_type = "document"

    # Save to database
    fb = await save_feedback(
        user_id=user.id,
        user_message_id=message.message_id,
        text=content_text,
        media_type=media_type,
    )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    admin_header = (
        f"📩 <b>Yangi murojaat (Taklif / Savol / Hamkorlik)!</b>\n\n"
        f"👤 <b>Yuboruvchi:</b> {user_link} ({username_str})\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"⏰ <b>Vaqti:</b> {now_str}\n"
        f"🎫 <b>Murojaat raqami:</b> #{fb.id}\n"
    )

    if content_text:
        admin_header += f"\n📝 <b>Matn:</b>\n{html.escape(content_text)}\n"

    admin_header += (
        "\n💬 <i>Ushbu xabarga <b>Reply (Javob berish)</b> qilsangiz, bot javobingizni "
        "to'g'ridan-to'g'ri foydalanuvchiga yetkazadi.</i>"
    )

    # Deliver to all admins
    delivered_count = 0
    for aid in admin_ids:
        try:
            admin_msg = None
            if message.photo:
                admin_msg = await message.bot.send_photo(
                    chat_id=aid,
                    photo=message.photo[-1].file_id,
                    caption=admin_header,
                    parse_mode="HTML",
                )
            elif message.voice:
                admin_msg = await message.bot.send_voice(
                    chat_id=aid,
                    voice=message.voice.file_id,
                    caption=admin_header,
                    parse_mode="HTML",
                )
            elif message.document:
                admin_msg = await message.bot.send_document(
                    chat_id=aid,
                    document=message.document.file_id,
                    caption=admin_header,
                    parse_mode="HTML",
                )
            else:
                admin_msg = await message.bot.send_message(
                    chat_id=aid,
                    text=admin_header,
                    parse_mode="HTML",
                )

            if admin_msg:
                delivered_count += 1
                await update_feedback_admin_msg(fb.id, admin_id=aid, admin_message_id=admin_msg.message_id)
        except Exception as e:
            logger.warning(f"Could not forward feedback to admin {aid}: {e}")

    await state.clear()
    await message.answer(
        "✅ <b>Murojaatingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        "Xabaringiz dasturchi va ma'muriyatga yetkazildi. Tez orada ko'rib chiqib sizga javob yuboramiz.\n"
        "Rahmat!",
        parse_mode="HTML",
    )


@feedback_router.message(F.reply_to_message, F.chat.type == ChatType.PRIVATE)
async def handle_admin_reply_to_feedback(message: types.Message):
    """
    Catches when an admin replies to a forwarded feedback message
    and relays the answer back to the original user.
    """
    user_id = message.from_user.id if message.from_user else 0
    if user_id != settings.DEVELOPER_CHAT_ID and not settings.is_admin(user_id):
        # Not authorized admin / developer, ignore
        return

    replied_msg = message.reply_to_message
    if not replied_msg:
        return

    fb = await get_feedback_by_admin_msg(admin_id=user_id, admin_message_id=replied_msg.message_id)
    if not fb:
        # Not a reply to a tracked feedback notification
        return

    reply_text = message.text or message.caption or ""
    client_msg = (
        "📩 <b>Dasturchi / Ma'muriyatdan javob:</b>\n\n"
        f"{html.escape(reply_text) if reply_text else ''}\n\n"
        "<i>💡 Savol yoki taklifingiz bo'lsa, istalgan vaqtda /feedback orqali yana murojaat qilishingiz mumkin.</i>"
    )

    try:
        if message.photo:
            await message.bot.send_photo(
                chat_id=fb.user_id,
                photo=message.photo[-1].file_id,
                caption=client_msg,
                parse_mode="HTML",
            )
        elif message.voice:
            await message.bot.send_voice(
                chat_id=fb.user_id,
                voice=message.voice.file_id,
                caption=client_msg,
                parse_mode="HTML",
            )
        elif message.document:
            await message.bot.send_document(
                chat_id=fb.user_id,
                document=message.document.file_id,
                caption=client_msg,
                parse_mode="HTML",
            )
        else:
            await message.bot.send_message(
                chat_id=fb.user_id,
                text=client_msg,
                parse_mode="HTML",
            )

        # Mark as answered in DB
        await mark_feedback_answered(fb.id, reply_text=reply_text or "[Media javob]")

        await message.reply(
            f"✅ <b>Javobingiz foydalanuvchiga (ID: <code>{fb.user_id}</code>) muvaffaqiyatli yetkazildi!</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to deliver admin reply to user {fb.user_id}: {e}")
        await message.reply(
            f"⚠️ <b>Xatolik:</b> Foydalanuvchiga xabar yetkazib bo'lmadi (ehtimol botni bloklagan yoki o'chirgan).\n"
            f"Tafsilot: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
