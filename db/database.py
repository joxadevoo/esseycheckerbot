import logging
from datetime import date, datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_, func

from config import settings
from db.models import Base, User, Group, GroupMember, Essay, DailyUsage, GroupTopic, GroupMemberRole, Referral, Payment

logger = logging.getLogger(__name__)

# Handle connection pooling args appropriately for sqlite vs postgresql
engine_kwargs = {}
if "sqlite" in settings.DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300
    engine_kwargs["connect_args"] = {"statement_cache_size": 0}

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    """Create tables if they do not exist and ensure columns exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            from sqlalchemy import text
            if "sqlite" in settings.DATABASE_URL:
                res = await conn.execute(text("PRAGMA table_info(users);"))
                cols = [r[1] for r in res.fetchall()]
                if "extra_credits" not in cols:
                    await conn.execute(text("ALTER TABLE users ADD COLUMN extra_credits INTEGER DEFAULT 0 NOT NULL;"))
                if "referral_count" not in cols:
                    await conn.execute(text("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0 NOT NULL;"))
            else:
                await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS extra_credits INTEGER DEFAULT 0 NOT NULL;"))
                await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0 NOT NULL;"))
        except Exception as ex:
            logger.warning(f"Database migration notice: {ex}")
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


async def upsert_group_member(
    chat_id: int,
    user_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
):
    """
    Registers a user as a member of chat_id and updates their activity timestamp.
    Also ensures User record is up to date (handles users with or without username).
    """
    await upsert_user(user_id, username, full_name or "")
    async with get_session() as session:
        stmt = select(GroupMember).where(
            and_(GroupMember.chat_id == chat_id, GroupMember.user_id == user_id)
        )
        res = await session.execute(stmt)
        member = res.scalar_one_or_none()
        if member:
            member.last_seen = func.now()
        else:
            member = GroupMember(chat_id=chat_id, user_id=user_id)
            session.add(member)
        await session.commit()


async def add_user_credits(user_id: int, count: int) -> int:
    """Adds purchased essay credits to user's balance and returns the new total."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(id=user_id, extra_credits=count)
            session.add(user)
        else:
            user.extra_credits = (user.extra_credits or 0) + count
        await session.commit()
        return user.extra_credits


