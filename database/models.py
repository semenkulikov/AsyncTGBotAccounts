from sqlalchemy import Column, Integer, String, Boolean, Text
from sqlalchemy.orm import declarative_base

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
