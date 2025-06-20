from aiogram import types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.orm import orm_insert_sentinel

from config_data.config import API_HASH, API_ID
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
from telethon.tl.types import ReactionEmoji, ChatInviteAlready
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpAbridged
from services.services import service

from database.models import UserChannel, async_session
from database.query_orm import get_user_by_user_id, get_accounts_count_by_user
from keyboards.inline.channels import (
    get_channels_keyboard,
    get_channel_actions_keyboard,
    get_reactions_keyboard
)
from loader import bot, dp, app_logger
from services.channel_manager import ChannelManager
from states.states import ChannelStates
from services.account_manager import AccountService
import asyncio


@dp.message(Command("my_channels"))
async def channels_handler(message: types.Message):
    """Показывает главное меню управления каналами"""
    await message.answer(
        "Панель управления каналами",
        reply_markup=get_channels_keyboard()
    )


@dp.callback_query(F.data == "my_channels")
async def my_channels_callback(callback: CallbackQuery):
    """Показывает список каналов пользователя"""
    try:
        async with async_session() as session:
            user = await get_user_by_user_id(str(callback.from_user.id))
            channel_manager = ChannelManager(session)
            channels = await channel_manager.get_user_channels(user.id)

            if not channels:
                await callback.message.edit_text(
                    "У вас пока нет добавленных каналов",
                    reply_markup=get_channels_keyboard()
                )
                return

            await callback.message.edit_text(
                await _get_channel_text(channels[0], channel_manager),
                reply_markup=get_channel_actions_keyboard(channels[0].id, 0, len(channels))
            )
    except Exception as e:
        app_logger.error(f"Ошибка в my_channels_callback: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")


@dp.callback_query(F.data.startswith("prev_channel_") | F.data.startswith("next_channel_"))
async def navigate_channel(callback: CallbackQuery):
    """Обрабатывает навигацию между каналами"""
    try:
        async with async_session() as session:
            user = await get_user_by_user_id(str(callback.from_user.id))
            channel_manager = ChannelManager(session)
            channels = await channel_manager.get_user_channels(user.id)
            
            if not channels:
                await callback.answer("Каналы не найдены")
                return

            current_channel_id = int(callback.data.split("_")[-1])
            current_index = next((i for i, c in enumerate(channels) if c.id == current_channel_id), 0)
            
            if callback.data.startswith("prev_channel_"):
                new_index = current_index - 1
            else:
                new_index = current_index + 1

            if 0 <= new_index < len(channels):
                channel = channels[new_index]
                await callback.message.edit_text(
                    await _get_channel_text(channel, channel_manager),
                    reply_markup=get_channel_actions_keyboard(channel.id, new_index, len(channels))
                )
            else:
                await callback.answer("Достигнут конец списка")
    except Exception as e:
        app_logger.error(f"Ошибка в navigate_channel: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")


async def _get_channel_text(channel: UserChannel, channel_manager: ChannelManager) -> str:
    """Формирует текст для отображения канала"""
    text = f"📢 {channel.channel_title}\n"
    text += f"Статус: {'активен' if channel.is_active else 'неактивен'}\n"
    text += f"Минимальное количество реакций на пост: {channel.min_reactions}\n"
    text += f"Максимальное количество реакций на пост: {channel.max_reactions}\n"
    text += f"Количество просмотров на пост: {channel.views}\n"
    
    # Получаем текущие реакции
    try:
        available_reactions, user_reactions = await channel_manager.get_channel_reactions(channel.id)
    except TelegramBadRequest:
        available_reactions, user_reactions = [], []
    user_reactions = available_reactions if user_reactions is None else user_reactions
    reactions_text = " ".join(user_reactions) if user_reactions else "не выбраны"
    text += f"Реакции: {reactions_text}\n"
        
    return text


@dp.callback_query(F.data == "add_channel")
async def add_channel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Отправьте ссылку на канал или его username"
    )
    await state.set_state(ChannelStates.waiting_for_channel)
    await callback.answer()


