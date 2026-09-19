import logging
import urllib.parse
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.database import get_user_referral_stats, upsert_user

logger = logging.getLogger(__name__)

referral_router = Router()


@referral_router.message(Command("referral"))
@referral_router.message(Command("taklif"))
async def handle_referral_command(message: types.Message):
    """Generates user's personal referral link and share buttons."""
    user = message.from_user
    if not user:
        return

    await upsert_user(user.id, user.username, user.full_name)
    stats = await get_user_referral_stats(user.id)

    bot_user = await message.bot.get_me()
    bot_username = bot_user.username or "esseycheckerbot"

    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

    # Pre-filled share message for Telegram
    share_text = (
        "Assalomu alaykum! Ushbu bot IELTS Task 2 insholarini rasmiy British Council "
        "mezonlarida bepul tekshirib, batafsil tahlil va ball beradi. "
        "Havola orqali kirsangiz, sizga ham bonus insho tekshiruvi beriladi:"
    )
    encoded_text = urllib.parse.quote(share_text)
    encoded_link = urllib.parse.quote(ref_link)
    share_url = f"https://t.me/share/url?url={encoded_link}&text={encoded_text}"

    text = (
        "🎁 <b>DO'STLARNI TAKLIF QILISH VA BONUS INSHOLAR</b>\n\n"
        "Do'stlaringiz, kursdoshlaringiz yoki IELTS guruhlariga botni tavsiya qiling va har bir taklif uchun <b>bepul bonus insho</b> tekshiruvlariga ega bo'ling!\n\n"
        "✨ <b>Qoidalar:</b>\n"
        "• Siz taklif qilgan har bir yangi do'st uchun sizga: <b>+1 ta insho</b>\n"
        "• Taklif orqali kirgan do'stingizga ham: <b>+1 ta insho</b>\n\n"
        "📊 <b>Sizning natijalaringiz:</b>\n"
        f"• 👥 Taklif qilingan do'stlar: <b>{stats['referral_count']} ta</b>\n"
        f"• 💎 Ishlangan bonus insholar: <b>{stats['bonus_credits_earned']} ta</b>\n\n"
        f"🔗 <b>Sizning shaxsiy taklif havolangiz:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "👇 <b>Quyidagi tugma orqali havolani do'stlaringizga darhol ulashishingiz mumkin:</b>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📲 Do'stlarga ulashish (Share)",
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Mening balansim",
                    callback_data="buy:menu",
                ),
                InlineKeyboardButton(
                    text="✍️ Insho tekshirish",
                    callback_data="fsm:start_check",
                ),
            ],
        ]
    )

    await message.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


@referral_router.callback_query(F.data == "ref:menu")
async def cb_referral_menu(query: types.CallbackQuery):
    """Handles referral menu callback button from start menu."""
    user = query.from_user
    await upsert_user(user.id, user.username, user.full_name)
    stats = await get_user_referral_stats(user.id)

    bot_user = await query.bot.get_me()
    bot_username = bot_user.username or "esseycheckerbot"

    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

    share_text = (
        "Assalomu alaykum! Ushbu bot IELTS Task 2 insholarini rasmiy British Council "
        "mezonlarida bepul tekshirib, batafsil tahlil va ball beradi. "
        "Havola orqali kirsangiz, sizga ham bonus insho tekshiruvi beriladi:"
    )
    encoded_text = urllib.parse.quote(share_text)
    encoded_link = urllib.parse.quote(ref_link)
    share_url = f"https://t.me/share/url?url={encoded_link}&text={encoded_text}"

    text = (
        "🎁 <b>DO'STLARNI TAKLIF QILISH VA BONUS INSHOLAR</b>\n\n"
        "Do'stlaringiz, kursdoshlaringiz yoki IELTS guruhlariga botni tavsiya qiling va har bir taklif uchun <b>bepul bonus insho</b> tekshiruvlariga ega bo'ling!\n\n"
        "✨ <b>Qoidalar:</b>\n"
        "• Siz taklif qilgan har bir yangi do'st uchun sizga: <b>+1 ta insho</b>\n"
        "• Taklif orqali kirgan do'stingizga ham: <b>+1 ta insho</b>\n\n"
        "📊 <b>Sizning natijalaringiz:</b>\n"
        f"• 👥 Taklif qilingan do'stlar: <b>{stats['referral_count']} ta</b>\n"
        f"• 💎 Ishlangan bonus insholar: <b>{stats['bonus_credits_earned']} ta</b>\n\n"
        f"🔗 <b>Sizning shaxsiy taklif havolangiz:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "👇 <b>Quyidagi tugma orqali havolani do'stlaringizga darhol ulashishingiz mumkin:</b>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📲 Do'stlarga ulashish (Share)",
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Mening balansim",
                    callback_data="buy:menu",
                ),
                InlineKeyboardButton(
                    text="✍️ Insho tekshirish",
                    callback_data="fsm:start_check",
                ),
            ],
        ]
    )

    if query.message:
        try:
            await query.message.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            await query.message.reply(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    await query.answer()