async def record_payment_and_add_credits(
    user_id: int,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: Optional[str],
    package_id: str,
    stars_amount: int,
    essays_count: int,
) -> Tuple[bool, int]:
    """
    Saves the payment receipt to the payments table (Supabase/DB) and adds credits to user.
    Idempotent: if charge_id already exists, does not double-credit.
    Returns (is_new: bool, new_total_credits: int).
    """
    async with get_session() as session:
        stmt = select(Payment).where(
            Payment.telegram_payment_charge_id == telegram_payment_charge_id
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        user = await session.get(User, user_id)
        current_credits = user.extra_credits if user and user.extra_credits else 0

        if existing:
            logger.warning(
                f"Payment receipt {telegram_payment_charge_id} already exists for user {user_id}. Skipping double-credit."
            )
            return False, current_credits

        # Save payment receipt to DB
        payment = Payment(
            user_id=user_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            provider_payment_charge_id=provider_payment_charge_id,
            package_id=package_id,
            stars_amount=stars_amount,
            essays_count=essays_count,
        )
        session.add(payment)

        # Update user balance
        if not user:
            user = User(id=user_id, extra_credits=essays_count)
            session.add(user)
            new_credits = essays_count
        else:
            user.extra_credits = (user.extra_credits or 0) + essays_count
            new_credits = user.extra_credits

        await session.commit()
        logger.info(
            f"Payment receipt saved in DB: user={user_id}, charge_id={telegram_payment_charge_id}, "
            f"stars={stars_amount}, essays=+{essays_count}, new_balance={new_credits}"
        )
        return True, new_credits


async def get_payment_by_charge_id(charge_id: str) -> Optional[Payment]:
    """Retrieves payment receipt by Telegram charge ID."""
    async with get_session() as session:
        stmt = select(Payment).where(Payment.telegram_payment_charge_id == charge_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_credits(user_id: int) -> int:
    """Returns the current extra credits balance for a user."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        return user.extra_credits if user and user.extra_credits else 0


async def get_user_daily_usage(user_id: int) -> int:
    """Returns today's used count for a user."""
    today = date.today()
    async with get_session() as session:
        stmt = select(DailyUsage).where(
            and_(
                DailyUsage.target_type == "user",
                DailyUsage.target_id == user_id,
                DailyUsage.usage_date == today,
            )
        )
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        return record.count if record else 0


async def process_referral(
    referrer_id: int, new_user_id: int, new_user_name: str
) -> Tuple[bool, str, int]:
    """
    Processes referral attribution when a new user joins via a referral link.
    Awards +1 bonus credit to referrer and +1 to new user.
    Returns (success: bool, message: str, referrer_credits: int).
    """
    if referrer_id == new_user_id:
        return False, "O'z-o'zingizni taklif qila olmaysiz.", 0

    async with get_session() as session:
        # Check if new_user_id already has a referral record
        stmt = select(Referral).where(Referral.referred_id == new_user_id)
        existing_ref = (await session.execute(stmt)).scalar_one_or_none()
        if existing_ref:
            return False, "Ushbu foydalanuvchi allaqachon referal orqali qo'shilgan.", 0

        # Check if new_user_id is an old user who has already submitted essays
        stmt_essays = select(func.count(Essay.id)).where(Essay.user_id == new_user_id)
        essay_count = (await session.execute(stmt_essays)).scalar() or 0
        if essay_count > 0:
            return False, "Ushbu foydalanuvchi yangi emas (avval insho topshirgan).", 0

        # Record referral
        ref_record = Referral(
            referrer_id=referrer_id,
            referred_id=new_user_id,
            reward_given=True,
        )
        session.add(ref_record)

        # Update referrer stats and extra_credits (+1)
        referrer = await session.get(User, referrer_id)
        if referrer:
            referrer.referral_count = (referrer.referral_count or 0) + 1
            referrer.extra_credits = (referrer.extra_credits or 0) + 1
            referrer_credits = referrer.extra_credits
        else:
            referrer = User(id=referrer_id, extra_credits=1, referral_count=1)
            session.add(referrer)
            referrer_credits = 1

        # Update new user extra_credits (+1 welcome bonus)
        new_user = await session.get(User, new_user_id)
        if new_user:
            new_user.extra_credits = (new_user.extra_credits or 0) + 1
        else:
            new_user = User(id=new_user_id, full_name=new_user_name, extra_credits=1)
            session.add(new_user)

        await session.commit()
        logger.info(f"Referral SUCCESS: referrer {referrer_id} referred {new_user_id}. Both awarded +1 credit.")
        return True, "Referal muvaffaqiyatli qabul qilindi!", referrer_credits


async def get_user_referral_stats(user_id: int) -> dict:
    """Returns referral count and total referrals for a user."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        count = user.referral_count if user and user.referral_count else 0
        return {
            "referral_count": count,
            "bonus_credits_earned": count,
        }



async def check_and_increment_limits(
    user_id: int, chat_id: int, is_private: bool
) -> Tuple[bool, str]:
    """
    Checks user and group daily limits. If daily limit reached, checks extra_credits.
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

        used_extra_credit = False
        if current_user_count >= settings.DAILY_USER_LIMIT:
            # Check if user has extra credits purchased via Telegram Stars
            user = await session.get(User, user_id)
            if user and user.extra_credits > 0:
                user.extra_credits -= 1
                used_extra_credit = True
                logger.info(f"User {user_id} used 1 extra credit. Remaining: {user.extra_credits}")
            else:
                return (
                    False,
                    f"Sizning bugungi bepul limitingiz ({settings.DAILY_USER_LIMIT} ta) tugadi.\n\n"
                    f"Tekshirishni davom ettirish uchun o'zingizga ma'qul yo'lni tanlang:\n"
                    f"⭐️ <b>Sotib olish:</b> Telegram Yulduzlari (Stars) orqali qo'shimcha insholar xarid qiling\n"
                    f"🎁 <b>Do'st taklif qilish:</b> Do'stlaringizni taklif qiling va har bir do'stingiz uchun <b>+1 ta bepul insho</b> oling!",
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

        # Increment user daily usage (if not using extra credits)
        if not used_extra_credit:
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
            topic.created_at = func.now()
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


async def get_group_topic_submissions(
    chat_id: int, since: Optional[datetime] = None
) -> list[tuple[Essay, Optional[User]]]:
    """Retrieves all essays submitted in a group, optionally since a given datetime, along with user info."""
    async with get_session() as session:
        stmt = (
            select(Essay, User)
            .outerjoin(User, Essay.user_id == User.id)
            .where(Essay.chat_id == chat_id)
        )
        if since:
            safe_since = since - timedelta(seconds=5)
            stmt = stmt.where(Essay.created_at >= safe_since)
        stmt = stmt.order_by(Essay.created_at.asc())
        res = await session.execute(stmt)
        return list(res.all())


async def get_student_historical_scores(chat_id: int, user_id: int) -> list[float]:
    """Returns all overall band scores for a student in this group in chronological order."""
    async with get_session() as session:
        stmt = (
            select(Essay.overall_band)
            .where(and_(Essay.chat_id == chat_id, Essay.user_id == user_id))
            .order_by(Essay.created_at.asc())
        )
        res = await session.execute(stmt)
        return [b for b in res.scalars().all() if b is not None]


async def get_group_tracked_users(chat_id: int) -> list[User]:
    """
    Returns all users tracked in this group (either recorded as group members
    or who submitted essays in this group). Handles users with or without username.
    """
    from sqlalchemy import or_
    async with get_session() as session:
        member_subq = select(GroupMember.user_id).where(GroupMember.chat_id == chat_id)
        essay_subq = select(Essay.user_id).where(Essay.chat_id == chat_id)
        stmt = (
            select(User)
            .where(or_(User.id.in_(member_subq), User.id.in_(essay_subq)))
            .order_by(User.full_name.asc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


async def get_user_teacher_groups(
    username: Optional[str], user_id: Optional[int] = None
) -> list[tuple[int, str]]:
    """
    Returns a list of (chat_id, group_title) for all groups where this user
    is registered as a teacher or admin, or where they created a topic,
    or all groups if whitelist admin.
    """
    clean_username = username.strip().lstrip("@").lower() if username else None
    async with get_session() as session:
        # Check if whitelist admin
        if user_id and settings.is_admin(user_id):
            stmt = select(Group.id, Group.title).order_by(Group.title.asc())
            res = await session.execute(stmt)
            return [(gid, gtitle or f"Guruh #{gid}") for gid, gtitle in res.all()]

        groups_map: dict[int, str] = {}

        conditions = []
        if clean_username:
            conditions.append(GroupMemberRole.username == clean_username)
        if user_id:
            conditions.append(GroupMemberRole.user_id == user_id)

        if conditions:
            from sqlalchemy import or_
            stmt = (
                select(GroupMemberRole.chat_id, Group.title)
                .outerjoin(Group, GroupMemberRole.chat_id == Group.id)
                .where(
                    and_(
                        GroupMemberRole.role.in_(["teacher", "admin"]),
                        or_(*conditions),
                    )
                )
            )
            res = await session.execute(stmt)
            for gid, gtitle in res.all():
                groups_map[gid] = gtitle or f"Guruh #{gid}"

        # Also check GroupTopic created_by
        if user_id:
            stmt_topics = (
                select(GroupTopic.chat_id, Group.title)
                .outerjoin(Group, GroupTopic.chat_id == Group.id)
                .where(GroupTopic.created_by == user_id)
            )
            res_t = await session.execute(stmt_topics)
            for gid, gtitle in res_t.all():
                if gid not in groups_map:
                    groups_map[gid] = gtitle or f"Guruh #{gid}"

        return list(groups_map.items())
