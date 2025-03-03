from typing import Dict, List
from sqlalchemy import select, and_
from cryptography.fernet import Fernet
import asyncio
import random
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionExpiredError, SessionPasswordNeededError, AuthKeyError, FloodWaitError
from telethon.sessions import StringSession
from config_data.config import CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX, API_ID, API_HASH
from database.models import Account, User, async_session
from telethon.tl.types import User as TelegramUser
from telethon.network import ConnectionTcpAbridged

from database.query_orm import get_user_by_user_id
from loader import app_logger, bot
import traceback


class AccountService:
    def __init__(self, encryption_key: str):
        self.cipher = Fernet(encryption_key.encode())
        self.active_sessions: Dict[str, TelegramClient] = {}

    async def encrypt_session(self, session_str: str) -> bytes:
        app_logger.debug(f"Шифрование сессии длиной {len(session_str)} символов")
        return self.cipher.encrypt(session_str.encode())

    async def decrypt_session(self, encrypted_data: bytes) -> str:
        app_logger.debug(f"Дешифрование данных сессии размером {len(encrypted_data)} байт")
        return self.cipher.decrypt(encrypted_data).decode()

    async def _create_client(self, session_str: str) -> TelegramClient:
        app_logger.debug(f"Создание клиента для сессии: {session_str[:15]}...")
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
            timeout=30,
            auto_reconnect=False
        )

    async def validate_session(self, session_str: str) -> bool:
        """Проверка и кэширование активной сессии"""
        app_logger.info(f"Проверка сессии: {session_str[:10]}...")

        # Проверка кэша с учетом TTL (30 минут)
        if session_str in self.active_sessions:
            cached_time = self.active_sessions[session_str]['timestamp']
            if (datetime.now() - cached_time).seconds < 1800:
                app_logger.debug("Использование кэшированной сессии")
                return True
            del self.active_sessions[session_str]

        client = None
        try:
            client = await self._create_client(session_str)
            await client.connect()

            # Добавляем проверку flood-wait
            me = await client.get_me()
            if not me or not hasattr(me, 'phone'):
                app_logger.warning("Не удалось получить информацию об аккаунте")
                return False

            # Обновляем кэш
            self.active_sessions[session_str] = {
                'client': client,
                'timestamp': datetime.now()
            }
            app_logger.info(f"Успешная проверка сессии для {me.phone}")
            return True

        except (SessionPasswordNeededError, AuthKeyError) as e:
            app_logger.warning(f"Сессия требует повторной авторизации: {str(e)}")
            return False
        except FloodWaitError as e:
            app_logger.warning(f"Требуется ожидание: {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            return await self.validate_session(session_str)
        except Exception as e:
            app_logger.error(f"Ошибка проверки сессии: {str(e)}")
            return False
        finally:
            if client and session_str not in self.active_sessions:
                await client.disconnect()

    async def create_account(self, user_id: int, phone: str, session_str: str):
        user = await get_user_by_user_id(user_id)
        app_logger.info(f"Создание аккаунта для пользователя {user.full_name}, телефон: {phone}")
        async with async_session() as session:
            try:
                encrypted = await self.encrypt_session(session_str)
                account = Account(
                    user_id=user_id,
                    phone=phone,
                    session_data=encrypted,
                    is_active=True
                )
                session.add(account)
                await session.commit()
                app_logger.info(f"Аккаунт {phone} успешно создан")
                return account
            except Exception as e:
                app_logger.error(f"Ошибка создания аккаунта: {str(e)}")
                raise

    async def get_user_accounts(self, user_id: int) -> List[Account]:
        user = await get_user_by_user_id(user_id)
        app_logger.debug(f"Получение аккаунтов пользователя {user.full_name}")
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.user_id == user_id)
            )
            accounts = result.scalars().all()
            app_logger.info(f"Найдено {len(accounts)} аккаунтов для пользователя {user.full_name}")
            return accounts

    async def toggle_account(self, user_id: int, phone: str) -> tuple[bool, bool]:
        user = await get_user_by_user_id(user_id)
        app_logger.info(f"Изменение статуса аккаунта {phone} пользователя {user.full_name}")
        async with async_session() as session:
            try:
                account = await session.execute(
                    select(Account).where(
                        and_(
                            Account.user_id == user_id,
                            Account.phone == phone
                        )
                    )
                )
                account = account.scalar()

                if not account:
                    app_logger.warning(f"Аккаунт {phone} не найден")
                    return False, False, False

                old_status = account.is_active
                account.is_active = not account.is_active
                new_status = account.is_active
                await session.commit()

                app_logger.info(f"Статус аккаунта {phone} изменен: {'активен' if new_status else 'неактивен'}")
                return True, old_status, new_status

            except Exception as e:
                app_logger.error(f"Ошибка изменения статуса: {str(e)}")
                return False, False, False

    async def update_last_active(self, phone: str):
        app_logger.debug(f"Обновление времени активности для {phone}")
        async with async_session() as session:
            account = await session.execute(
                select(Account).where(Account.phone == phone))
            account = account.scalar()
            if account:
                account.last_active = datetime.now()
                await session.commit()
                app_logger.info(f"Обновлено время активности для {phone}")

    async def get_all_active_accounts(self) -> List[Account]:
        app_logger.debug("Получение всех активных аккаунтов")
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.is_active == True))
            accounts = result.scalars().all()
            app_logger.info(f"Найдено {len(accounts)} активных аккаунтов")
            return accounts

    async def delete_account(self, phone: str) -> bool:
        async with async_session() as session:
            try:
                result = await session.execute(
                    select(Account).where(Account.phone == phone))
                account = result.scalar()
                if account:
                # Получаем сессию для выхода из аккаунта
                    session_str = await self.decrypt_session(account.session_data)
                    try:
                        client = await self._create_client(session_str)
                        await client.connect()
                        await client.log_out()  # Явный выход из аккаунта
                        app_logger.info(f"Выполнен выход из аккаунта {phone}")
                    except Exception as e:
                        app_logger.error(f"Ошибка выхода из аккаунта: {str(e)}")
                    finally:
                        if client and client.is_connected():
                            await client.disconnect()

                    # Удаляем запись из базы
                    await session.delete(account)
                    await session.commit()
                    app_logger.info(f"Аккаунт {phone} удален из базы")
                    return True
            except Exception as e:
                app_logger.error(f"Ошибка удаления аккаунта: {str(e)}")

            return False

    async def clear_session_cache(self):
        now = datetime.now()
        expired_sessions = [
            session for session, data in self.active_sessions.items()
            if (now - data['timestamp']).seconds > 1800
        ]
        for session in expired_sessions:
            del self.active_sessions[session]
        app_logger.info(f"Очищено {len(expired_sessions)} устаревших сессий")


