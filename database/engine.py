import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config_data.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL)

async_session = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)
