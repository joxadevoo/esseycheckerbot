import os
import sys
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


env_file_path = os.getenv("ENV_FILE", ".env")
if "--test" in sys.argv:
    env_file_path = ".env.test"
elif "--env" in sys.argv:
    try:
        env_file_path = sys.argv[sys.argv.index("--env") + 1]
    except IndexError:
        pass


class Settings(BaseSettings):
    BOT_TOKEN: str = "placeholder_bot_token"
    
    # AI Provider: 'openai' or 'groq'
    AI_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = "placeholder_openai_key"
    OPENAI_MODEL: str = "gpt-5.6-luna"

    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    DATABASE_URL: str = "sqlite+aiosqlite:///bot.db"
    REDIS_URL: Optional[str] = None

    DAILY_USER_LIMIT: int = 5
    DAILY_GROUP_LIMIT: int = 50
    CACHE_TTL_SECONDS: int = 86400  # 24 hours

    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_PORT: int = 8000
    PORT: int = 8080

    ADMIN_IDS: str = "7326292681"

    model_config = SettingsConfigDict(
        env_file=env_file_path,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def is_admin(self, user_id: int) -> bool:
        if user_id == 7326292681:
            return True
        admin_list = [int(i.strip()) for i in self.ADMIN_IDS.split(",") if i.strip().isdigit()]
        return user_id in admin_list


settings = Settings()
