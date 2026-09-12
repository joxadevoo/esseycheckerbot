import asyncio
import logging
import sys

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
)

from aiohttp import web
from config import settings
from db.database import init_db
from handlers.messages import router
from services.worker import start_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("esseycheckerbot")


async def handle_health(request):
    """Healthcheck endpoint for UptimeRobot and Render/Koyeb monitoring."""
    return web.json_response({
        "status": "ok",
        "service": "IELTS Essay Checker Bot",
        "database": "connected",
        "queue": "active",
    })


async def start_health_server(port: int = 8080):
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck HTTP server listening on http://0.0.0.0:{port}/health")
    return runner


async def setup_bot_commands(bot: Bot):
    """Configures Telegram command menus for Groups and Private chats."""
    try:
        # 1. Guruhdagi barcha a'zolar uchun buyruqlar:
        group_commands = [
            BotCommand(command="new", description="✍️ Yangi savol / sessiya boshlash"),
            BotCommand(command="topic", description="📌 Guruhdagi faol savolni ko'rish"),
            BotCommand(command="help", description="ℹ️ Guruhda foydalanish qoidalari"),
        ]
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())

        # 2. Guruh adminlari va ustozlar uchun buyruqlar:
        admin_group_commands = [
            BotCommand(command="new", description="✍️ Yangi savol / sessiya boshlash"),
            BotCommand(command="topic", description="📌 Guruhdagi faol savolni ko'rish"),
            BotCommand(command="report", description="📊 Guruh hisoboti va natijalar"),
            BotCommand(command="stop", description="🛑 Faol savol qabulini to'xtatish"),
            BotCommand(command="ustoz", description="👨‍🏫 Ustoz tayinlash (/ustoz @mentor)"),
            BotCommand(command="admin", description="🛡 Yangi admin biriktirish (/admin @username)"),
            BotCommand(command="ustozlar", description="👥 Guruh ustozlari va adminlari ro'yxati"),
            BotCommand(command="help", description="ℹ️ Qo'llanma va boshqaruv"),
        ]
        await bot.set_my_commands(admin_group_commands, scope=BotCommandScopeAllChatAdministrators())

        # 3. Shaxsiy chat uchun buyruqlar menyusi:
        private_commands = [
            BotCommand(command="start", description="🚀 Botni ishga tushirish"),
            BotCommand(command="new", description="✍️ Yangi sessiya (savol va insho tekshirish)"),
            BotCommand(command="help", description="ℹ️ Yordam va IELTS mezonlari"),
        ]
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("Telegram buyruqlar menyusi ('/' menyusi) muvaffaqiyatli sozlandi.")
    except Exception as e:
        logger.warning(f"Buyruqlar menyusini sozlashda xatolik: {e}")


async def main():
    # 1. Start Healthcheck HTTP Server IMMEDIATELY so Render/Cloud port scan detects it
    health_runner = None
    try:
        health_runner = await start_health_server(port=settings.PORT)
    except Exception as e:
        logger.warning(f"Could not start HTTP health server on port {settings.PORT}: {e}")

    env_name = settings.model_config.get("env_file", ".env")
    mode_name = "TEST / DEV" if "--test" in sys.argv else "PRODUCTION"
    logger.info(f"🚀 Bot ishga tushirilmoqda... Rejim: [{mode_name}] (Fayl: {env_name})")

    if not settings.BOT_TOKEN or settings.BOT_TOKEN == "placeholder_bot_token":
        logger.warning(
            f"DIQQAT: {env_name} faylida BOT_TOKEN ko'rsatilmadi! Iltimos, {env_name} faylini to'ldiring."
        )

    # 2. Initialize Database tables
    await init_db()

    # 3. Setup Bot & Dispatcher
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Get bot user info
    bot_user = None
    bot_username = "esseychecker_bot"
    try:
        bot_user = await bot.get_me()
        bot_username = bot_user.username or "esseychecker_bot"
        logger.info(f"Bot muvaffaqiyatli ishga tushdi: @{bot_username} (ID: {bot_user.id})")
        
        # Setup Telegram commands menu ('/' belgisi bosilganda chiqadigan buyruqlar)
        await setup_bot_commands(bot)
    except Exception as e:
        logger.warning(
            f"Telegram API ulanishida ogohlantirish (Token hali kiritilmagan bo'lishi mumkin): {e}"
        )

    # 4. Start background AI Workers (default 3 concurrent workers)
    NUM_WORKERS = 3
    worker_tasks = []
    for i in range(1, NUM_WORKERS + 1):
        task = asyncio.create_task(start_worker(bot, bot_username, worker_id=i))
        worker_tasks.append(task)
    logger.info(f"{NUM_WORKERS} ta mustaqil AI Worker orqa fonda ishga tushirildi.")

    # 5. Start Bot Polling or Webhook
    try:
        if settings.WEBHOOK_URL:
            logger.info(f"Webhook rejimida ishga tushirilmoqda: {settings.WEBHOOK_URL}")
            await bot.set_webhook(url=settings.WEBHOOK_URL)
        else:
            logger.info("Long-polling rejimida ishga tushirilmoqda...")
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
    finally:
        for t in worker_tasks:
            t.cancel()
        if health_runner:
            await health_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
