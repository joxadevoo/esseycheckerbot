import html
import logging
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from config import settings
from db.database import get_system_admin_stats, export_users_and_essays_excel

logger = logging.getLogger(__name__)
admin_router = Router()


def get_admin_stats_keyboard(current_tab: str = "overview") -> InlineKeyboardMarkup:
    """Builds interactive inline keyboard for navigating admin statistics."""
    buttons = []

    # Row 1: Main navigation
    if current_tab == "overview":
        row1 = [
            InlineKeyboardButton(text="🏆 Top Userlar", callback_data="admin_stats:users"),
            InlineKeyboardButton(text="👥 Guruhlar", callback_data="admin_stats:groups"),
        ]
        row2 = [
            InlineKeyboardButton(text="📊 Ballar Taqsimoti", callback_data="admin_stats:bands"),
            InlineKeyboardButton(text="📥 Excel Eksport", callback_data="admin_stats:export_excel"),
        ]
        row3 = [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_stats:refresh"),
        ]
        buttons.extend([row1, row2, row3])
    else:
        buttons.append([
            InlineKeyboardButton(text="🔙 Bosh Sahifa", callback_data="admin_stats:overview"),
            InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"admin_stats:{current_tab}"),
        ])
        if current_tab != "export_excel":
            buttons.append([
                InlineKeyboardButton(text="📥 Excel Yuklab Olish", callback_data="admin_stats:export_excel")
            ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_overview_text(data: dict) -> str:
    """Formats the main dashboard overview text."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    return (
        f"📊 <b>IELTS BOT — BOSH ADMIN STATISTIKASI</b>\n"
        f"<i>Yangilangan vaqt: {now_str}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>Foydalanuvchilar oqimi:</b>\n"
        f"• Jami ro'yxatdan o'tganlar: <b>{data['total_users']:,} ta</b>\n"
        f"• Insho topshirgan faol talabalar: <b>{data['unique_writers']:,} ta</b>\n"
        f"• Bugungi faol foydalanuvchilar (DAU): <b>{data['active_today_users']:,} ta</b>\n"
        f"• Tarqatilgan bonus kreditlar: <b>{data['total_credits']:,} ta</b>\n\n"
        f"👥 <b>Guruhlar monitoringi:</b>\n"
        f"• Guruhlar soni: <b>{data['total_groups']:,} ta</b>\n"
        f"• Shundan Premium guruhlar: <b>{data['premium_groups']:,} ta</b>\n\n"
        f"📝 <b>Insholar tahlili:</b>\n"
        f"• Jami tekshirilgan: <b>{data['total_essays']:,} ta</b>\n"
        f"• ⚡️ Bugun tekshirilgan: <b>{data['today_essays']:,} ta</b>\n"
        f"• 📅 So'nggi 7 kunda: <b>{data['week_essays']:,} ta</b>\n"
        f"• 🗓 So'nggi 30 kunda: <b>{data['month_essays']:,} ta</b>\n"
        f"• 🎯 O'rtacha IELTS Band: <b>{data['avg_band']:.2f}</b>\n\n"
        f"💰 <b>Monetizatsiya va Viral o'sish:</b>\n"
        f"• 🎁 Do'st taklifi (Referal): <b>{data['total_referrals']:,} ta</b>\n"
        f"• ⭐️ Telegram Stars xaridlari: <b>{data['total_payments']:,} ta</b>\n"
        f"• 💎 Jami olingan daromad: <b>{data['total_stars']:,} Stars</b> ({data['total_paid_essays']} ta insho)\n"
        f"• 💬 Taklif/mulohazalar: <b>{data['total_feedback']} ta</b> (Kutilmoqda: {data['pending_feedback']} ta)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 <i>Tafsilotlar, top reytinglar yoki Excel hisobotini ko'rish uchun quyidagi tugmalardan foydalaning:</i>"
    )


def format_top_users_text(data: dict) -> str:
    """Formats top 10 students text."""
    lines = [
        "🏆 <b>ENG FAOL TALABALAR VA O'QUVCHILAR (TOP 10)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    top_users = data.get("top_users", [])
    if not top_users:
        lines.append("<i>Hozircha faol foydalanuvchilar topilmadi.</i>")
    else:
        for idx, u in enumerate(top_users, 1):
            name = html.escape(u["full_name"])
            user_link = f"@{u['username']}" if u["username"] else f'<a href="tg://user?id={u["id"]}">{name}</a>'
            avg_str = f"{u['avg_band']:.1f}" if u["avg_band"] else "-"
            best_str = f"{u['best_band']:.1f}" if u["best_band"] else "-"
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            lines.append(
                f"{medal} <b>{user_link}</b> (ID: <code>{u['id']}</code>)\n"
                f"   └ ✍️ Insholar: <b>{u['essay_count']} ta</b> | 🎯 O'rtacha: <b>{avg_str}</b> (Eng zo'ri: {best_str}) | 💎 Kredit: {u['extra_credits']}"
            )
    return "\n".join(lines)


def format_top_groups_text(data: dict) -> str:
    """Formats top groups text."""
    lines = [
        "👥 <b>ENG FAOL IELTS GURUHLARI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    top_groups = data.get("top_groups", [])
    if not top_groups:
        lines.append("<i>Guruhlar ma'lumotlari mavjud emas.</i>")
    else:
        for idx, g in enumerate(top_groups, 1):
            title = html.escape(g["title"])
            lines.append(
                f"{idx}. <b>{title}</b>\n"
                f"   └ ID: <code>{g['id']}</code> | ✍️ Topshirilgan insholar: <b>{g['essay_count']} ta</b>"
            )
    return "\n".join(lines)


def format_bands_distribution_text(data: dict) -> str:
    """Formats visual band score distribution."""
    total = data.get("total_essays", 0)
    bands = data.get("bands_distribution", {})
    lines = [
        "🎯 <b>IELTS BAND BALLARI TAQSIMOTI</b>\n"
        f"<i>Jami tekshirilgan insholar: {total:,} ta | O'rtacha: {data.get('avg_band', 0.0):.2f}</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    
    if not bands or total == 0:
        lines.append("<i>Hali ballar to'plamagan.</i>")
    else:
        for b, count in sorted(bands.items(), reverse=True):
            pct = (count / total) * 100
            bar_len = min(15, max(1, int(pct / 6.6)))
            bar = "▇" * bar_len
            lines.append(f"<b>Band {b}:</b> {bar} <b>{count} ta</b> ({pct:.1f}%)")
            
    lines.append("\n━━━━━━━━━━━━━━━━━━━━\n<i>Eng ko'p uchraydigan ball darajasi talabalarning asosiy qiyinchilik nuqtasini ko'rsatadi.</i>")
    return "\n".join(lines)


@admin_router.message(Command("stats", "statistika", "admin"))
async def cmd_admin_stats(message: types.Message):
    """Entrypoint for admin stats dashboard."""
    user_id = message.from_user.id if message.from_user else 0
    if not settings.is_admin(user_id):
        return  # Silently ignore non-admins to prevent unauthorized probe

    stats = await get_system_admin_stats()
    text = format_overview_text(stats)
    kb = get_admin_stats_keyboard("overview")
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_stats:"))
async def cb_admin_stats(callback: types.CallbackQuery):
    """Handles tab switches and actions for admin stats."""
    user_id = callback.from_user.id
    if not settings.is_admin(user_id):
        await callback.answer("Ruxsat berilmagan!", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    if action == "export_excel":
        await callback.answer("⏳ Excel hisobot tayyorlanmoqda...", show_alert=False)
        try:
            excel_io = await export_users_and_essays_excel()
            filename = f"IELTS_Bot_Statistika_{datetime.now().strftime('%Y_%m_%d_%H%M')}.xlsx"
            input_file = BufferedInputFile(excel_io.getvalue(), filename=filename)
            await callback.message.answer_document(
                document=input_file,
                caption="📥 <b>IELTS Essay Checker Bot — To'liq Excel hisoboti</b>\n\nJadval ichida: barcha o'quvchilar, guruhlar va topshirilgan insholar tarixi jamlangan.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Excel export error: {e}", exc_info=True)
            await callback.message.answer(f"❌ Excel faylni yaratishda xatolik: {e}")
        return

    stats = await get_system_admin_stats()

    if action in ["overview", "refresh"]:
        text = format_overview_text(stats)
        kb = get_admin_stats_keyboard("overview")
    elif action == "users":
        text = format_top_users_text(stats)
        kb = get_admin_stats_keyboard("users")
    elif action == "groups":
        text = format_top_groups_text(stats)
        kb = get_admin_stats_keyboard("groups")
    elif action == "bands":
        text = format_bands_distribution_text(stats)
        kb = get_admin_stats_keyboard("bands")
    else:
        text = format_overview_text(stats)
        kb = get_admin_stats_keyboard("overview")

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer("Yangilandi!")
    except Exception:
        await callback.answer()