@dp.message(ChannelStates.waiting_for_channel)
async def process_channel(message: types.Message, state: FSMContext):
    """Обрабатывает добавление канала"""
    try:
        channel_link = message.text.strip()
        if not channel_link.startswith('@') and not channel_link.startswith('https://t.me/'):
            await message.answer("Пожалуйста, отправьте корректную ссылку на канал")
            await state.clear()
            return

        async with async_session() as session:
            channel_manager = ChannelManager(session)
            user = await get_user_by_user_id(str(message.from_user.id))
            
            # Получаем активные аккаунты пользователя
            accounts = await service.get_user_accounts(message.from_user.id)
            channels = await channel_manager.get_user_channels(user.id)
            user_channels = [channel.channel_title
                             for channel in channels]
            
            if not accounts:
                await message.answer(
                    "У вас нет активных аккаунтов. Добавьте аккаунт через /add_account",
                    reply_markup=get_channels_keyboard()
                )
                await state.clear()
                return
                
            # Берем все аккаунты пользователя и присоединяемся к каналу
            for account in accounts:
                
                if channel_link.startswith('@'):
                    channel_username = channel_link[1:]
                else:
                    channel_username = channel_link.split('/')[-1]

                # Получаем информацию о канале через Telethon используя аккаунт пользователя
                try:
                    session_str = await service.decrypt_session(account.session)
                    
                    # Создаем новый event loop для Telethon
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
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
                        auto_reconnect=False,
                        loop=loop
                    )
                    
                    await client.connect()
                    
                    try:
                        # Обработка открытых и закрытых каналов
                        if "+" in channel_username:
                            invite = await client(CheckChatInviteRequest(channel_username[1:]))

                            if isinstance(invite, ChatInviteAlready):
                                # Аккаунт уже в канале, получаем полные данные
                                channel = await client.get_entity(invite.chat.id)
                                full_channel = await client(GetFullChannelRequest(channel))
                            else:
                                # Присоединяемся к каналу
                                try:
                                    # Пытаемся присоединиться к каналу
                                    result = await client(ImportChatInviteRequest(channel_username[1:]))
                                    if hasattr(result, 'chats') and result.chats:
                                        channel = result.chats[0]
                                        full_channel = await client(GetFullChannelRequest(channel))
                                        
                                        # Подписываемся на канал и отключаем уведомления
                                        try:
                                            await client(JoinChannelRequest(channel))
                                            app_logger.info(f"Успешно подписались на канал {channel.title} с аккаунта {account.phone}")
                                            
                                            # Полностью отключаем уведомления
                                            from telethon.tl.functions.account import UpdateNotifySettingsRequest
                                            from telethon.tl.types import InputPeerNotifySettings, InputNotifyPeer
                                            
                                            # Создаем настройки с полностью выключенными уведомлениями
                                            settings = InputPeerNotifySettings(
                                                show_previews=False,
                                                silent=True,
                                                mute_until=2147483647,  # Максимальное значение времени
                                                sound=None              # Отключаем звук
                                            )
                                            
                                            # Применяем настройки к каналу
                                            await client(UpdateNotifySettingsRequest(
                                                peer=InputNotifyPeer(peer=channel),
                                                settings=settings
                                            ))
                                            
                                            app_logger.info(f"Успешно отключили уведомления для канала {channel.title} с аккаунта {account.phone}")
                                        except Exception as e:
                                            app_logger.error(f"Ошибка при подписке на канал или отключении уведомлений: {e} с аккаунта {account.phone}")
                                    else:
                                        await message.answer(f"Не удалось присоединиться к закрытому каналу с аккаунта {account.phone}!")
                                        return
                                except Exception as e:
                                    app_logger.error(f"Ошибка при присоединении к закрытому каналу: {e} с аккаунта {account.phone}")
                                    await message.answer(f"Ошибка при присоединении к закрытому каналу с аккаунта {account.phone}!")
                                    return
                        else:  # Если канал публичный - не присоединяемся к каналу
                            channel = await client.get_entity(channel_username)
                            full_channel = await client(GetFullChannelRequest(channel))
                            
                            # Не подписываемся на публичные каналы, так как они доступны и без подписки
                            app_logger.info(f"Публичный канал {channel.title} добавлен без подписки (аккаунт {account.phone})")

                        # Обработка ситуации уже добавленного канала
                        if channel.title in user_channels:
                            await message.answer(f"Канал {channel.title} уже добавлен!")
                            return

                        available_reactions = []
                        
                        if hasattr(full_channel.full_chat.available_reactions, 'reactions'):
                            reactions = full_channel.full_chat.available_reactions.reactions
                            if isinstance(reactions, list):
                                # Преобразуем ReactionEmoji в строки
                                available_reactions = []
                                for r in reactions:
                                    if isinstance(r, ReactionEmoji):
                                        available_reactions.append(str(r.emoticon))
                        else:
                            default_reactions = ["👍", "❤", "👏", "🎉", "🤩", "👌", "😍",
                                                "❤", "💯", "🤣", "⚡", "🏆", "🤝", "✍"]
                            available_reactions = default_reactions
                    finally:
                        await client.disconnect()
                        loop.close()
                
                except Exception as e:
                    app_logger.error(f"Ошибка получения информации о канале: {e}")
                    await message.answer(
                        "Не удалось получить информацию о канале. Попробуйте позже",
                        reply_markup=get_channels_keyboard()
                    )
                    await state.clear()
                    return

            # Получаем количество аккаунтов пользователя для установки максимального количества реакций
            account_count = await get_accounts_count_by_user(message.from_user.id)

            # Добавляем канал в базу
            channel_id = await channel_manager.add_channel(
                user_id=user.id,
                channel_id=channel.id,
                username=channel_username,
                title=channel.title,
                min_reactions=1,   # Минимум — одна реакция на пост
                max_reactions=account_count,  # Максимум реакций — сколько аккаунтов у юзера
                available_reactions=available_reactions
            )
            
            # Логируем добавление канала
            app_logger.info(f"Пользователь {message.from_user.full_name} добавил канал {channel.title} (ID: {channel.id})")
            
            # Сохраняем данные в состоянии
            await state.update_data(
                channel_id=channel_id,
                selected_reactions=[],
                available_reactions=available_reactions
            )
            
            await message.answer(
                f"Канал {channel.title} успешно добавлен\n"
                "Выберите реакции для использования:",
                reply_markup=get_reactions_keyboard(
                    [(r, f"reaction_{hash(r)}") for r in available_reactions],
                    []
                )
            )
            
    except Exception as e:
        app_logger.error(f"Ошибка при добавлении канала: {e}")
        await message.answer(
            "Произошла ошибка при добавлении канала. Попробуйте позже",
            reply_markup=get_channels_keyboard()
        )
        await state.clear()


