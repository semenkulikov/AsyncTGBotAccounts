from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config_data.config import ADMIN_ID
from database.query_orm import get_all_users

async def users_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    users = await get_all_users()
    for user in users:
        # Добавляем кнопку только если пользователь не является администратором
        if int(user.user_id) != int(ADMIN_ID):
            builder.button(text=user.username, callback_data=str(user.id))
    
    # Добавляем кнопку для управления каналами
    builder.button(text="📢 Каналы", callback_data="channels")
    
    # Добавляем кнопку "Выйти"
    builder.button(text="Выйти", callback_data="Выход")
    
    # Располагаем кнопки в 2 колонки
    builder.adjust(2)
    return builder.as_markup()
