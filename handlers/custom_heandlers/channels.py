from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.inline.channels import get_channels_keyboard, get_channel_actions_keyboard, get_reactions_keyboard
from services.channel_manager import ChannelManager
from states.states import ChannelStates

router = Router()

@router.message(Command("channels"))
async def cmd_channels(message: Message):
    await message.answer(
        "Управление каналами",
        reply_markup=get_channels_keyboard()
    )

@router.callback_query(F.data == "add_channel")
async def add_channel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Отправьте ссылку на канал или его username"
    )
    await state.set_state(ChannelStates.waiting_for_channel)
    await callback.answer()

@router.message(ChannelStates.waiting_for_channel)
async def process_channel(message: Message, state: FSMContext, session: AsyncSession):
    channel_manager = ChannelManager(session)
    try:
        # Здесь нужно добавить логику получения информации о канале через Telethon
        # Для примера используем заглушку
        channel_id = 123456789  # Получаем из Telethon
        username = message.text.strip('@')
        title = "Channel Title"  # Получаем из Telethon
        
        await channel_manager.add_channel(
            user_id=message.from_user.id,
            channel_id=channel_id,
            username=username,
            title=title
        )
        
        await message.answer(
            f"Канал {title} успешно добавлен!\n"
            "Выберите реакцию для постов:",
            reply_markup=get_reactions_keyboard()
        )
        await state.set_state(ChannelStates.waiting_for_reaction)
        
    except Exception as e:
        await message.answer(f"Ошибка при добавлении канала: {e}")
        await state.clear()

@router.callback_query(F.data.startswith("set_reaction_"))
async def set_reaction_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    reaction = callback.data.split("_")[2]
    channel_manager = ChannelManager(session)
    
    # Здесь нужно добавить логику обновления реакции для последнего добавленного канала
    # Для примера используем заглушку
    channel_id = 1  # Получаем из состояния или базы данных
    
    await channel_manager.update_channel_reaction(channel_id, reaction)
    await callback.message.answer(f"Реакция {reaction} установлена для канала")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "my_channels")
async def my_channels_callback(callback: CallbackQuery, session: AsyncSession):
    channel_manager = ChannelManager(session)
    channels = await channel_manager.get_user_channels(callback.from_user.id)
    
    if not channels:
        await callback.message.answer("У вас пока нет добавленных каналов")
        return
    
    for channel in channels:
        await callback.message.answer(
            f"📢 {channel.channel_title}\n"
            f"👤 @{channel.channel_username}\n"
            f"💫 Реакция: {channel.reaction if channel.reaction else 'Не установлена'}",
            reply_markup=get_channel_actions_keyboard(channel.id)
        )
    
    await callback.answer()

@router.callback_query(F.data.startswith("delete_channel_"))
async def delete_channel_callback(callback: CallbackQuery, session: AsyncSession):
    channel_id = int(callback.data.split("_")[2])
    channel_manager = ChannelManager(session)
    
    if await channel_manager.delete_channel(channel_id):
        await callback.message.answer("Канал успешно удален")
    else:
        await callback.message.answer("Ошибка при удалении канала")
    
    await callback.answer() 