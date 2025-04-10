from aiogram import types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

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

            # Сохраняем индекс текущего канала в состоянии
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
    
    # Получаем последнюю реакцию для канала
    last_reaction = await channel_manager.get_last_reaction(channel.id)
    if last_reaction:
        text += f"Реакция: {last_reaction.reaction}\n"
    else:
        text += "Реакция: не установлена\n"
        
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
            
            if channel_link.startswith('@'):
                channel_username = channel_link[1:]
            else:
                channel_username = channel_link.split('/')[-1]

            # Получаем информацию о канале
            channel = await bot.get_chat(f"@{channel_username}")
            
            # Добавляем канал в базу
            await channel_manager.add_channel(
                user_id=user.id,
                channel_id=channel.id,
                username=channel_username,
                title=channel.title
            )
            
            await state.clear()
            await message.answer(
                f"Канал {channel.title} успешно добавлен",
                reply_markup=get_channels_keyboard()
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
    channel_id = int(callback.data.split("_")[-1])
    await state.update_data(channel_id=channel_id)
    await callback.message.edit_text(
        "Выберите реакцию для канала",
        reply_markup=get_reactions_keyboard()
    )
    await state.set_state(ChannelStates.waiting_for_reaction)
    await callback.answer()


@dp.callback_query(ChannelStates.waiting_for_reaction)
async def process_reaction(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор реакции"""
    reaction = callback.data.split("_")[-1]
    data = await state.get_data()
    channel_id = data["channel_id"]
    
    try:
        async with async_session() as session:
            channel_manager = ChannelManager(session)
            success = await channel_manager.update_channel_reaction(channel_id, reaction)
            
            if success:
                await callback.message.edit_text(
                    f"Реакция успешно изменена на {reaction}",
                    reply_markup=get_channels_keyboard()
                )
            else:
                await callback.message.edit_text(
                    "Ошибка при изменении реакции",
                    reply_markup=get_channels_keyboard()
                )
    except Exception as e:
        app_logger.error(f"Ошибка при изменении реакции: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже")
    
    await state.clear()
    await callback.answer()


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
