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
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram user ID
    username = Column(String(128), nullable=True)
    full_name = Column(String(256), nullable=False, default="")
    created_at = Column(DateTime, default=func.now())


class Group(Base):
    __tablename__ = "groups"

    id = Column(BigInteger, primary_key=True)  # Telegram chat ID
    title = Column(String(256), nullable=True)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


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
