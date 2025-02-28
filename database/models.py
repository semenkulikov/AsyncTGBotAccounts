from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, Boolean, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

from config_data.config import DATABASE_URL

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False)  # Telegram ID
    full_name = Column(String, nullable=False)
    username = Column(String, nullable=False)
    is_premium = Column(Boolean, nullable=True)


class Group(Base):
    __tablename__ = 'groups'

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    invite_link = Column(String, nullable=True)
    location = Column(String, nullable=True)
    username = Column(String, nullable=True)


class Account(AsyncAttrs, Base):
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True)
    phone = Column(String(20), unique=True)
    session_data = Column(LargeBinary)
    last_active = Column(DateTime)
    two_factor = Column(String(50), nullable=True)

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
