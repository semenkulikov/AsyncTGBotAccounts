import random
from datetime import datetime, timedelta, UTC
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import UserChannel, AccountReaction
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, ImportChatInviteRequest, CheckChatInviteRequest, SendReactionRequest
from telethon.tl.types import InputPeerChannel, PeerChannel, ReactionEmoji
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
from telethon.errors import (
    ChannelPrivateError,
    InviteHashEmptyError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserAlreadyParticipantError,
)
from config_data.config import API_ID, API_HASH
import asyncio
from loader import app_logger
from database.query_orm import get_user_by_user_id

# Для решения циклического импорта используем глобальную переменную
account_service = None

class ChannelManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_channels(self, user_id: int) -> List[UserChannel]:
        """Получает список каналов пользователя"""
        query = select(UserChannel).where(UserChannel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def add_channel(self, user_id: int,
                          channel_id: int,
                          username: str,
                          title: str,
                          min_reactions: int,
                          max_reactions: int,
                          available_reactions: list) -> int:
        """Добавляет новый канал для пользователя"""
        try:
            channel_id = int("-100" + str(channel_id))  # Приводим ID канала к стандартному виду
            channel = UserChannel(
                user_id=user_id,
                channel_id=channel_id,
                channel_username=username,
                channel_title=title,
                min_reactions=min_reactions,
                max_reactions=max_reactions,
                is_active=True
            )
            self.session.add(channel)
            await self.session.flush()
            
            # Создаем запись о реакциях
            reaction = AccountReaction(
                channel_id=channel.id,
                available_reactions=available_reactions,
                user_reactions=None  # Пользователь еще не выбрал свои реакции
            )
            self.session.add(reaction)
            await self.session.commit()
            return channel.id
        except Exception as e:
            await self.session.rollback()
            raise e

    async def get_channel(self, channel_id: int) -> Optional[UserChannel]:
        """ Метод для получения канала по его id """
        query = select(UserChannel).where(UserChannel.id == channel_id)
        result = await self.session.execute(query)
        channel = result.scalar_one_or_none()

        if channel:
            return channel
        return None

    async def delete_channel(self, channel_id: int) -> bool:
        """Удаляет канал"""
        try:
            query = select(UserChannel).where(UserChannel.id == channel_id)
            result = await self.session.execute(query)
            channel = result.scalar_one_or_none()
            
            if channel:
                # Удаляем все реакции канала
                await self.session.execute(
                    select(AccountReaction).where(AccountReaction.channel_id == channel_id)
                )
                await self.session.delete(channel)
                await self.session.commit()
                return True
            return False
        except Exception as e:
            await self.session.rollback()
            raise e

    async def update_channel_reaction(self, channel_id: int, user_reactions: list) -> bool:
        """Обновляет пользовательские реакции для канала"""
        try:
            reaction = await self.session.execute(
                select(AccountReaction).where(AccountReaction.channel_id == channel_id)
            )
            reaction = reaction.scalar_one_or_none()
            
            if reaction:
                reaction.user_reactions = user_reactions
                await self.session.commit()
                return True
            return False
        except Exception as e:
            await self.session.rollback()
            raise e

    async def get_channel_reactions(self, channel_id: int) -> tuple[list, list]:
        """Получает списки доступных и пользовательских реакций"""
        try:
            reaction = await self.session.execute(
                select(AccountReaction).where(AccountReaction.channel_id == channel_id)
            )
            reaction = reaction.scalar_one_or_none()
        except Exception:
            reaction = await self.session.execute(
                select(AccountReaction).where(AccountReaction.channel_id == channel_id)
            )
            reaction = reaction.scalars().first()
        if reaction:
            return reaction.available_reactions, reaction.user_reactions
        return [], None

    async def update_reactions_count(self, channel_id: int, min_reactions: int, max_reactions: int) -> bool:
        """ Метод для обновления количества реакций для канала """
        try:
            cur_channel = await self.get_channel(channel_id)
            if cur_channel:
                cur_channel.min_reactions = min_reactions
                cur_channel.max_reactions = max_reactions
                await self.session.commit()
            return True
        except Exception:
            return False

    async def update_views_count(self, channel_id: int, views_count: int) -> bool:
        """ Метод для обновления количества просмотров для канала """
        try:
            cur_channel = await self.get_channel(channel_id)
            if cur_channel:
                cur_channel.views = views_count
                await self.session.commit()
            return True
        except Exception:
            return False

    async def check_new_posts(self, channel: UserChannel, client: TelegramClient, account_id: int = None) -> list[int]:
        try:
            peer = None  # Инициализируем peer None изначально
            
            # Правильно обрабатываем ID канала
            # Telegram API ожидает ID без префикса -100
            orig_channel_id = channel.channel_id
            
            # Извлекаем только ID канала без префикса -100
            if str(orig_channel_id).startswith('-100'):
                # Берем только часть после -100
                channel_id = int(str(abs(orig_channel_id))[3:])
                app_logger.debug(f"Извлекаем ID канала: {orig_channel_id} -> {channel_id}")
            else:
                channel_id = abs(orig_channel_id)
            
            # Сначала проверяем, можно ли получить канал по username
            if channel.channel_username and channel.channel_username.strip():
                try:
                    # Если это ссылка-приглашение (начинается с +)
                    if channel.channel_username.startswith('+'):
                        invite_hash = channel.channel_username[1:]
                        try:
                            # Пытаемся присоединиться к каналу
                            app_logger.debug(f"Присоединяемся к каналу по хэшу: {invite_hash}")
                            updates = await client(ImportChatInviteRequest(invite_hash))
                            # После успешного присоединения получаем диалоги заново
                            await client.get_dialogs()
                        except UserAlreadyParticipantError:
                            app_logger.debug(f"Уже участник канала с хэшем {invite_hash}")
                        except Exception as e:
                            # Если ссылка-приглашение истекла/недействительна, деактивируем канал
                            if "expired" in str(e).lower() or "invalid" in str(e).lower():
                                app_logger.error(f"Ссылка-приглашение для канала {channel.channel_title} недействительна: {e}")
                                # Деактивируем канал
                                channel.is_active = False
                                await self.session.commit()
                                app_logger.info(f"Канал {channel.channel_title} автоматически деактивирован из-за недействительной ссылки")
                            else:
                                app_logger.error(f"Ошибка при подключении к каналу {channel.channel_title}: {e}")
                    
                    # Для публичных каналов пробуем несколько способов получения
                    try:
                        # Сначала стандартный способ
                        peer = await client.get_entity(channel.channel_username)
                        app_logger.debug(f"Канал получен по юзернейму: {channel.channel_username}")
                    except Exception as e:
                        app_logger.debug(f"Не удалось получить канал стандартным способом: {e}")
                        
                        # Пробуем через t.me/
                        try:
                            peer = await client.get_entity(f"t.me/{channel.channel_username}")
                            app_logger.debug(f"Канал получен через t.me/: {channel.channel_username}")
                        except Exception as e2:
                            app_logger.debug(f"Не удалось получить канал через t.me/: {e2}")
                            
                            # Для публичных каналов не подписываемся, так как реакции и просмотры можно ставить без подписки
                            app_logger.debug(f"Не пытаемся подписываться на публичный канал: {channel.channel_username}")
                except Exception as e:
                    app_logger.debug(f"Не удалось получить канал по юзернейму: {e}")
            
            # Если не удалось получить по юзернейму или его нет, пробуем искать в диалогах
            if not peer:
                try:
                    dialogs = await client.get_dialogs()
                    
                    for dialog in dialogs:
                        if hasattr(dialog.entity, 'id'):
                            dialog_id = dialog.entity.id
                            # Проверяем и по чистому ID и по полному ID
                            if dialog_id == channel_id or dialog_id == abs(orig_channel_id):
                                peer = dialog.entity
                                app_logger.info(f"Канал найден в диалогах: {dialog_id}")
                                break
                except Exception as e:
                    app_logger.error(f"Ошибка при поиске в диалогах: {e}")
            
            # Если не нашли канал, пробуем другие способы
            if not peer:
                try:
                    # Пробуем через PeerChannel с правильным ID
                    app_logger.debug(f"Пробуем получить через PeerChannel({channel_id})")
                    peer = await client.get_entity(PeerChannel(channel_id))
                    app_logger.info(f"Канал успешно получен через PeerChannel({channel_id})")
                except Exception as e:
                    app_logger.debug(f"Не удалось получить через PeerChannel: {e}")
                    
                    # Пробуем через t.me/c/ID
                    try:
                        app_logger.debug(f"Пробуем получить канал по ссылке t.me/c/{channel_id}")
                        peer = await client.get_entity(f"t.me/c/{channel_id}")
                        app_logger.info(f"Канал получен через t.me/c/{channel_id}")
                    except Exception as e:
                        app_logger.debug(f"Не удалось получить канал через t.me/c/: {e}")
                        
                        # Попытка получить через GetFullChannelRequest
                        try:
                            app_logger.debug(f"Пробуем получить через GetFullChannelRequest({channel_id})")
                            result = await client(GetFullChannelRequest(channel=PeerChannel(channel_id=channel_id)))
                            if result and result.chats:
                                peer = result.chats[0]
                                app_logger.info(f"Канал получен через GetFullChannelRequest: {channel_id}")
                        except Exception as e:
                            app_logger.debug(f"Не удалось получить через GetFullChannelRequest: {e}")
            
            # Если все попытки не удались, выходим и деактивируем канал
            if not peer:
                app_logger.warning(f"Не удалось найти канал {orig_channel_id}")
                # Если не удалось найти канал после всех попыток, деактивируем его
                channel.is_active = False
                await self.session.commit()
                app_logger.info(f"Канал {channel.channel_title} автоматически деактивирован, так как не удалось его найти")
                return []
            
            # Получаем сообщения
            app_logger.debug(f"Получаем сообщения из канала {orig_channel_id}")
            messages = await client.get_messages(peer, limit=20)  # Увеличиваем лимит сообщений
            
            # Получаем время последней проверки канала
            check_time = channel.last_checked.replace(tzinfo=UTC)
            
            # Проверяем новые сообщения
            new_post_ids = []
            
            # Также проверяем, не ставил ли этот аккаунт реакцию на этот пост ранее
            for message in messages:
                # Добавляем часовой пояс UTC к message.date
                message_date = message.date.replace(tzinfo=UTC)
                
                # Сообщение новее времени последней проверки
                if message_date > check_time:
                    # Если указан ID аккаунта, проверяем, не ставил ли этот аккаунт уже реакцию
                    if account_id:
                        # Проверяем, ставил ли этот аккаунт реакцию на этот пост
                        query = select(AccountReaction).where(
                            AccountReaction.account_id == account_id,
                            AccountReaction.channel_id == channel.id,
                            AccountReaction.post_id == message.id
                        )
                        result = await self.session.execute(query)
                        existing_reaction = result.scalar_one_or_none()
                        
                        # Также проверяем, не достигнут ли максимум реакций для этого поста
                        max_reactions_query = select(AccountReaction).where(
                            AccountReaction.channel_id == channel.id,
                            AccountReaction.post_id == message.id,
                            AccountReaction.reaction == "__max_reactions__"
                        )
                        max_reactions_result = await self.session.execute(max_reactions_query)
                        max_reactions_record = max_reactions_result.scalar_one_or_none()
                        
                        # Если реакции от этого аккаунта еще нет и пост не имеет макс. количество реакций
                        if not existing_reaction and not max_reactions_record:
                            new_post_ids.append(message.id)
                    else:
                        # Если ID аккаунта не указан, просто добавляем пост
                        new_post_ids.append(message.id)
            
            # Обновляем время последней проверки только для самого канала,
            # реакции от разных аккаунтов будем отслеживать отдельно
            if not account_id:  # Обновляем только если это общая проверка, а не для конкретного аккаунта
                channel.last_checked = datetime.now(UTC)
                await self.session.commit()
            
            if new_post_ids:  # Логируем только если есть новые сообщения
                app_logger.info(f"Найдено {len(new_post_ids)} новых сообщений в канале {channel.channel_title}")
            return new_post_ids
        except Exception as e:
            app_logger.error(f"Ошибка при проверке постов канала {channel.channel_title}: {e}")
            # Если канал деактивирован или недоступен, не нужно пытаться работать с ним
            if not channel.is_active:
                return []
            try:
                # Обновляем время последней проверки даже при ошибке
                channel.last_checked = datetime.now(UTC)
                await self.session.commit()
            except Exception as commit_error:
                app_logger.error(f"Ошибка при обновлении времени проверки: {commit_error}")
            return []

    async def set_reaction(self, client: TelegramClient, channel_id: int, post_id: int, reaction: str) -> bool:
        """
        Устанавливает реакцию на пост в канале.
        
        Args:
            client: Telethon клиент
            channel_id: ID канала (может быть с префиксом -100)
            post_id: ID поста
            reaction: Эмодзи реакции
            
        Returns:
            bool: Успешно ли установлена реакция
        """
        try:
            # Сначала проверяем, существует ли сообщение
            try:
                msg = await client.get_messages(
                    entity=channel_id,
                    ids=post_id
                )
                
                if not msg or not isinstance(msg, list) and not msg:
                    app_logger.warning(f"Сообщение {post_id} не найдено в канале {channel_id}")
                    return False
                
                if isinstance(msg, list):
                    if not msg:
                        app_logger.warning(f"Сообщение {post_id} не найдено в канале {channel_id}")
                        return False
                    msg = msg[0]
            except Exception as e:
                app_logger.error(f"Ошибка при проверке существования сообщения {post_id} в канале {channel_id}: {e}")
                return False
                
            try:
                await client(SendReactionRequest(
                    peer=channel_id,
                    msg_id=post_id,
                    reaction=[ReactionEmoji(emoticon=reaction)]
                ))
                
                app_logger.debug(f"Установлена реакция {reaction} на пост {post_id} в канале {channel_id}")
                return True
            except Exception as e:
                # Проверяем на ошибку с reactions_uniq_max
                if "reactions_uniq_max" in str(e):
                    app_logger.warning(f"Невозможно добавить новый тип эмодзи, достигнут лимит уникальных реакций для поста {post_id}")
                    # Пост уже имеет максимальное количество различных типов реакций
                    # Возвращаем True, чтобы не считать это ошибкой
                    return True
                else:
                    app_logger.error(f"Ошибка при установке реакции: {e}")
                    return False
        except Exception as e:
            app_logger.error(f"Ошибка при установке реакции {reaction} на пост {post_id} в канале {channel_id}: {e}")
            return False

    async def process_channel_posts(self, channel: UserChannel, accounts: list) -> None:
        # Проверяем, активен ли канал перед обработкой
        if not channel.is_active:
            app_logger.debug(f"Канал {channel.channel_title} неактивен, пропускаем его")
            return
            
        # Проверяем существование канала в Telegram, прежде чем обрабатывать
        try:
            # Используем первый активный аккаунт для проверки
            for account in accounts:
                if account.is_active:
                    global account_service
                    if account_service:
                        try:
                            session_str = await account_service.decrypt_session(account.session)
                            async with TelegramClient(
                                f'temp_session_{channel.id}',
                                API_ID,
                                API_HASH
                            ) as test_client:
                                try:
                                    # Пытаемся получить информацию о канале
                                    if str(channel.channel_id).startswith('-100'):
                                        channel_id = int(str(abs(channel.channel_id))[3:])
                                    else:
                                        channel_id = abs(channel.channel_id)
                                        
                                    try:
                                        entity = await test_client.get_entity(channel.channel_username or channel_id)
                                        # Если удалось получить сущность, канал существует
                                        break
                                    except Exception as e:
                                        # Проверяем, является ли ошибка признаком удаленного/недоступного канала
                                        if "not found" in str(e).lower() or "private" in str(e).lower() or "access" in str(e).lower():
                                            app_logger.warning(f"Канал {channel.channel_title} недоступен: {e}")
                                            # Деактивируем канал, если он недоступен
                                            channel.is_active = False
                                            await self.session.commit()
                                            app_logger.info(f"Канал {channel.channel_title} автоматически деактивирован из-за недоступности")
                                            return
                                except Exception as e:
                                    app_logger.debug(f"Ошибка при проверке канала с аккаунтом {account.phone}: {e}")
                        except Exception as e:
                            app_logger.debug(f"Ошибка при расшифровке сессии аккаунта {account.phone}: {e}")
            
        except Exception as e:
            app_logger.error(f"Ошибка при проверке доступности канала {channel.channel_title}: {e}")
            return
            
        # Получаем доступные реакции канала
        available_reactions, user_reactions = await self.get_channel_reactions(channel.id)
        
        # Если пользователь выбрал свои реакции, используем их, иначе доступные
        reactions_to_use = user_reactions if user_reactions else available_reactions
        
        if not reactions_to_use:
            app_logger.warning(f"Нет доступных реакций для канала {channel.id}")
            return
            
        # Перемешиваем список аккаунтов для более случайного распределения реакций
        shuffled_accounts = list(accounts)
        random.shuffle(shuffled_accounts)
        
        # Счетчик для контроля числа реакций для всех постов
        post_reaction_counts = {}
        
        # Проходим по всем активным аккаунтам
        for account in shuffled_accounts:
            if not account.is_active:
                continue
                
            async with TelegramClient(
                f'sessions/{account.phone}',
                API_ID,
                API_HASH
            ) as client:
                try:
                    # Получаем новые посты, учитывая, что данный аккаунт еще не ставил на них реакции
                    new_posts = await self.check_new_posts(channel, client, account.id)
                    
                    # Если нет новых постов - пропускаем
                    if not new_posts:
                        continue
                    
                    # Для каждого нового поста
                    for post_id in new_posts:
                        # Получаем правильный ID канала без префикса -100
                        orig_channel_id = channel.channel_id
                        if str(orig_channel_id).startswith('-100'):
                            channel_id = int(str(abs(orig_channel_id))[3:])
                        else:
                            channel_id = abs(orig_channel_id)
                            
                        # Инициализируем счетчик для данного поста, если его еще нет
                        if post_id not in post_reaction_counts:
                            # Проверяем текущее количество реакций для этого поста
                            query = select(AccountReaction).where(
                                AccountReaction.channel_id == channel.id,
                                AccountReaction.post_id == post_id
                            )
                            result = await self.session.execute(query)
                            existing_reactions = result.scalars().all()
                            post_reaction_counts[post_id] = len(existing_reactions)
                            
                        # Проверяем, не превышено ли максимальное количество реакций
                        if post_reaction_counts[post_id] >= channel.max_reactions:
                            app_logger.info(f"Достигнут лимит реакций ({channel.max_reactions}) для поста {post_id}")
                            continue
                            
                        # Выбираем случайную реакцию
                        cur_reaction = random.choice(reactions_to_use)
                        
                        try:
                            # Получаем entity канала
                            channel_entity = await client.get_entity(PeerChannel(channel_id))
                            
                            # Отправляем реакцию
                            await client(SendReactionRequest(
                                peer=channel_entity,
                                msg_id=post_id,
                                reaction=[ReactionEmoji(emoticon=cur_reaction)]
                            ))
                            
                            app_logger.info(f"Установлена реакция {cur_reaction} на пост {post_id} в канале {orig_channel_id} (аккаунт {account.phone})")
                            
                            # Сохраняем информацию о реакции
                            reaction = AccountReaction(
                                account_id=account.id,
                                channel_id=channel.id,
                                post_id=post_id,
                                reaction=cur_reaction
                            )
                            self.session.add(reaction)
                            await self.session.commit()
                            
                            # Увеличиваем счетчик реакций для этого поста
                            post_reaction_counts[post_id] += 1
                            
                        except Exception as e:
                            app_logger.error(f"Ошибка при установке реакции: {e}")
                            
                        # Задержка между реакциями
                        await asyncio.sleep(5)
                except Exception as e:
                    app_logger.error(f"Ошибка обработки канала {channel.id}: {e}")
                    continue

    async def search_channels(self, query: str) -> List[UserChannel]:
        """Ищет каналы по названию или юзернейму"""
        try:
            # Используем LIKE для поиска по подстроке
            search_query = f"%{query}%"
            result = await self.session.execute(
                select(UserChannel).where(
                    UserChannel.channel_title.like(search_query) | 
                    UserChannel.channel_username.like(search_query)
                )
            )
            return result.scalars().all()
        except Exception as e:
            app_logger.error(f"Ошибка при поиске каналов: {e}")
            return [] 