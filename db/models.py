from datetime import datetime, date
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    Date,
    func,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram user ID
    username = Column(String(128), nullable=True)
    full_name = Column(String(256), nullable=False, default="")
    extra_credits = Column(Integer, default=0, nullable=False)
    referral_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=func.now())


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, index=True, nullable=False)
    referred_id = Column(BigInteger, unique=True, index=True, nullable=False)
    reward_given = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    telegram_payment_charge_id = Column(String(128), unique=True, index=True, nullable=False)
    provider_payment_charge_id = Column(String(128), nullable=True)
    package_id = Column(String(64), nullable=False)
    stars_amount = Column(Integer, nullable=False)
    essays_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now())


class Group(Base):
    __tablename__ = "groups"

    id = Column(BigInteger, primary_key=True)  # Telegram chat ID
    title = Column(String(256), nullable=True)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    joined_at = Column(DateTime, default=func.now())
    last_seen = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_group_member"),
    )


class GroupTopic(Base):
    __tablename__ = "group_topics"

    chat_id = Column(BigInteger, primary_key=True)
    topic_text = Column(Text, nullable=False)
    message_id = Column(BigInteger, nullable=True)
    announcement_msg_id = Column(BigInteger, nullable=True)
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=func.now())


class GroupMemberRole(Base):
    __tablename__ = "group_member_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=True)
    username = Column(String(128), index=True, nullable=False)  # Normalized lowercase without '@'
    role = Column(String(32), default="teacher", nullable=False)  # 'teacher' or 'admin'
    assigned_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=func.now())


class Essay(Base):
    __tablename__ = "essays"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    chat_id = Column(BigInteger, index=True, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    essay_hash = Column(String(64), index=True, nullable=False)
    original_text = Column(Text, nullable=False)
    word_count = Column(Integer, default=0)
    overall_band = Column(Float, nullable=True)
    feedback_json = Column(Text, nullable=False)  # JSON formatted feedback
    created_at = Column(DateTime, default=func.now())


class DailyUsage(Base):
    __tablename__ = "daily_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_type = Column(String(16), nullable=False)  # 'user' or 'group'
    target_id = Column(BigInteger, nullable=False)
    usage_date = Column(Date, default=date.today, nullable=False)
    count = Column(Integer, default=0, nullable=False)


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    user_message_id = Column(BigInteger, nullable=True)
    admin_id = Column(BigInteger, index=True, nullable=True)
    admin_message_id = Column(BigInteger, index=True, nullable=True)
    text = Column(Text, nullable=True)
    media_type = Column(String(32), default="text", nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    reply_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    replied_at = Column(DateTime, nullable=True)