@dp.callback_query(F.data.startswith("delete_channel_"))
async def delete_channel_callback(callback: CallbackQuery):
    """Удаляет канал"""
    channel_id = int(callback.data.split("_")[-1])
    try:
        async with async_session() as session:
            channel_manager = ChannelManager(session)
            success = await channel_manager.delete_channel(channel_id, service)
            
            if success:
                await callback.message.edit_text(
                    "Канал успешно удален",
                    reply_markup=get_channels_keyboard()
                )
            else:
                await callback.message.edit_text(
                    "Ошибка при удалении канала",
                    reply_markup=get_channels_keyboard()
                )
    except Exception as e:
        app_logger.error(f"Ошибка при удалении канала: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")
    await callback.answer()


@dp.callback_query(F.data.startswith("change_reaction_"))
async def change_reaction_callback(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения реакции"""
    try:
        channel_id = int(callback.data.split("_")[-1])

        async with async_session() as session:
            channel_manager = ChannelManager(session)
            channel = await channel_manager.get_channel(channel_id)

            if not channel:
                await callback.answer("Канал не найден")
                return

            # Получаем текущие реакции
            try:
                available_reactions, user_reactions = await channel_manager.get_channel_reactions(channel.id)
            except TelegramBadRequest:
                available_reactions, user_reactions = [], []

            # Сохраняем данные в состоянии
            await state.update_data(
                channel_id=channel_id,
                selected_reactions=user_reactions or [],
                available_reactions=available_reactions
            )

            # Формируем текст с текущими реакциями
            reactions_text = " ".join(user_reactions) if user_reactions else "не выбраны"

            await callback.message.edit_text(
                f"Выберите реакции для канала {channel.channel_title}\n"
                f"Текущие реакции: {reactions_text}",
                reply_markup=get_reactions_keyboard(
                    [(r, f"reaction_{hash(r)}") for r in available_reactions],
                    user_reactions or []
                )
            )

    except Exception as e:
        app_logger.error(f"Ошибка при изменении реакции: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")


@dp.callback_query(F.data.startswith("reaction_"))
@dp.callback_query(F.data == "use_all_reactions")
@dp.callback_query(F.data == "finish_reactions")
async def process_reaction(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор реакции"""
    try:
        # Получаем данные о канале из состояния
        data = await state.get_data()
        channel_id = data.get("channel_id")
        selected_reactions = data.get("selected_reactions", [])
        available_reactions = data.get("available_reactions", [])
        
        if not channel_id:
            await callback.answer("Ошибка: данные о канале не найдены")
            return
            
        async with async_session() as session:
            channel_manager = ChannelManager(session)
            channel = await channel_manager.get_channel(channel_id)
            
            if not channel:
                await callback.answer("Ошибка: канал не найден")
                return
                
            if callback.data == "finish_reactions":
                # Сохраняем выбранные реакции
                success = await channel_manager.update_channel_reaction(
                    channel_id, 
                    selected_reactions
                )
                
                if success:
                    await callback.message.edit_text(
                        f"Реакции для канала {channel.channel_title} успешно обновлены",
                        reply_markup=get_channels_keyboard()
                    )
                else:
                    await callback.answer("Ошибка при сохранении реакций")
                await state.clear()
                return
                
            elif callback.data == "use_all_reactions":
                # Переключаем режим "использовать все"
                if len(selected_reactions) == len(available_reactions):
                    selected_reactions = []
                else:
                    selected_reactions = available_reactions.copy()
                    
            else:
                # Обрабатываем выбор конкретной реакции
                reaction_hash = callback.data.split("_")[1]
                selected_reaction = None
                
                for reaction in available_reactions:
                    if hash(reaction) == int(reaction_hash):
                        selected_reaction = reaction
                        break
                        
                if not selected_reaction:
                    await callback.answer("Ошибка: реакция не найдена")
                    return
                    
                # Добавляем или удаляем реакцию
                if selected_reaction in selected_reactions:
                    selected_reactions.remove(selected_reaction)
                else:
                    selected_reactions.append(selected_reaction)
            
            # Обновляем состояние
            await state.update_data(selected_reactions=selected_reactions)
            
            # Формируем текст с текущими реакциями
            reactions_text = " ".join(selected_reactions) if selected_reactions else "не выбраны"
            
            # Обновляем сообщение
            await callback.message.edit_text(
                f"Выберите реакции для канала {channel.channel_title}\n"
                f"Текущие реакции: {reactions_text}",
                reply_markup=get_reactions_keyboard(
                    [(r, f"reaction_{hash(r)}") for r in available_reactions],
                    selected_reactions
                )
            )
            
    except Exception as e:
        app_logger.error(f"Ошибка при обработке реакции: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")

@dp.callback_query(F.data.startswith("change_count_reaction_"))
async def change_count_reaction_callback(callback: CallbackQuery, state: FSMContext):
    """ Начинает процесс изменения количества реакций """
    try:
        channel_id = int(callback.data.split("_")[-1])
        # Сохраняем данные в состоянии
        await state.update_data(
            channel_id=channel_id
        )
        await callback.message.edit_text("Введите минимальное и максимально кол-во реакций "
                                         "в формате min-max (1-15)")
        await state.set_state(ChannelStates.waiting_for_count_reaction)
    except Exception as e:
        app_logger.error(f"Ошибка при парсинге ID канала: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")


@dp.message(ChannelStates.waiting_for_count_reaction)
async def get_count_reaction_handler(message: types.Message, state: FSMContext):
    """ Получает и сохраняет кол-во реакций для канала """
    data = await state.get_data()
    channel_id = data.get("channel_id")
    app_logger.info(f"Пользователь {message.from_user.full_name} хочет обновить "
                    f"кол-во реакций для канала {channel_id}: {message.text}")

    if not channel_id:
        await message.answer("Ошибка: данные о канале не найдены")
        return

    async with async_session() as session:
        channel_manager = ChannelManager(session)
        channel = await channel_manager.get_channel(channel_id)

        if not channel:
            await message.answer("Ошибка: канал не найден")
            return

        try:
            min_reactions, max_reactions = message.text.split("-")
        except Exception:
            await message.answer("Данные введены в неверном формате!")
            await state.clear()
            return

        account_count = await get_accounts_count_by_user(message.from_user.id)
        if int(max_reactions) > account_count:
            await message.answer(f"Вы не можете ввести MAX больше количества аккаунтов ({account_count})!")
            return

        result = await channel_manager.update_reactions_count(
            channel_id,
            int(min_reactions),
            int(max_reactions)
        )
        if result:
            await message.answer("Количество реакций успешно обновлено!")
            await state.clear()
            await message.answer(
                "Управление каналами",
                reply_markup=get_channels_keyboard()
            )
        else:
            await message.answer("Произошла ошибка при обновлении количества реакций!")
            await state.clear()
            app_logger.error("Произошла ошибка при обновлении количества реакций!")


@dp.callback_query(F.data.startswith("change_count_views_"))
async def change_count_views_callback(callback: CallbackQuery, state: FSMContext):
    """ Начинает процесс изменения количества просмотров """
    try:
        channel_id = int(callback.data.split("_")[-1])
        # Сохраняем данные в состоянии
        await state.update_data(
            channel_id=channel_id
        )
        await callback.message.edit_text("Введите количество просмотров на пост")
        await state.set_state(ChannelStates.waiting_for_count_views)
    except Exception as e:
        app_logger.error(f"Ошибка при парсинге ID канала: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")

@dp.message(ChannelStates.waiting_for_count_views)
async def get_count_views_handler(message: types.Message, state: FSMContext):
    """ Получает и сохраняет кол-во просмотров для канала """
    data = await state.get_data()
    channel_id = data.get("channel_id")
    app_logger.info(f"Пользователь {message.from_user.full_name} хочет обновить "
                    f"кол-во просмотров для канала {channel_id}: {message.text}")

    if not channel_id:
        await message.answer("Ошибка: данные о канале не найдены")
        return

    async with async_session() as session:
        channel_manager = ChannelManager(session)
        channel = await channel_manager.get_channel(channel_id)

        if not channel:
            await message.answer("Ошибка: канал не найден")
            await state.clear()
            return

        try:
            views_count = int(message.text)
        except Exception:
            await message.answer("Данные введены в неверном формате! Введите цифру")
            await state.clear()
            return

        account_count = await get_accounts_count_by_user(message.from_user.id)
        if views_count > account_count:
            await message.answer(f"Вы не можете ввести количество просмотров "
                                 f"больше количества аккаунтов ({account_count})!")
            await state.clear()
            return

        result = await channel_manager.update_views_count(
            channel_id,
            views_count
        )
        if result:
            await message.answer("Количество просмотров успешно обновлено!")
            await state.clear()
            await message.answer(
                "Управление каналами",
                reply_markup=get_channels_keyboard()
            )
        else:
            await message.answer("Произошла ошибка при обновлении количества просмотров!")
            await state.clear()
            app_logger.error("Произошла ошибка при обновлении количества просмотров!")

@dp.callback_query(F.data == "back_to_channels")
async def back_to_channels_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Назад' в меню действий с каналом"""
    try:
        await callback.message.edit_text(
            "Управление каналами",
            reply_markup=get_channels_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    except Exception as e:
        app_logger.error(f"Error in back_to_channels_callback: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "search_user_channel")
async def search_user_channel_start(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс поиска канала пользователя"""
    await callback.message.edit_text("Введите название или юзернейм канала для поиска:")
    await state.set_state(ChannelStates.waiting_for_channel_search)
    await callback.answer()


@dp.message(ChannelStates.waiting_for_channel_search)
async def search_user_channel_process(message: types.Message, state: FSMContext):
    """Обрабатывает поисковый запрос по каналам пользователя"""
    search_query = message.text.strip()
    
    if not search_query:
        await message.answer("Пожалуйста, введите поисковый запрос")
        return
        
    try:
        async with async_session() as session:
            user = await get_user_by_user_id(str(message.from_user.id))
            channel_manager = ChannelManager(session)
            
            # Получаем все каналы пользователя
            all_user_channels = await channel_manager.get_user_channels(user.id)
            
            # Фильтруем каналы по поисковому запросу
            channels = []
            search_query_lower = search_query.lower()
            for channel in all_user_channels:
                if (search_query_lower in channel.channel_title.lower() or 
                    (channel.channel_username and search_query_lower in channel.channel_username.lower())):
                    channels.append(channel)
            
            if not channels:
                await message.answer(
                    f"По запросу '{search_query}' ничего не найдено",
                    reply_markup=get_channels_keyboard()
                )
            else:
                # Показываем первый канал из результатов поиска
                await message.answer(
                    f"Результаты поиска по запросу '{search_query}':"
                )
                await message.answer(
                    await _get_channel_text(channels[0], channel_manager),
                    reply_markup=get_channel_actions_keyboard(channels[0].id, 0, len(channels))
                )
                
            await state.clear()
    except Exception as e:
        app_logger.error(f"Ошибка при поиске каналов: {e}")
        await message.answer("Произошла ошибка при поиске каналов", 
                            reply_markup=get_channels_keyboard())
        await state.clear()
