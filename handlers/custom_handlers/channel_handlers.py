from aiogram import types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserChannel
from database.query_orm import get_user_by_user_id
from handlers.default_handlers.echo import echo_handler
from keyboards.inline.channels import get_channels_keyboard
from loader import bot, dp, app_logger
from services.channel_manager import ChannelManager
from states.states import ChannelStates


@dp.message(Command("channels"))
async def my_channels(message: types.Message, session: AsyncSession):
    """Показывает список каналов пользователя"""
    user = await get_user_by_user_id(str(message.from_user.id))

    channel_manager = ChannelManager(session)
    channels = await channel_manager.get_user_channels(user.id)
    
    if not channels:
        await message.answer("У вас пока нет добавленных каналов")
        return
        
    await message.answer(
        "Ваши каналы:",
        reply_markup=await get_channels_keyboard(channels)
    )

@router.callback_query(F.data == "add_channel")
async def add_channel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Отправьте ссылку на канал или его username"
    )
    await state.set_state(ChannelStates.waiting_for_channel)
    await callback.answer()


@dp.message(ChannelStates.waiting_for_channel)
async def process_channel(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обрабатывает добавление канала"""
    try:
        channel_link = message.text.strip()
        if not channel_link.startswith('@') and not channel_link.startswith('https://t.me/'):
            await message.answer("Пожалуйста, отправьте корректную ссылку на канал")
            return

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
        await message.answer(f"Канал {channel.title} успешно добавлен")
        
    except Exception as e:
        app_logger.error(f"Ошибка при добавлении канала: {e}")
        await message.answer("Произошла ошибка при добавлении канала. Попробуйте позже")
        await state.clear()


@dp.callback_query(F.data.startswith("channel_"))
async def process_channel_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Обрабатывает действия с каналами"""
    action, channel_id = callback.data.split("_")[1:]
    channel_manager = ChannelManager(session)
    
    if action == "delete":
        success = await channel_manager.delete_channel(int(channel_id))
        if success:
            await callback.message.edit_text("Канал успешно удален")
        else:
            await callback.message.edit_text("Ошибка при удалении канала")
            
    elif action == "toggle":
        channel = await channel_manager.get_channel(int(channel_id))
        if channel:
            channel.is_active = not channel.is_active
            await session.commit()
            await callback.message.edit_text(
                f"Статус канала изменен: {'активен' if channel.is_active else 'неактивен'}"
            )
            
    await callback.answer() 