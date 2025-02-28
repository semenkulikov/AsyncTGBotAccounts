from sqlalchemy import select
from telethon import TelegramClient
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
import asyncio
import random
from datetime import datetime

from config_data.config import CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX
from database.models import Account, async_session


class AccountService:
    def __init__(self, encryption_key: str):
        self.cipher = Fernet(encryption_key.encode())

    async def encrypt_session(self, session_str: str) -> bytes:
        return self.cipher.encrypt(session_str.encode())

    async def decrypt_session(self, encrypted_data: bytes) -> str:
        return self.cipher.decrypt(encrypted_data).decode()

    async def create_account(self, phone: str, session_str: str):
        async with async_session() as session:
            encrypted = await self.encrypt_session(session_str)
            account = Account(phone=phone, session_data=encrypted)
            session.add(account)
            await session.commit()
            return account

    async def get_all_accounts(self):
        async with async_session() as session:
            result = await session.execute(select(Account))
            return result.scalars().all()

    async def delete_account(self, phone: str):
        async with async_session() as session:
            account = await session.get(Account, phone)
            if account:
                await session.delete(account)
                await session.commit()
                return True
            return False

    async def update_last_active(self, phone: str):
        async with async_session() as session:
            account = await session.get(Account, phone)
            if account:
                account.last_active = datetime.now()
                await session.commit()
                return True
            return False


class AccountActivity:
    def __init__(self, api_id: int, api_hash: str, account_service: AccountService):
        self.api_id = api_id
        self.api_hash = api_hash
        self.account_service = account_service

    async def _connect_client(self, session_str: str):
        client = TelegramClient(StringSession(session_str), self.api_id, self.api_hash)
        await client.connect()
        return client

    async def perform_activity(self, account):
        try:
            session_str = await self.account_service.decrypt_session(account.session_data)
            async with await self._connect_client(session_str) as client:
                if await client.is_user_authorized():
                    await client.get_me()
                    await self.account_service.update_last_active(account.phone)
                    return True
            return False
        except Exception as e:
            print(f"Error for {account.phone}: {str(e)}")
            return False

    async def random_activity_loop(self):
        while True:
            accounts = await self.account_service.get_all_accounts()
            if accounts:
                account = random.choice(accounts)
                await self.perform_activity(account)
            interval = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
            await asyncio.sleep(interval)
