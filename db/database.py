import logging
from datetime import date
from contextlib import asynccontextmanager
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_

from config import settings
from db.models import Base, User, Group, Essay, DailyUsage, GroupTopic, GroupMemberRole

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


async def get_group_topic(chat_id: int) -> Optional[GroupTopic]:
    """Retrieves active IELTS topic for a specific group."""
    async with get_session() as session:
        return await session.get(GroupTopic, chat_id)


async def set_group_topic(
    chat_id: int,
    topic_text: str,
    message_id: Optional[int] = None,
    created_by: Optional[int] = None,
    announcement_msg_id: Optional[int] = None,
) -> GroupTopic:
    """Sets or updates the active IELTS topic for a group."""
    async with get_session() as session:
        topic = await session.get(GroupTopic, chat_id)
        if not topic:
            topic = GroupTopic(
                chat_id=chat_id,
                topic_text=topic_text,
                message_id=message_id,
                created_by=created_by,
                announcement_msg_id=announcement_msg_id,
            )
            session.add(topic)
        else:
            topic.topic_text = topic_text
            topic.message_id = message_id
            topic.created_by = created_by
            if announcement_msg_id is not None:
                topic.announcement_msg_id = announcement_msg_id
        await session.commit()
        await session.refresh(topic)
        return topic


async def clear_group_topic(chat_id: int) -> bool:
    """Removes the active topic for a group."""
    async with get_session() as session:
        topic = await session.get(GroupTopic, chat_id)
        if topic:
            await session.delete(topic)
            await session.commit()
            return True
        return False


async def set_group_user_role(
    chat_id: int,
    username: str,
    role: str = "teacher",
    assigned_by: Optional[int] = None,
    user_id: Optional[int] = None,
) -> GroupMemberRole:
    """Assigns or updates a role (teacher/admin) for a username in a group."""
    clean_username = username.strip().lstrip("@").lower()
    async with get_session() as session:
        stmt = select(GroupMemberRole).where(
            and_(
                GroupMemberRole.chat_id == chat_id,
                GroupMemberRole.username == clean_username,
            )
        )
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        if not record:
            record = GroupMemberRole(
                chat_id=chat_id,
                username=clean_username,
                role=role.lower(),
                assigned_by=assigned_by,
                user_id=user_id,
            )
            session.add(record)
        else:
            record.role = role.lower()
            record.assigned_by = assigned_by
            if user_id:
                record.user_id = user_id
        await session.commit()
        await session.refresh(record)
        return record


async def remove_group_user_role(chat_id: int, username: str) -> bool:
    """Removes a role assigned to a username in a group."""
    clean_username = username.strip().lstrip("@").lower()
    async with get_session() as session:
        stmt = select(GroupMemberRole).where(
            and_(
                GroupMemberRole.chat_id == chat_id,
                GroupMemberRole.username == clean_username,
            )
        )
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            await session.delete(record)
            await session.commit()
            return True
        return False


async def get_group_roles(chat_id: int) -> list[GroupMemberRole]:
    """Returns all custom assigned roles for a group."""
    async with get_session() as session:
        stmt = (
            select(GroupMemberRole)
            .where(GroupMemberRole.chat_id == chat_id)
            .order_by(GroupMemberRole.created_at.asc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


async def check_user_role_in_group(
    chat_id: int,
    username: Optional[str],
    user_id: Optional[int] = None,
) -> Optional[str]:
    """
    Returns role ('teacher' or 'admin') if the user has one explicitly set in this group.
    Matches by username or user_id.
    """
    clean_username = username.strip().lstrip("@").lower() if username else None
    async with get_session() as session:
        conditions = []
        if clean_username:
            conditions.append(GroupMemberRole.username == clean_username)
        if user_id:
            conditions.append(GroupMemberRole.user_id == user_id)

        if not conditions:
            return None

        from sqlalchemy import or_
        stmt = select(GroupMemberRole).where(
            and_(
                GroupMemberRole.chat_id == chat_id,
                or_(*conditions),
            )
        )
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        return record.role if record else None
