from typing import Dict, List
from sqlalchemy import select, and_
from cryptography.fernet import Fernet
import asyncio
import random
from datetime import datetime, UTC
from telethon import TelegramClient
from telethon.errors import SessionExpiredError, SessionPasswordNeededError, AuthKeyError, FloodWaitError
from telethon.sessions import StringSession
from config_data.config import CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX, API_ID, API_HASH
from database.models import Account, User, async_session
from telethon.tl.types import User as TelegramUser
from telethon.network import ConnectionTcpAbridged
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from telethon import functions

from database.query_orm import get_user_by_user_id, get_account_by_phone
from loader import app_logger, bot
from services.channel_manager import ChannelManager


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
        """ Проверка сессии на валидность """
        client = await self._create_client(session_str)
        try:
            await client.connect()
            return await client.is_user_authorized()
        finally:
            if client.is_connected():
                await client.disconnect()


    async def create_account(self, user_id: int, phone: str, session_str: str, two_factor: str = None):
        user = await get_user_by_user_id(user_id)
        app_logger.info(f"Создание аккаунта для пользователя {user.username}, телефон: {phone}")
        async with async_session() as session:
            try:
                encrypted = await self.encrypt_session(session_str)
                encrypted_2fa = self.cipher.encrypt(two_factor.encode()).decode() if two_factor else None
                account = Account(
                    user_id=user_id,
                    phone=phone,
                    session=encrypted,
                    is_active=True,
                    password=encrypted_2fa
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
        app_logger.debug(f"Получение аккаунтов пользователя {user.username}")
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.user_id == user_id)
            )
            accounts = result.scalars().all()
            return accounts

    async def toggle_account(self, user_id: int, phone: str) -> tuple[bool, bool, bool]:
        user = await get_user_by_user_id(user_id)
        app_logger.info(f"Изменение статуса аккаунта {phone} пользователя {user.username}")
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

                if new_status is True:
                    # Если статус аккаунта изменен на "активен", запускаем активность
                    pass
                else:
                    # Если аккаунт не активен теперь, завершаем таску по мониторингу активности
                    pass

                app_logger.info(f"Статус аккаунта {phone} изменен: {'активен' if new_status else 'неактивен'}")
                return True, old_status, new_status

            except Exception as e:
                app_logger.error(f"Ошибка изменения статуса: {str(e)}")
                return False, False, False

    async def update_last_active(self, phone: str):
        """Обновляет время последней активности для аккаунта"""
        app_logger.debug(f"Обновление времени активности для {phone}")
        async with async_session() as session:
            try:
                result = await session.execute(
                    select(Account).where(Account.phone == phone)
                )
                account = result.scalar_one_or_none()
                
                if account:
                    account.last_activity = datetime.now(UTC)
                    await session.commit()
                    app_logger.info(f"Обновлено время активности для {phone}")
                else:
                    app_logger.warning(f"Аккаунт {phone} не найден при обновлении времени активности")
            except Exception as e:
                app_logger.error(f"Ошибка при обновлении времени активности для {phone}: {e}")
                await session.rollback()

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
                    session_str = await self.decrypt_session(account.session)
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

    async def get_2fa_password(self, phone: str) -> str:
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.phone == phone)
            )
            account = result.scalars().first()
            if account and account.password:
                return self.cipher.decrypt(account.password).decode()
            return None


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
                app_logger.info(f"Запущена проверка активности для пользователя {user.username or user.first_name}")

    async def stop_user_activity(self, user_id: int):
        user = await get_user_by_user_id(user_id)
        async with self.lock:
            task = self.user_tasks.get(user_id)
            if task:
                task.cancel()
                del self.user_tasks[user_id]
                app_logger.info(f"Остановлена проверка активности для пользователя {user.username}")

    async def stop_account_activity(self, phone: str):
        async with self.lock:
            task = self.account_tasks.get(phone)
            if task and not task.done():
                task.cancel()
                del self.account_tasks[phone]
                app_logger.info(f"Остановлена активность для аккаунта {phone}")

    async def start_account_activity(self, phone: str, service: AccountService):
        account = await get_account_by_phone(phone)
        if phone not in self.account_tasks or self.account_tasks[phone].done():
            self.account_tasks[phone] = asyncio.create_task(
                self._account_activity_loop(account, service)
            )
            app_logger.info(f"Запущена задача для аккаунта {phone}")


    async def _user_monitor_loop(self, user_id: int, service: AccountService):
        # Получаем объект текущего юзера по user_id из модели user
        user = await get_user_by_user_id(user_id)

        try:
            app_logger.debug(f"Проверка состояния аккаунтов для пользователя {user.username or user.first_name}")
            accounts = await service.get_user_accounts(user_id)
            await self._manage_account_tasks(accounts, service)
            # await asyncio.sleep(60)

        except asyncio.CancelledError:
            app_logger.warning(f"Мониторинг активности для пользователя {user.username} прерван")
            return None
        except Exception as e:
            app_logger.error(f"Ошибка мониторинга: {str(e)}")
            await asyncio.sleep(60)

    async def _manage_account_tasks(self, accounts: List[Account], service: AccountService):
        """Управление задачами для аккаунтов"""
        current_phones = {acc.phone for acc in accounts if acc.is_active}
        # existing_phones = set(self.account_tasks.keys())

        # Запуск новых задач
        for phone in current_phones:
            account = next(acc for acc in accounts if acc.phone == phone)
            if phone not in self.account_tasks or self.account_tasks[phone].done():
                self.account_tasks[phone] = asyncio.create_task(
                    self._account_activity_loop(account, service)
                )
                app_logger.info(f"Запущена задача для аккаунта {phone}")

        # # Остановка удаленных задач
        # for phone in existing_phones - current_phones:
        #     if phone in self.account_tasks and not self.account_tasks[phone].done():
        #         self.account_tasks[phone].cancel()
        #         del self.account_tasks[phone]
        #         app_logger.info(f"Остановлена задача для аккаунта {phone}")

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
        """Выполняет активность для аккаунта."""
        session_str = await service.decrypt_session(account.session)

        async with TelegramClient(
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
        ) as client:
            await client.connect()

            await client(functions.account.UpdateStatusRequest(
                        offline=False
                    ))

            # Читаем сообщения в избранном для обновления времени последнего захода
            messages = await client.get_messages("me", limit=1)
            if messages:
                await client.send_read_acknowledge("me", messages[0])

            # # Отправляем тестовое сообщение и удаляем его для обновления времени последнего захода
            # temp_message = await client.send_message("me", "test")
            # await client.delete_messages("me", temp_message)

            # Обновляем сообщение в избранном
            current_time = datetime.now(UTC).strftime("%d.%m.%Y %H:%M:%S")
            if messages and messages[0].text and "Аккаунт был активен" in messages[0].text:
                await client.edit_message("me", messages[0].id, f"🔄 Аккаунт был активен: {current_time}")
            else:
                await client.send_message("me", f"🔄 Аккаунт был активен: {current_time}")

            # Получаем каналы пользователя
            async with async_session() as session:
                channel_manager = ChannelManager(session)
                user = await get_user_by_user_id(str(account.user_id))
                channels = await channel_manager.get_user_channels(user.id)

                for channel in channels:
                    if not channel.is_active:
                        continue
                    try:
                        # Получаем список доступных реакций и для каждого поста выбираем рандомную
                        try:
                            available_reactions, user_reactions = await channel_manager.get_channel_reactions(
                                channel.id
                            )
                        except Exception:
                            available_reactions, user_reactions = [], []
                        user_reactions = available_reactions if user_reactions is None else user_reactions

                        # Проверяем новые посты
                        new_posts = await channel_manager.check_new_posts(channel, client)
                        if new_posts and user_reactions:
                            for post_id in new_posts:
                                msg = await client.get_messages(
                                    entity=channel.channel_id,
                                    ids=post_id
                                )

                                # Если у сообщения нет реакций, treat as 0
                                rx = 0
                                if msg.reactions:
                                    # msg.reactions.results — список объектов ReactionCount
                                    # каждый имеет .count
                                    rx = sum(r.count for r in msg.reactions.results)

                                # Пропускаем, если уже зашкаливает
                                if rx > channel.max_reactions or rx < channel.min_reactions:
                                    app_logger.warning(f"Пропустил реакцию "
                                                       f"{channel.min_reactions} < {rx} < {channel.max_reactions} "
                                                       f"на канале {channel.channel_title} "
                                                       f"для поста {post_id}")
                                    continue
                                try:
                                    await client(SendReactionRequest(
                                        peer=channel.channel_id,
                                        msg_id=post_id,
                                        reaction=[ReactionEmoji(emoticon=random.choice(user_reactions))]
                                    ))
                                    await asyncio.sleep(random.uniform(1, 3))
                                except Exception as e:
                                    app_logger.error(f"Ошибка при отправке реакции: {e}")

                        channel.last_checked = datetime.now(UTC)
                        await session.commit()

                    except Exception as e:
                        app_logger.error(f"Ошибка при проверке канала {channel.channel_id}: {e}")
                        continue

            await service.update_last_active(account.phone)
            
            await client(functions.account.UpdateStatusRequest(
                        offline=True
                    ))
            await client.disconnect()

    async def _handle_invalid_session(self, service: AccountService, phone: str, user_id: int):
        """Обработка невалидной сессии"""

        if await service.delete_account(phone):
            await self._notify_user(user_id,
                                    f"⚠️ Сессия {phone} была автоматически удалена из-за ошибки авторизации. "
                                    f"Пожалуйста, добавьте аккаунт заново.")
        else:
            app_logger.error(f"Не удалось удалить аккаунт {phone}")

    async def _notify_user(self, user_id: int, message: str):
        """Отправка уведомления пользователю"""
        try:
            user = await get_user_by_user_id(user_id)
            await bot.send_message(user_id, message)
            app_logger.info(f"Уведомление отправлено пользователю {user.username}")
        except Exception as e:
            app_logger.error(f"Ошибка отправки уведомления: {str(e)}")
