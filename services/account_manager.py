from typing import Dict, List
from sqlalchemy import select, and_
from cryptography.fernet import Fernet
import asyncio
import random
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from config_data.config import CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX, API_ID, API_HASH
from database.models import Account, User, async_session
from telethon.tl.types import User as TelegramUser
from telethon.network import ConnectionTcpAbridged

from loader import app_logger


class AccountService:
    def __init__(self, encryption_key: str):
        self.cipher = Fernet(encryption_key.encode())

    async def encrypt_session(self, session_str: str) -> bytes:
        app_logger.debug("Сессия расшифрована")
        return self.cipher.encrypt(session_str.encode())

    async def decrypt_session(self, encrypted_data: bytes) -> str:
        app_logger.debug("Сессия зашифрована")
        return self.cipher.decrypt(encrypted_data).decode()

    async def _create_client(self, session_str: str) -> TelegramClient:
        app_logger.debug("Создается клиент Telegram")
        return TelegramClient(
            session=StringSession(session_str),
            api_id=API_ID,
            api_hash=API_HASH,
            connection=ConnectionTcpAbridged,
            device_model="Samsung S24 Ultra",
            app_version="10.2.0",
            system_version="Android 14",
            lang_code="en",
            system_lang_code="en-US",
            timeout=20,
            auto_reconnect=True
        )

    async def validate_session(self, session_str: str) -> bool:
        app_logger.debug("Проверяется сессия Telegram")
        client = None
        try:
            client = TelegramClient(
                StringSession(session_str),
                API_ID,
                API_HASH,
                device_model="Xiaomi Redmi Note 12",
                app_version="10.5.2",
                system_version="Android 13"
            )

            await client.connect()

            if not await client.is_user_authorized():
                return False

            # Дополнительная проверка через получение информации об аккаунте
            me = await client.get_me()
            return me is not None and hasattr(me, 'phone')

        except Exception as e:
            app_logger.error(f"Ошибка валидации сессии: {str(e)}")
            return False
        finally:
            if client:
                await client.disconnect()

    async def create_account(self, user_id: int, phone: str, session_str: str):
        app_logger.debug("Создаётся аккаунт Telegram")
        async with async_session() as session:
            encrypted = await self.encrypt_session(session_str)
            account = Account(
                user_id=user_id,
                phone=phone,
                session_data=encrypted,
                is_active=True
            )
            session.add(account)
            await session.commit()
            return account

    async def get_user_accounts(self, user_id: int) -> List[Account]:
        app_logger.debug("Получены аккаунты пользователя Telegram")
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.user_id == user_id)
            )
            return result.scalars().all()

    async def toggle_account(self, user_id: int, phone: str) -> tuple[bool, bool]:
        app_logger.debug("Изменяется активность аккаунта Telegram")
        async with async_session() as session:
            account = await session.execute(
                select(Account).where(
                    and_(
                        Account.user_id == user_id,
                        Account.phone == phone
                    )
                )
            )
            account = account.scalar()
            if account:
                old_status = account.is_active
                account.is_active = not account.is_active
                new_status = account.is_active
                await session.commit()
                return True, old_status, new_status
            return False, False, False


    async def update_last_active(self, phone: str):
        app_logger.debug("Обновляется дата последнего входа аккаунта Telegram")
        async with async_session() as session:
            account = await session.execute(
                select(Account).where(Account.phone == phone)
            )
            account = account.scalar()
            if account:
                account.last_active = datetime.now()
                await session.commit()

    async def get_all_active_accounts(self) -> List[Account]:
        app_logger.debug("Получены активные аккаунты Telegram")
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.is_active == True)
            )
            return result.scalars().all()


class UserActivityManager:
    def __init__(self):
        self.user_tasks: Dict[int, asyncio.Task] = {}
        self.account_tasks: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def start_user_activity(self, user_id: int, service: AccountService):
        async with self.lock:
            if user_id not in self.user_tasks:
                self.user_tasks[user_id] = asyncio.create_task(
                    self._user_monitor_loop(user_id, service)
                )
                app_logger.info(f"Activity check started for user {user_id}")

    async def stop_user_activity(self, user_id: int):
        async with self.lock:
            task = self.user_tasks.get(user_id)
            if task:
                task.cancel()
                del self.user_tasks[user_id]
                app_logger.info(f"Activity check stopped for user {user_id}")

    async def stop_account_activity(self, phone: str):
        async with self.lock:
            task = self.account_tasks.get(phone)
            if task and not task.done():
                task.cancel()
                del self.account_tasks[phone]
                app_logger.info(f"Задачи для аккаунта {phone} остановлены")

    async def _user_monitor_loop(self, user_id: int, service: AccountService):
        while True:
            try:
                accounts = await service.get_user_accounts(user_id)
                await self._manage_account_tasks(accounts, service)
                await asyncio.sleep(60)  # Check every minute for new accounts
                app_logger.info(f"Activity check for user {user_id}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(60)

    async def _manage_account_tasks(self, accounts: List[Account], service: AccountService):
        current_phones = {acc.phone for acc in accounts if acc.is_active}
        existing_phones = set(self.account_tasks.keys())

        # Start new tasks
        for phone in current_phones - existing_phones:
            account = next(acc for acc in accounts if acc.phone == phone)
            self.account_tasks[phone] = asyncio.create_task(
                self._account_activity_loop(account, service)
            )
            app_logger.info(f"Activity check started for {phone}")

        # Stop removed tasks
        for phone in existing_phones - current_phones:
            self.account_tasks[phone].cancel()
            del self.account_tasks[phone]
            app_logger.info(f"Activity check stopped for {phone}")

    async def _account_activity_loop(self, account: Account, service: AccountService):
        while True:
            try:
                await self._perform_activity(account, service)
                interval = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
                app_logger.info(f"Activity check for {account.phone}")
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(60)

    async def _perform_activity(self, account: Account, service: AccountService):
        try:
            session_str = await service.decrypt_session(account.session_data)
            client = await service._create_client(session_str)

            await client.connect()
            if not await client.is_user_authorized():
                app_logger.error(f"Session expired for {account.phone}")
                return

            me = await client.get_me()
            if isinstance(me, TelegramUser):
                await service.update_last_active(account.phone)
                app_logger.info(f"Activity success for {account.phone}")

        except Exception as e:
            app_logger.error(f"Activity error for {account.phone}: {str(e)}")
        finally:
            await client.disconnect()
