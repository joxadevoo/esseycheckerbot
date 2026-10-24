import os
import sys
import json
import time
import logging
from collections import defaultdict
from aiohttp import web
from config import settings
from services.ai_service import ai_service
from services.filter_service import count_words

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("landing_server")

LANDING_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "landing"))

logger.info(f"Serving Landing Page from directory: {LANDING_DIR}")

# ==============================================================================
# IP-BASED RATE LIMITING (1 Free Trial per IP per 7 days / 168 hours)
# ==============================================================================
IP_LIMIT_HOURS = 168  # 7 days (1 hafta)
IP_MAX_EVALUATIONS = 1
IP_STORAGE_FILE = os.path.join(os.path.dirname(__file__), ".ip_evaluations.json")


def load_ip_evaluations():
    if os.path.exists(IP_STORAGE_FILE):
        try:
            with open(IP_STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return defaultdict(list, data)
        except Exception as e:
            logger.warning(f"Error reading IP evaluations: {e}")
    return defaultdict(list)


def save_ip_evaluations():
    try:
        with open(IP_STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(ip_evaluations), f)
    except Exception as e:
        logger.warning(f"Could not persist IP evaluations: {e}")


ip_evaluations = load_ip_evaluations()


def get_client_ip(request: web.Request) -> str:
    """Extract real client IP considering reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.remote or "unknown"


def check_ip_limit(client_ip: str):
    """
    Checks if client IP is within the free trial quota (1 per 7 days).
    Returns: (is_allowed: bool, remaining_trials: int, reset_in_seconds: int)
    """
    now = time.time()
    cutoff = now - (IP_LIMIT_HOURS * 3600)
    timestamps = [t for t in ip_evaluations[client_ip] if t > cutoff]
    ip_evaluations[client_ip] = timestamps

    if len(timestamps) >= IP_MAX_EVALUATIONS:
        oldest = timestamps[0]
        reset_in = int((oldest + IP_LIMIT_HOURS * 3600) - now)
        return False, 0, max(reset_in, 0)

    remaining = IP_MAX_EVALUATIONS - len(timestamps)
    return True, remaining, 0


def record_ip_evaluation(client_ip: str):
    """Records an evaluation usage timestamp for the client IP and persists it."""
    ip_evaluations[client_ip].append(time.time())
    save_ip_evaluations()


async def handle_status(request):
    """Returns AI model and backend status along with client IP trial quota."""
    client_ip = get_client_ip(request)
    is_allowed, remaining, reset_in = check_ip_limit(client_ip)

    return web.json_response(
        {
            "status": "online",
            "provider": ai_service.provider,
            "openai_model": ai_service.openai_model,
            "groq_model": ai_service.groq_model,
            "active_model": ai_service.openai_model
            if ai_service.provider == "openai"
            else ai_service.groq_model,
            "client_ip": client_ip,
            "remaining_trials": remaining,
            "limit_reached": not is_allowed,
            "reset_in_seconds": reset_in,
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


async def handle_options(request):
    """CORS Preflight handler."""
    return web.Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
    )


async def handle_evaluate(request):
    """
    Evaluates essay using the bot's real AI model (e.g. gpt-5.6-luna / OpenAI / Groq)
    with strict 1-trial IP protection.
    """
    client_ip = get_client_ip(request)
    is_allowed, remaining, reset_in = check_ip_limit(client_ip)

    if not is_allowed:
        logger.warning(f"Rate limit exceeded for IP [{client_ip}]. Evaluation blocked.")
        return web.json_response(
            {
                "status": "limit_reached",
                "limit_reached": True,
                "error": "Sizning saytdagi haftalik 1 ta bepul sinov limitingiz tugadi! Insholaringizni har kuni bepul tekshirish uchun rasmiy Telegram botimizga o'ting: @esseycheckerbot",
                "telegram_bot": "https://t.me/esseycheckerbot",
                "reset_in_seconds": reset_in,
            },
            status=429,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        data = await request.json()
    except Exception as e:
        return web.json_response(
            {"error": f"Invalid JSON payload: {str(e)}"},
            status=400,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    prompt = (data.get("prompt") or "").strip()
    essay_text = (data.get("essay_text") or "").strip()
    task_type = data.get("task_type", "Task 2")

    if not essay_text:
        return web.json_response(
            {"error": "Insho matni kiritilmadi (essay_text is required)."},
            status=400,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    word_count = count_words(essay_text)
    logger.info(
        f"Evaluating essay ({word_count} words) for IP [{client_ip}] with model [{ai_service.openai_model}]..."
    )

    try:
        result = await ai_service.evaluate_essay(
            essay_text=essay_text,
            task_type=task_type,
            task_prompt=prompt,
            word_count=word_count,
        )

        # Record this successful evaluation against client IP
        record_ip_evaluation(client_ip)

        # Standardize overall band for frontend convenience
        overall = (
            result.get("current_overall_band")
            or result.get("overall")
            or result.get("overall_band")
            or 0.0
        )
        result["overall"] = overall
        result["word_count"] = result.get("word_count", word_count)
        result["meets_minimum"] = result.get("meets_minimum", word_count >= 250)
        result["has_cap"] = (
            word_count < 250 and result.get("task_type", "Task 2") == "Task 2"
        )
        result["model_used"] = result.get("_model", ai_service.openai_model)
        result["provider_used"] = result.get("_provider", ai_service.provider)
        result["remaining_trials"] = 0
        result["limit_reached"] = True

        return web.json_response(
            result,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )
    except Exception as e:
        logger.error(f"Error during AI evaluation: {e}", exc_info=True)
        return web.json_response(
            {"error": f"AI model baholashda xatolik: {str(e)}"},
            status=500,
            headers={"Access-Control-Allow-Origin": "*"},
        )


async def handle_index(request):
    index_file = os.path.join(LANDING_DIR, "index.html")
    if os.path.exists(index_file):
        return web.FileResponse(index_file)
    return web.Response(text="Landing page index.html not found", status=404)


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/evaluate", handle_evaluate)
    app.router.add_options("/api/evaluate", handle_options)
    app.router.add_options("/api/status", handle_options)

    # Static file routes
    if os.path.exists(LANDING_DIR):
        app.router.add_static("/", path=LANDING_DIR, name="static")

    return app


if __name__ == "__main__":
    port = 5173
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    app = create_app()
    logger.info(
        f"🚀 Landing server ishga tushmoqda: http://localhost:{port} (Model: {ai_service.openai_model})"
    )
    web.run_app(app, host="0.0.0.0", port=port)
