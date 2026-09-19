import logging
from typing import Optional
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
)

from config import settings
from db.database import (
    get_user_credits,
    add_user_credits,
    get_user_daily_usage,
    upsert_user,
)

logger = logging.getLogger(__name__)

payments_router = Router()

# Telegram Stars Packages Definition
STARS_PACKAGES = {
    "pkg_3": {
        "id": "pkg_3",
        "title": "⚡️ 3 ta insho paketi",
        "essays": 3,
        "stars": 15,
        "desc": "3 ta IELTS Task 2 insho tekshiruvi (muddatsiz saqlanadi)",
    },
    "pkg_10": {
        "id": "pkg_10",
        "title": "⭐ 10 ta insho paketi",
        "essays": 10,
        "stars": 35,
        "desc": "10 ta IELTS Task 2 insho tekshiruvi (eng ommabop, muddatsiz)",
    },
    "pkg_30": {
        "id": "pkg_30",
        "title": "🚀 30 ta insho paketi",
        "essays": 30,
        "stars": 75,
        "desc": "30 ta IELTS Task 2 insho tekshiruvi (maksimal tejamkor, muddatsiz)",
    },
}


def get_payment_packages_keyboard() -> InlineKeyboardMarkup:
    """Generates inline buttons for available Telegram Stars packages."""
    buttons = [
        [
            InlineKeyboardButton(
                text="⚡️ 3 ta insho — 15 ⭐️ Stars",
                callback_data="buy:pkg:pkg_3",
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ 10 ta insho — 35 ⭐️ Stars (Tavsiya!)",
                callback_data="buy:pkg:pkg_10",
            )
        ],
        [
            InlineKeyboardButton(
                text="🚀 30 ta insho — 75 ⭐️ Stars (-50% chegirma)",
                callback_data="buy:pkg:pkg_30",
            )
        ],
        [
            InlineKeyboardButton(
                text="🎁 Do'st taklif qilish (+1 bepul insho)",
                callback_data="ref:menu",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_balance_message(daily_used: int, daily_limit: int, extra_credits: int) -> str:
    """Formats student balance text."""
    daily_remaining = max(0, daily_limit - daily_used)
    return (
        "💎 <b>SIZNING INSHO TEKSHIRISH BALANSINGIZ:</b>\n\n"
        f"• 📅 <b>Bugungi bepul limit:</b> {daily_remaining} / {daily_limit} ta qoldi\n"
        f"• ⭐️ <b>Sotib olingan qo'shimcha insholar:</b> <b>{extra_credits} ta</b>\n\n"
        "ℹ️ <i>Kunlik bepul limit (5 ta) tugaganida, insholar avtomatik ravishda sotib olingan qo'shimcha insholar hisobidan tekshiriladi. "
        "Sotib olingan insholar muddatsiz saqlanadi va kuymaydi.</i>\n\n"
        "👇 <b>Quyidagi paketlardan birini tanlab, Telegram Stars orqali darhol xarid qilishingiz mumkin:</b>"
    )


@payments_router.message(Command("buy"))
@payments_router.message(Command("balance"))
async def handle_buy_or_balance_command(message: types.Message):
    """Handles /buy and /balance commands in private chat."""
    user = message.from_user
    if not user:
        return

    await upsert_user(user.id, user.username, user.full_name)
    daily_used = await get_user_daily_usage(user.id)
    extra_credits = await get_user_credits(user.id)

    text = format_balance_message(
        daily_used=daily_used,
        daily_limit=settings.DAILY_USER_LIMIT,
        extra_credits=extra_credits,
    )
    kb = get_payment_packages_keyboard()
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@payments_router.callback_query(F.data == "buy:menu")
async def cb_buy_menu(query: types.CallbackQuery):
    """Opens the purchase menu via callback button."""
    user = query.from_user
    daily_used = await get_user_daily_usage(user.id)
    extra_credits = await get_user_credits(user.id)

    text = format_balance_message(
        daily_used=daily_used,
        daily_limit=settings.DAILY_USER_LIMIT,
        extra_credits=extra_credits,
    )
    kb = get_payment_packages_keyboard()

    if query.message:
        try:
            await query.message.answer(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await query.message.reply(text, parse_mode="HTML", reply_markup=kb)
    await query.answer()


@payments_router.callback_query(F.data.startswith("buy:pkg:"))
async def cb_send_stars_invoice(query: types.CallbackQuery):
    """Sends official Telegram Stars invoice for the selected package."""
    pkg_id = query.data.replace("buy:pkg:", "")
    pkg = STARS_PACKAGES.get(pkg_id)

    if not pkg:
        await query.answer("Kechirasiz, tanlangan paket topilmadi.", show_alert=True)
        return

    user_id = query.from_user.id
    payload = f"stars:{pkg_id}:{user_id}"

    try:
        # Currency code 'XTR' is Telegram's official standard for Telegram Stars
        prices = [LabeledPrice(label=pkg["title"], amount=pkg["stars"])]

        await query.bot.send_invoice(
            chat_id=user_id,
            title=pkg["title"],
            description=pkg["desc"],
            payload=payload,
            currency="XTR",
            prices=prices,
            provider_token="",  # Digital goods paid via Stars do not require external payment provider token
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Error sending Stars invoice to user {user_id}: {e}", exc_info=True)
        await query.answer("To'lov oynasini ochishda xatolik yuz berdi. Iltimos qayta urinib ko'ring.", show_alert=True)


@payments_router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Approves the transaction within Telegram's required 10-second window."""
    await pre_checkout_query.answer(ok=True)


@payments_router.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    """Fulfills the purchase once Telegram confirms successful payment with Stars."""
    payment = message.successful_payment
    user = message.from_user
    if not user:
        return

    payload = payment.invoice_payload or ""
    parts = payload.split(":")
    pkg_id = parts[1] if len(parts) > 1 else ""

    pkg = STARS_PACKAGES.get(pkg_id)
    essays_count = pkg["essays"] if pkg else 10

    new_total = await add_user_credits(user.id, essays_count)
    logger.info(
        f"Payment SUCCESS: user {user.id} paid {payment.total_amount} Stars for {essays_count} essays. New balance: {new_total}"
    )

    success_text = (
        "🎉 <b>To'lovingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        f"⭐️ <b>To'langan miqdor:</b> {payment.total_amount} Stars\n"
        f"📥 <b>Qo'shilgan insholar:</b> +{essays_count} ta\n"
        f"💎 <b>Jami qo'shimcha balansingiz:</b> <b>{new_total} ta insho</b>\n\n"
        "✅ <i>Ushbu insholar muddatsiz saqlanadi. Endi bemalol o'z insholaringizni yuborishingiz mumkin, bot ularni navbatsiz tekshirib beradi!</i>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Insho tekshirishni boshlash",
                    callback_data="fsm:start_check",
                )
            ]
        ]
    )

    await message.answer(success_text, parse_mode="HTML", reply_markup=kb)
