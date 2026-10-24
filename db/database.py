import logging
from datetime import date, datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_, func, or_

from config import settings
from db.models import Base, User, Group, GroupMember, Essay, DailyUsage, GroupTopic, GroupMemberRole, Referral, Payment, Feedback

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
                res_g = await conn.execute(text("PRAGMA table_info(groups);"))
                cols_g = [r[1] for r in res_g.fetchall()]
                if "added_by_user_id" not in cols_g:
                    await conn.execute(text("ALTER TABLE groups ADD COLUMN added_by_user_id BIGINT;"))
                if "reward_given" not in cols_g:
                    await conn.execute(text("ALTER TABLE groups ADD COLUMN reward_given BOOLEAN DEFAULT FALSE;"))
            else:
                await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS extra_credits INTEGER DEFAULT 0 NOT NULL;"))
                await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0 NOT NULL;"))
                await conn.execute(text("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_user_id BIGINT;"))
                await conn.execute(text("ALTER TABLE groups ADD COLUMN IF NOT EXISTS reward_given BOOLEAN DEFAULT FALSE;"))
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


async def record_group_addition_reward(
    chat_id: int, user_id: int, group_title: Optional[str] = None
) -> Tuple[bool, int]:
    """
    Rewards a user with +3 extra credits when they add the bot to a new group.
    Returns (reward_given: bool, new_total_credits: int).
    """
    async with get_session() as session:
        group = await session.get(Group, chat_id)
        should_reward = False
        if not group:
            group = Group(
                id=chat_id,
                title=group_title,
                added_by_user_id=user_id,
                reward_given=True,
            )
            session.add(group)
            should_reward = True
        else:
            if group_title:
                group.title = group_title
            if not group.reward_given:
                group.added_by_user_id = user_id
                group.reward_given = True
                should_reward = True

        new_credits = 0
        if should_reward and user_id:
            user = await session.get(User, user_id)
            if not user:
                user = User(id=user_id, extra_credits=3)
                session.add(user)
                new_credits = 3
            else:
                user.extra_credits += 3
                new_credits = user.extra_credits
            await session.commit()
            logger.info(
                f"User {user_id} rewarded +3 extra credits for adding bot to group {chat_id} ({group_title}). Total: {new_credits}"
            )
            return True, new_credits
        else:
            await session.commit()
            if user_id:
                user = await session.get(User, user_id)
                new_credits = user.extra_credits if user else 0
            return False, new_credits


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



async def get_whitelist_teacher_group_ids(teacher_id: Optional[int] = None) -> list[int]:
    """
    Returns the list of chat_ids (up to WHITELIST_MAX_GROUPS, default 5)
    where a whitelisted user is designated as teacher, added the bot, or created topics.
    Ordered chronologically by when the group was associated.
    """
    if teacher_id is not None:
        whitelist_ids = [teacher_id]
    else:
        whitelist_ids = list(settings.get_whitelist_user_ids())

    if not whitelist_ids:
        return []

    async with get_session() as session:
        # Find usernames for these whitelist user IDs
        stmt_users = select(User.username).where(User.id.in_(whitelist_ids))
        res_u = await session.execute(stmt_users)
        whitelist_usernames = [u.lower() for u in res_u.scalars().all() if u]

        conditions = [GroupMemberRole.user_id.in_(whitelist_ids)]
        if whitelist_usernames:
            conditions.append(func.lower(GroupMemberRole.username).in_(whitelist_usernames))

        # 1. Groups from GroupMemberRole (role in teacher/admin)
        stmt_roles = (
            select(GroupMemberRole.chat_id, GroupMemberRole.created_at)
            .where(
                and_(
                    GroupMemberRole.role.in_(["teacher", "admin"]),
                    or_(*conditions),
                )
            )
            .order_by(GroupMemberRole.created_at.asc())
        )
        res_r = await session.execute(stmt_roles)
        role_groups = res_r.all()

        # 2. Groups where whitelist user added the bot
        stmt_added = (
            select(Group.id, Group.created_at)
            .where(Group.added_by_user_id.in_(whitelist_ids))
            .order_by(Group.created_at.asc())
        )
        res_a = await session.execute(stmt_added)
        added_groups = res_a.all()

        # 3. Groups where whitelist user created a topic
        stmt_topics = (
            select(GroupTopic.chat_id, GroupTopic.created_at)
            .where(GroupTopic.created_by.in_(whitelist_ids))
            .order_by(GroupTopic.created_at.asc())
        )
        res_t = await session.execute(stmt_topics)
        topic_groups = res_t.all()

        # Combine and order chronologically
        all_groups = []
        seen = set()
        for gid, dt in sorted(role_groups + added_groups + topic_groups, key=lambda x: x[1] or datetime.min):
            if gid not in seen:
                seen.add(gid)
                all_groups.append(gid)

        return all_groups[: settings.WHITELIST_MAX_GROUPS]


