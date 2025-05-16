from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

from config_data.config import DATABASE_URL

Base = declarative_base()


class User(Base):
    """ Модель для юзера """
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    is_admin = Column(Boolean, default=False)
    accounts = relationship("Account", back_populates="user")
    channels = relationship("UserChannel", back_populates="user")


class Group(Base):
    """ Модель для групп """
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
    user_id = Column(Integer, ForeignKey('users.user_id'))
    phone = Column(String)
    session = Column(String)
    password = Column(String)
    is_active = Column(Boolean, default=True)
    last_activity = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="accounts")
    reactions = relationship("AccountReaction", back_populates="account")


class UserChannel(Base):
    __tablename__ = 'user_channels'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    channel_id = Column(Integer)
    channel_username = Column(String)
    channel_title = Column(String)
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=datetime.utcnow)
    min_reactions = Column(Integer, default=1)
    max_reactions = Column(Integer, default=15)
    views = Column(Integer, default=0)

    user = relationship("User", back_populates="channels")
    reactions = relationship("AccountReaction", back_populates="channel")


class AccountReaction(Base):
    __tablename__ = 'account_reactions'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'))
    channel_id = Column(Integer, ForeignKey('user_channels.id'))
    post_id = Column(Integer)
    reaction = Column(String)
    available_reactions = Column(JSON, nullable=True)  # Список доступных реакций канала
    user_reactions = Column(JSON, nullable=True)      # Пользовательский список реакций
    reacted_at = Column(DateTime, default=datetime.utcnow)
    account = relationship("Account", back_populates="reactions")
    channel = relationship("UserChannel", back_populates="reactions") 


engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