class UserActivityManager:
    def __init__(self):
        self.user_tasks: Dict[int, asyncio.Task] = {}
        self.account_tasks: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def start_user_activity(self, user_id: int, service: AccountService):
        user = await get_user_by_user_id(user_id)
        async with self.lock:
            if user_id not in self.user_tasks:
                self.user_tasks[user_id] = asyncio.create_task(
                    self._user_monitor_loop(user_id, service)
                )
                app_logger.info(f"Запущена проверка активности для пользователя {user.full_name}")

    async def stop_user_activity(self, user_id: int):
        user = await get_user_by_user_id(user_id)
        async with self.lock:
            task = self.user_tasks.get(user_id)
            if task:
                task.cancel()
                del self.user_tasks[user_id]
                app_logger.info(f"Остановлена проверка активности для пользователя {user.full_name}")

    async def stop_account_activity(self, phone: str):
        async with self.lock:
            task = self.account_tasks.get(phone)
            if task and not task.done():
                task.cancel()
                del self.account_tasks[phone]
                app_logger.info(f"Остановлена активность для аккаунта {phone}")

    async def _user_monitor_loop(self, user_id: int, service: AccountService):
        app_logger.info(f"Запуск мониторинга активности для пользователя {user_id}")
        # Получаем объект текущего юзера по user_id из модели user
        user = await get_user_by_user_id(user_id)

        while True:
            try:
                accounts = await service.get_user_accounts(user_id)
                await self._manage_account_tasks(accounts, service)
                await asyncio.sleep(60)
                app_logger.debug(f"Проверка состояния для пользователя {user.full_name}")
            except asyncio.CancelledError:
                app_logger.warning(f"Мониторинг активности для пользователя {user.full_name} прерван")
                break
            except Exception as e:
                app_logger.error(f"Ошибка мониторинга: {str(e)}")
                await asyncio.sleep(60)

    async def _manage_account_tasks(self, accounts: List[Account], service: AccountService):
        current_phones = {acc.phone for acc in accounts if acc.is_active}
        existing_phones = set(self.account_tasks.keys())

        # Запуск новых задач
        for phone in current_phones - existing_phones:
            account = next(acc for acc in accounts if acc.phone == phone)
            self.account_tasks[phone] = asyncio.create_task(
                self._account_activity_loop(account, service)
            )
            app_logger.info(f"Запущена активность для аккаунта {phone}")

        # Остановка удаленных задач
        for phone in existing_phones - current_phones:
            self.account_tasks[phone].cancel()
            del self.account_tasks[phone]
            app_logger.info(f"Остановлена активность для аккаунта {phone}")

    async def _account_activity_loop(self, account: Account, service: AccountService):
        app_logger.info(f"Запуск цикла активности для {account.phone}")
        while True:
            try:
                await self._perform_activity(account, service)
                interval = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
                app_logger.info(f"Следующая проверка для {account.phone} через {interval} сек")
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                app_logger.warning(f"Цикл активности для {account.phone} прерван")
                break
            except Exception as e:
                app_logger.error(f"Ошибка в цикле активности: {str(e)}")
                await asyncio.sleep(60)

    async def _perform_activity(self, account: Account, service: AccountService):
        client = None
        session_str = None
        try:
            session_str = await service.decrypt_session(account.session_data)
            app_logger.debug(f"Выполнение активности для {account.phone}")

            # Проверка валидности сессии перед использованием
            if not await service.validate_session(session_str):
                app_logger.warning(f"Сессия {account.phone} невалидна, удаляем...")
                await service.delete_account(account.phone)
                await self._notify_user(account.user_id,
                                        f"Сессия {account.phone} устарела. "
                                        f"Пожалуйста, добавьте аккаунт заново.")
                return

            # Используем кэшированную сессию
            if session_str not in service.active_sessions:
                app_logger.debug(f"Создаем новое подключение для {account.phone}")
                client = await service._create_client(session_str)
                service.active_sessions[session_str] = {"client": client, "timestamp": datetime.now()}
            else:
                client = service.active_sessions[session_str]["client"]

            if not client.is_connected():
                await client.connect()

            # Дополнительная проверка авторизации
            if not await client.is_user_authorized():
                raise ConnectionError("Сессия не авторизована")

            me = await client.get_me()
            if isinstance(me, TelegramUser):
                await service.update_last_active(account.phone)
                app_logger.info(f"Успешная активность для {account.phone}")

        except (SessionExpiredError, ConnectionError, ValueError) as e:
            app_logger.error(f"Критическая ошибка сессии {account.phone}: {str(e)}")
            await self._handle_invalid_session(service, account.phone, session_str, account.user_id)

        except Exception as e:
            app_logger.error(f"Ошибка активности для {account.phone}: {str(e)}")
            app_logger.debug(f"Трассировка:\n{traceback.format_exc()}")
            # Удаляем сессию из кэша при любой ошибке
            if session_str and session_str in service.active_sessions:
                del service.active_sessions[session_str]
        finally:
            if client and client.is_connected():
                await client.disconnect()


    async def _handle_invalid_session(self, service: AccountService, phone: str, session_str: str, user_id: int):
        """Обработка невалидной сессии"""
        if session_str and session_str in service.active_sessions:
            del service.active_sessions[session_str]

        if await service.delete_account(phone):
            await self._notify_user(user_id,
                                    f"⚠️ Сессия {phone} была автоматически удалена из-за ошибки авторизации. "
                                    f"Пожалуйста, добавьте аккаунт заново.")
        else:
            app_logger.error(f"Не удалось удалить аккаунт {phone}")

    async def _notify_user(self, user_id: int, message: str):
        """Отправка уведомления пользователю"""
        try:
            await bot.send_message(user_id, message)
            app_logger.info(f"Уведомление отправлено пользователю {user_id}")
        except Exception as e:
            app_logger.error(f"Ошибка отправки уведомления: {str(e)}")
