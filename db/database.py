import logging
from datetime import date
from contextlib import asynccontextmanager
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_

from config import settings
from db.models import Base, User, Group, Essay, DailyUsage

logger = logging.getLogger(__name__)

# Handle connection pooling args appropriately for sqlite vs postgresql
engine_kwargs = {}
if "sqlite" in settings.DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    """Create tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully.")


@asynccontextmanager
async def get_session() -> AsyncSession:
    """Async session context manager."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def upsert_user(user_id: int, username: Optional[str], full_name: str):
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(id=user_id, username=username, full_name=full_name)
            session.add(user)
        else:
            user.username = username
            user.full_name = full_name
        await session.commit()


async def upsert_group(chat_id: int, title: Optional[str]):
    async with get_session() as session:
        group = await session.get(Group, chat_id)
        if not group:
            group = Group(id=chat_id, title=title)
            session.add(group)
        else:
            group.title = title
        await session.commit()


async def check_and_increment_limits(
    user_id: int, chat_id: int, is_private: bool
) -> Tuple[bool, str]:
    """
    Checks user and group daily limits. If within limit, increments usage count.
    Admin users have unlimited access.
    Returns (is_allowed: bool, reason: str).
    """
    # Exemption for admin / test user
    if settings.is_admin(user_id):
        logger.info(f"User {user_id} is ADMIN/WHITELISTED — limits completely bypassed.")
        return True, "OK"

    today = date.today()

    async with get_session() as session:
        # 1. Check user limit
        stmt_user = select(DailyUsage).where(
            and_(
                DailyUsage.target_type == "user",
                DailyUsage.target_id == user_id,
                DailyUsage.usage_date == today,
            )
        )
        result_user = await session.execute(stmt_user)
        user_usage = result_user.scalar_one_or_none()
        current_user_count = user_usage.count if user_usage else 0

        if current_user_count >= settings.DAILY_USER_LIMIT:
            return (
                False,
                f"Sizning kunlik limitingiz ({settings.DAILY_USER_LIMIT} ta) tugadi. Ertaga yana davom etishingiz mumkin!",
            )

        # 2. If in a group, check group limit
        if not is_private:
            stmt_group = select(DailyUsage).where(
                and_(
                    DailyUsage.target_type == "group",
                    DailyUsage.target_id == chat_id,
                    DailyUsage.usage_date == today,
                )
            )
            result_group = await session.execute(stmt_group)
            group_usage = result_group.scalar_one_or_none()
            current_group_count = group_usage.count if group_usage else 0

            # Check if group is premium
            group = await session.get(Group, chat_id)
            group_limit = (
                settings.DAILY_GROUP_LIMIT * 5
                if (group and group.is_premium)
                else settings.DAILY_GROUP_LIMIT
            )

            if current_group_count >= group_limit:
                return (
                    False,
                    f"Ushbu guruhning kunlik bepul tekshirish limiti ({group_limit} ta) tugadi. Ertaga qayta urinib ko'ring yoki Premium obunani faollashtiring!",
                )

            # Increment group usage
            if not group_usage:
                group_usage = DailyUsage(
                    target_type="group", target_id=chat_id, usage_date=today, count=1
                )
                session.add(group_usage)
            else:
                group_usage.count += 1

        # Increment user usage
        if not user_usage:
            user_usage = DailyUsage(
                target_type="user", target_id=user_id, usage_date=today, count=1
            )
            session.add(user_usage)
        else:
            user_usage.count += 1

        await session.commit()
        return True, "OK"


async def save_essay_result(
    user_id: int,
    chat_id: int,
    message_id: int,
    essay_hash: str,
    text: str,
    word_count: int,
    overall_band: float,
    feedback_json: str,
) -> int:
    async with get_session() as session:
        essay = Essay(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            essay_hash=essay_hash,
            original_text=text,
            word_count=word_count,
            overall_band=overall_band,
            feedback_json=feedback_json,
        )
        session.add(essay)
        await session.commit()
        await session.refresh(essay)
        return essay.id


async def get_cached_essay_by_hash(essay_hash: str) -> Optional[Essay]:
    async with get_session() as session:
        stmt = (
            select(Essay)
            .where(Essay.essay_hash == essay_hash)
            .order_by(Essay.id.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
