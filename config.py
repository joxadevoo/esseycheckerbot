import os
import sys
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


env_file_path = os.getenv("ENV_FILE", ".env")
if "--test" in sys.argv or "--dev" in sys.argv:
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
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    DATABASE_URL: str = "sqlite+aiosqlite:///bot.db"
    REDIS_URL: Optional[str] = None

    DAILY_USER_LIMIT: int = 1
    DAILY_GROUP_LIMIT: int = 15
    CACHE_TTL_SECONDS: int = 86400  # 24 hours

    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_PORT: int = 8000
    WEBHOOK_SECRET: Optional[str] = None
    PORT: int = 8080

    # Dedicated real developer / admin ID (for feedback & collaboration inquiries)
    DEVELOPER_CHAT_ID: int = 7326292681

    # Whitelisted User (Shaxsiyda cheksiz insho tekshirish, guruhlarda max 5 ta guruh limiti)
    WHITELIST: Optional[str] = None
    WHITELIST_USER_ID: Optional[int] = None
    WHITELIST_ID: Optional[int] = None
    WHITELIST_MAX_GROUPS: int = 5
    ADMIN_ID: Optional[int] = None
    ADMIN_IDS: str = ""

    model_config = SettingsConfigDict(
        env_file=env_file_path,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_admin_ids(self) -> set[int]:
        """Returns set of user IDs who are actual bot administrators/owners."""
        ids = set()
        if self.DEVELOPER_CHAT_ID:
            ids.add(self.DEVELOPER_CHAT_ID)
        if self.ADMIN_ID:
            ids.add(self.ADMIN_ID)
        if self.ADMIN_IDS:
            for part in str(self.ADMIN_IDS).split(","):
                if part.strip().isdigit():
                    ids.add(int(part.strip()))
        return ids

    def is_admin(self, user_id: int) -> bool:
        """Strictly checks if user is the bot administrator/owner (access to stats, db export, etc.)."""
        return user_id in self.get_admin_ids()

    def get_whitelist_user_ids(self) -> set[int]:
        """Returns set of user IDs who have bypass privileges for essay limits (includes admins)."""
        ids = set(self.get_admin_ids())
        if self.WHITELIST_USER_ID:
            ids.add(self.WHITELIST_USER_ID)
        if self.WHITELIST_ID:
            ids.add(self.WHITELIST_ID)
        if self.WHITELIST:
            for part in str(self.WHITELIST).split(","):
                if part.strip().isdigit():
                    ids.add(int(part.strip()))
        return ids

    def is_whitelist_user(self, user_id: int) -> bool:
        return user_id in self.get_whitelist_user_ids()


settings = Settings()
