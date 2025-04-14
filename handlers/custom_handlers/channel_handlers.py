from aiogram import types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from config_data.config import API_HASH, API_ID
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import ReactionEmoji, ChatInviteAlready
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpAbridged
from services.services import service

from database.models import UserChannel, async_session
from database.query_orm import get_user_by_user_id
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
                
            # Берем первый активный аккаунт
            account = accounts[0]
            
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
                            # Аккаунт не присоединен к каналу
                            await message.answer("Аккаунт не присоединен к закрытому каналу!")
                            return
                    else:
                        channel = await client.get_entity(channel_username)
                        full_channel = await client(GetFullChannelRequest(channel))

                    # Обработка ситуации уже добавленного канала
                    if channel.title in user_channels:
                        await message.answer("Такой канал уже добавлен!")
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

            # Добавляем канал в базу
            channel_id = await channel_manager.add_channel(
                user_id=user.id,
                channel_id=channel.id,
                username=channel_username,
                title=channel.title,
                available_reactions=available_reactions
            )
            
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
            success = await channel_manager.delete_channel(channel_id)
            
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
