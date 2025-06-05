from typing import Dict, List
from sqlalchemy import select, and_
from cryptography.fernet import Fernet
import asyncio
import random
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionExpiredError, SessionPasswordNeededError, AuthKeyError, FloodWaitError, RPCError
from telethon.sessions import StringSession
from config_data.config import CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX, API_ID, API_HASH
from database.models import Account, AccountReaction, User, async_session
from telethon.tl.types import User as TelegramUser
from telethon.network import ConnectionTcpAbridged
from telethon.tl.functions.messages import SendReactionRequest, GetMessagesViewsRequest
from telethon.tl.types import ReactionEmoji
from telethon import functions

from database.query_orm import get_user_by_user_id, get_account_by_phone
from loader import app_logger, bot
from services.channel_manager import ChannelManager

from sqlalchemy.exc import OperationalError, TimeoutError

# Добавляем функцию для безопасного выполнения транзакций с повторными попытками
async def execute_with_retry(async_func, *args, max_retries=5, retry_delay=1, **kwargs):
    """
    Выполняет асинхронную функцию с механизмом повторных попыток при ошибках базы данных.
    
    Args:
        async_func: Асинхронная функция для выполнения
        max_retries: Максимальное количество повторных попыток
        retry_delay: Начальная задержка между попытками (увеличивается экспоненциально)
        *args, **kwargs: Аргументы для передачи в async_func
        
    Returns:
        Результат выполнения async_func или None в случае неудачи
    """
    retries = 0
    while retries < max_retries:
        try:
            return await async_func(*args, **kwargs)
        except (OperationalError, TimeoutError) as e:
            retries += 1
            if "database is locked" in str(e) or "connection timed out" in str(e):
                wait_time = retry_delay * (2 ** retries)  # Экспоненциальная задержка
                app_logger.warning(f"База данных заблокирована или таймаут соединения. Повторная попытка {retries}/{max_retries} через {wait_time} сек...")
                await asyncio.sleep(wait_time)
                continue
            elif retries >= max_retries:
                app_logger.error(f"Достигнут лимит повторных попыток ({max_retries}). Последняя ошибка: {e}")
                return None
            else:
                raise
        except Exception as e:
            app_logger.error(f"Неожиданная ошибка при выполнении транзакции: {e}")
            raise

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
                    account.last_activity = datetime.now()
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

        client = TelegramClient(
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
        try:
            await client.connect()
        except RPCError as e:
            # сессия вовсе не может подключиться
            app_logger.error(f"Невозможно подключиться с аккаунтом {account.phone}: {e}")
            await self._handle_invalid_session(service, account.phone, account.user_id)
            return

        # проверяем, авторизованы ли мы
        if not await client.is_user_authorized():
            # файл сессии пустой или невалидный
            await self._handle_invalid_session(service, account.phone, account.user_id)
            await client.disconnect()
            return
        try:
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
            app_logger.info(f"Запуск цикла активности для {account.phone}")

            # Обновляем сообщение в избранном
            current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            if messages and messages[0].text and "Аккаунт был активен" in messages[0].text:
                await client.edit_message("me", messages[0].id, f"🔄 Аккаунт был активен: {current_time}")
            else:
                await client.send_message("me", f"🔄 Аккаунт был активен: {current_time}")

            # Получаем каналы пользователя с механизмом повторных попыток
            async with async_session() as session:
                
                    channel_manager = ChannelManager(session)
                    user = await execute_with_retry(get_user_by_user_id, str(account.user_id))
                    try: 
                        if not user:
                            app_logger.error(f"Не удалось получить пользователя {account.user_id}")
                            return
                            
                        channels = await execute_with_retry(channel_manager.get_user_channels, user.id)
                        
                        if channels is None:
                            app_logger.error(f"Не удалось получить каналы пользователя {user.username}")
                            return
                        
                        app_logger.debug(f"Найдено {len(channels)} каналов для пользователя {user.username}")

                        for channel in channels:
                            app_logger.info(f"Проверка канала {channel.channel_title}")
                            if not channel.is_active:
                                continue
                            try:
                                # Получаем список доступных реакций с повторными попытками
                                reaction_result = await execute_with_retry(
                                    channel_manager.get_channel_reactions,
                                    channel.id
                                )
                                available_reactions, user_reactions = reaction_result
                            except Exception:
                                available_reactions, user_reactions = [], []
                            
                            # Используем пользовательские реакции, если они установлены, иначе доступные
                            reactions_to_use = user_reactions if user_reactions else available_reactions
                            
                            # Если нет реакций, пропускаем канал
                            if not reactions_to_use:
                                app_logger.warning(f"Нет доступных реакций для канала {channel.channel_title}")
                                continue
                            
                            # Получаем канал из Telegram
                            # Извлекаем ID канала без префикса -100
                            orig_channel_id = channel.channel_id
                            if str(orig_channel_id).startswith('-100'):
                                channel_id = int(str(abs(orig_channel_id))[3:])
                            else:
                                channel_id = abs(orig_channel_id)
                            
                            # Проверяем новые посты для этого аккаунта
                            new_posts = await channel_manager.check_new_posts(channel, client, account.id)
                            
                            if new_posts:
                                app_logger.info(f"Найдено {len(new_posts)} новых постов в канале {channel.channel_title}")
                                
                                for post_id in new_posts:
                                    # Проверяем, не помечен ли уже этот пост как имеющий максимум реакций
                                    max_reactions_query = select(AccountReaction).where(
                                        AccountReaction.channel_id == channel.id,
                                        AccountReaction.post_id == post_id,
                                        AccountReaction.reaction == "__max_reactions__"
                                    )
                                    max_reactions_result = await session.execute(max_reactions_query)
                                    max_reactions_record = max_reactions_result.scalar_one_or_none()
                                    
                                    if max_reactions_record:
                                        app_logger.debug(f"Пост {post_id} в канале {channel.channel_title} уже помечен как имеющий максимум реакций. Пропускаем.")
                                        continue
                                    
                                    try:
                                        # Сначала проверяем, существует ли сообщение
                                        msg = await client.get_messages(
                                            entity=channel.channel_id,
                                            ids=post_id
                                        )
                                        
                                        if not msg or not isinstance(msg, list) and not msg:
                                            app_logger.warning(f"Сообщение {post_id} не найдено в канале {channel.channel_title}")
                                            continue
                                        
                                        # Если сообщение - список, берем первый элемент
                                        if isinstance(msg, list):
                                            if not msg:  # Если список пустой
                                                app_logger.warning(f"Сообщение {post_id} не найдено в канале {channel.channel_title}")
                                                continue
                                            msg = msg[0]
                                        
                                        # Проверяем, сколько просмотров у поста
                                        try:
                                            views_resp = await client(GetMessagesViewsRequest(
                                                peer=channel.channel_id,
                                                id=[post_id],
                                                increment=False
                                            ))
                                            views_count = views_resp.views[0].views or 0
                                            
                                            # Инкрементируем счетчик просмотров, если нужно
                                            if int(views_count) < channel.views:
                                                await client(GetMessagesViewsRequest(
                                                    peer=channel.channel_id,
                                                    id=[post_id],
                                                    increment=True
                                                ))
                                        except Exception as e:
                                            app_logger.error(f"Ошибка при получении/установке просмотров для поста {post_id}: {e}")
                                        
                                        # Проверяем текущее количество реакций на посте
                                        current_reactions_count = 0
                                        if msg.reactions:
                                            current_reactions_count = sum(r.count for r in msg.reactions.results)
                    
                                        # Проверяем, не превышен ли максимум реакций
                                        if current_reactions_count >= channel.max_reactions:
                                            app_logger.warning(
                                                f"Пост {post_id} в канале {channel.channel_title} уже имеет {current_reactions_count} "
                                                f"реакций (максимум: {channel.max_reactions})"
                                            )
                                            
                                            # Добавляем запись, что этот пост уже проверен и имеет максимум реакций
                                            # чтобы больше не проверять его в будущем
                                            max_reaction_record = AccountReaction(
                                                account_id=account.id,
                                                channel_id=channel.id,
                                                post_id=post_id,
                                                reaction="__max_reactions__"  # Специальный маркер для постов с максимумом реакций
                                            )
                                            session.add(max_reaction_record)
                                            
                                            await session.commit()
                                            continue
                                        
                                        # Проверяем, не выставлял ли уже этот аккаунт реакцию на этот пост
                                        query = select(AccountReaction).where(
                                            AccountReaction.account_id == account.id,
                                            AccountReaction.channel_id == channel.id,
                                            AccountReaction.post_id == post_id
                                        )
                                        result = await session.execute(query)
                                        existing_reaction = result.scalar_one_or_none()
                                        
                                        if existing_reaction:
                                            app_logger.debug(
                                                f"Аккаунт {account.phone} уже ставил реакцию на пост {post_id} в канале {channel.channel_title}"
                                            )
                                            continue
                                        
                                        # Выбираем случайную реакцию из доступных
                                        reaction_emoji = random.choice(reactions_to_use)
                                        
                                        try:
                                            # Получаем entity канала
                                            try:
                                                channel_entity = await client.get_entity(channel.channel_id)
                                            except Exception as e:
                                                app_logger.error(f"Не удалось получить entity канала {channel.channel_title}: {e}")
                                                continue
                                                
                                            # Устанавливаем реакцию
                                            try:
                                                await client(SendReactionRequest(
                                                    peer=channel.channel_id,
                                                    msg_id=post_id,
                                                    reaction=[ReactionEmoji(emoticon=reaction_emoji)]
                                                ))
                                                
                                                # Записываем информацию о выставленной реакции
                                                reaction_record = AccountReaction(
                                                    account_id=account.id,
                                                    channel_id=channel.id,
                                                    post_id=post_id,
                                                    reaction=reaction_emoji
                                                )
                                                session.add(reaction_record)
                                                await session.commit()
                                                
                                                app_logger.debug(
                                                    f"Установлена реакция {reaction_emoji} на пост {post_id} в канале {channel.channel_title}"
                                                )
                                                
                                                # Небольшая задержка между реакциями для естественности
                                                await asyncio.sleep(random.uniform(1, 3))
                                            except Exception as e:
                                                # Проверяем на ошибку с reactions_uniq_max
                                                if "reactions_uniq_max" in str(e):
                                                    app_logger.warning(f"Невозможно добавить новый тип эмодзи {reaction_emoji}, достигнут лимит уникальных реакций для поста {post_id}")
                                                    
                                                    # Пробуем использовать уже существующие реакции
                                                    if msg.reactions and msg.reactions.results:
                                                        # Получаем список существующих реакций на сообщении
                                                        existing_emoji = [r.reaction.emoticon for r in msg.reactions.results if hasattr(r.reaction, 'emoticon')]
                                                        if existing_emoji:
                                                            # Используем случайную из уже существующих реакций
                                                            existing_reaction_emoji = random.choice(existing_emoji)
                                                            try:
                                                                await client(SendReactionRequest(
                                                                    peer=channel.channel_id,
                                                                    msg_id=post_id,
                                                                    reaction=[ReactionEmoji(emoticon=existing_reaction_emoji)]
                                                                ))
                                                                
                                                                # Записываем информацию о выставленной реакции
                                                                reaction_record = AccountReaction(
                                                                    account_id=account.id,
                                                                    channel_id=channel.id,
                                                                    post_id=post_id,
                                                                    reaction=existing_reaction_emoji
                                                                )
                                                                session.add(reaction_record)
                                                                await session.commit()
                                                                
                                                                app_logger.debug(
                                                                    f"Установлена существующая реакция {existing_reaction_emoji} на пост {post_id} в канале {channel.channel_title}"
                                                                )
                                                                
                                                                # Небольшая задержка между реакциями для естественности
                                                                await asyncio.sleep(random.uniform(1, 3))
                                                            except Exception as e2:
                                                                app_logger.error(f"Ошибка при установке существующей реакции {existing_reaction_emoji}: {e2}")
                                                else:
                                                    # Для других ошибок
                                                    if "message ID is invalid" in str(e):
                                                        app_logger.warning(f"Пост {post_id} в канале {channel.channel_title} недоступен или был удален")
                                                        # Добавляем запись, чтобы больше не пытаться ставить реакцию на этот пост
                                                        invalid_post_record = AccountReaction(
                                                            account_id=account.id,
                                                            channel_id=channel.id,
                                                            post_id=post_id,
                                                            reaction="__invalid_post__"  # Специальный маркер для недоступных постов
                                                        )
                                                        session.add(invalid_post_record)
                                                        await session.commit()
                                                    else:
                                                        app_logger.error(f"Ошибка при отправке реакции {reaction_emoji} на пост {post_id} в канале {channel.channel_title}: {e}")
                                        except Exception as e:
                                            app_logger.error(f"Ошибка при отправке реакции на пост {post_id} в канале {channel.channel_title}: {e}")
                                    except Exception as e:
                                        app_logger.error(f"Ошибка при обработке поста {post_id} в канале {channel.channel_title}: {e}")
                            
                            # Обновляем время последней проверки в контексте этого аккаунта
                            # но НЕ в общем, чтобы другие аккаунты тоже могли проверить посты
                            # и поставить свои реакции
                            try:
                                last_check_record = AccountReaction(
                                    account_id=account.id,
                                    channel_id=channel.id,
                                    post_id=0,  # Специальное значение для маркера последней проверки
                                    reaction="__last_checked__"  # Маркер для отслеживания последней проверки
                                )
                                session.add(last_check_record)
                                await session.commit()
                            except Exception as e:
                                app_logger.error(f"Ошибка при обновлении времени последней проверки для канала {channel.channel_title}: {e}")

                    except Exception as e:
                        app_logger.error(f"Ошибка при проверке каналов для пользователя {user.username}: {e}")

            await service.update_last_active(account.phone)

            await client(functions.account.UpdateStatusRequest(
                        offline=True
                    ))
        finally:
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