async def is_whitelist_teacher_group(chat_id: int, teacher_id: Optional[int] = None) -> bool:
    """Checks if chat_id is one of the allowed (max 5) whitelist teacher groups."""
    allowed_groups = await get_whitelist_teacher_group_ids(teacher_id=teacher_id)
    return chat_id in allowed_groups


async def check_and_increment_limits(
    user_id: int, chat_id: int, is_private: bool
) -> Tuple[bool, str]:
    """
    Checks user and group daily limits:
    - Shaxsiy chatda (is_private=True):
      Whitelist user uchun limitsiz (cheksiz).
      Boshqa foydalanuvchilar uchun 1 ta bepul/kun + pullik tizim (Stars/Referral/Guruh).
    - Guruhda (is_private=False):
      Whitelist ustoz uchun bot tomonidan belgilangan maksimal 5 ta guruh limiti bor.
      Shu 5 ta guruhda insholar cheksiz tekshiriladi.
      6-guruh va boshqa barcha guruhlar esa oddiy pullik tizimga o'tadi
      (guruh limiti 15 ta, user limiti 1 ta, yoki Teacher Pro).
    Returns (is_allowed: bool, reason: str).
    """
    today = date.today()

    # 1. Shaxsiy chat tekshiruvi
    if is_private:
        if settings.is_whitelist_user(user_id):
            logger.info(f"User {user_id} is WHITELISTED in private chat — unlimited access.")
            return True, "OK"

        # Oddiy foydalanuvchi shaxsiy limit (1 ta bepul)
        async with get_session() as session:
            stmt_user = select(DailyUsage).where(
                and_(
                    DailyUsage.target_type == "user",
                    DailyUsage.target_id == user_id,
                    DailyUsage.usage_date == today,
                )
            )
            res_u = await session.execute(stmt_user)
            user_usage = res_u.scalar_one_or_none()
            current_user_count = user_usage.count if user_usage else 0

            used_extra_credit = False
            if current_user_count >= settings.DAILY_USER_LIMIT:
                user = await session.get(User, user_id)
                if user and user.extra_credits > 0:
                    user.extra_credits -= 1
                    used_extra_credit = True
                    logger.info(f"User {user_id} used 1 extra credit. Remaining: {user.extra_credits}")
                else:
                    return (
                        False,
                        f"Sizning bugungi bepul limitingiz ({settings.DAILY_USER_LIMIT} ta) tugadi.\n\n"
                        f"Insholarni tekshirishni davom ettirish uchun o'zingizga qulay yo'lni tanlang:\n\n"
                        f"⭐️ <b>Sotib olish:</b> Telegram Stars orqali qo'shimcha insholar xarid qiling\n"
                        f"👥 <b>Guruhga qo'shish:</b> Botni IELTS guruhiga qo'shing va darhol <b>+3 ta bepul insho</b> yuting!\n"
                        f"🎁 <b>Do'st taklif qilish:</b> Har bir taklif qilingan do'st uchun <b>+1 ta bepul insho</b> oling!",
                    )

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

    # 2. Guruh chat tekshiruvi
    # Whitelist ustozning tasdiqlangan 5 ta guruhi bormi?
    if await is_whitelist_teacher_group(chat_id):
        logger.info(f"Group {chat_id} is an approved Whitelist Teacher Group (within {settings.WHITELIST_MAX_GROUPS} groups limit) — access granted.")
        return True, "OK"

    # Guruh 5 ta ustoz guruhi ichida emas -> "qolgani ustozmi oddiy usermi farqi yo'q pullikga o'tadi"
    async with get_session() as session:
        # Guruh limitini tekshirish (15 ta)
        stmt_group = select(DailyUsage).where(
            and_(
                DailyUsage.target_type == "group",
                DailyUsage.target_id == chat_id,
                DailyUsage.usage_date == today,
            )
        )
        res_g = await session.execute(stmt_group)
        group_usage = res_g.scalar_one_or_none()
        current_group_count = group_usage.count if group_usage else 0

        group = await session.get(Group, chat_id)
        group_limit = (
            settings.DAILY_GROUP_LIMIT * 5
            if (group and group.is_premium)
            else settings.DAILY_GROUP_LIMIT
        )

        if current_group_count >= group_limit:
            return (
                False,
                f"Ushbu guruhning kunlik bepul tekshirish limiti ({group_limit} ta) tugadi.\n\n"
                f"Ertaga yangi bepul limit beriladi yoki guruh administratori <b>/teacher</b> buyrug'i orqali cheksiz Teacher Pro obunasini faollashtirishi mumkin!",
            )

        # Guruh ichidagi foydalanuvchi limitini tekshirish
        stmt_user = select(DailyUsage).where(
            and_(
                DailyUsage.target_type == "user",
                DailyUsage.target_id == user_id,
                DailyUsage.usage_date == today,
            )
        )
        res_u = await session.execute(stmt_user)
        user_usage = res_u.scalar_one_or_none()
        current_user_count = user_usage.count if user_usage else 0

        used_extra_credit = False
        if current_user_count >= settings.DAILY_USER_LIMIT:
            user = await session.get(User, user_id)
            if user and user.extra_credits > 0:
                user.extra_credits -= 1
                used_extra_credit = True
                logger.info(f"User {user_id} used 1 extra credit in group {chat_id}. Remaining: {user.extra_credits}")
            else:
                return (
                    False,
                    f"Sizning bugungi bepul limitingiz ({settings.DAILY_USER_LIMIT} ta) tugadi.\n\n"
                    f"Insholarni tekshirishni davom ettirish uchun o'zingizga qulay yo'lni tanlang:\n\n"
                    f"⭐️ <b>Sotib olish:</b> Telegram Stars orqali qo'shimcha insholar xarid qiling\n"
                    f"👥 <b>Guruhga qo'shish:</b> Botni IELTS guruhiga qo'shing va darhol <b>+3 ta bepul insho</b> yuting!\n"
                    f"🎁 <b>Do'st taklif qilish:</b> Har bir taklif qilingan do'st uchun <b>+1 ta bepul insho</b> oling!",
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
        if not user_id:
            stmt_u = select(User.id).where(func.lower(User.username) == clean_username)
            res_u = await session.execute(stmt_u)
            found_uid = res_u.scalar_one_or_none()
            if found_uid:
                user_id = found_uid

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


async def save_feedback(
    user_id: int,
    user_message_id: Optional[int] = None,
    text: Optional[str] = None,
    media_type: str = "text",
    admin_id: Optional[int] = None,
    admin_message_id: Optional[int] = None,
) -> Feedback:
    """Saves a new user feedback/support ticket into database."""
    async with get_session() as session:
        fb = Feedback(
            user_id=user_id,
            user_message_id=user_message_id,
            text=text,
            media_type=media_type,
            admin_id=admin_id,
            admin_message_id=admin_message_id,
            status="pending",
        )
        session.add(fb)
        await session.commit()
        await session.refresh(fb)
        return fb


async def update_feedback_admin_msg(feedback_id: int, admin_id: int, admin_message_id: int):
    """Updates the admin message ID mapping for a feedback ticket."""
    async with get_session() as session:
        fb = await session.get(Feedback, feedback_id)
        if fb:
            fb.admin_id = admin_id
            fb.admin_message_id = admin_message_id
            await session.commit()


async def get_feedback_by_admin_msg(admin_id: int, admin_message_id: int) -> Optional[Feedback]:
    """Finds pending or existing feedback associated with an admin's notification message."""
    async with get_session() as session:
        stmt = (
            select(Feedback)
            .where(
                and_(
                    Feedback.admin_id == admin_id,
                    Feedback.admin_message_id == admin_message_id,
                )
            )
            .order_by(Feedback.created_at.desc())
        )
        res = await session.execute(stmt)
        return res.scalars().first()


async def mark_feedback_answered(feedback_id: int, reply_text: str):
    """Marks feedback as answered and stores reply text."""
    async with get_session() as session:
        fb = await session.get(Feedback, feedback_id)
        if fb:
            fb.status = "answered"
            fb.reply_text = reply_text
            fb.replied_at = func.now()
            await session.commit()
