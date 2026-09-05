import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

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


async def main():
    # 1. Start Healthcheck HTTP Server IMMEDIATELY so Render/Cloud port scan detects it
    health_runner = None
    try:
        health_runner = await start_health_server(port=settings.PORT)
    except Exception as e:
        logger.warning(f"Could not start HTTP health server on port {settings.PORT}: {e}")

    if not settings.BOT_TOKEN or settings.BOT_TOKEN == "placeholder_bot_token":
        logger.warning(
            "DIQQAT: .env faylida BOT_TOKEN ko'rsatilmadi! Iltimos, .env faylini to'ldiring."
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
