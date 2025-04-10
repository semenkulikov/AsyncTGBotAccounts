from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_channels_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="➕ Добавить канал",
        callback_data="add_channel"
    ))
    builder.add(InlineKeyboardButton(
        text="📋 Мои каналы",
        callback_data="my_channels"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_channel_actions_keyboard(channel_id: int, current_index: int, total_channels: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Кнопки навигации
    if total_channels > 1:
        if current_index > 0:
            builder.add(InlineKeyboardButton(
                text="⬅️ Предыдущий",
                callback_data=f"prev_channel_{channel_id}"
            ))
        if current_index < total_channels - 1:
            builder.add(InlineKeyboardButton(
                text="Следующий ➡️",
                callback_data=f"next_channel_{channel_id}"
            ))
        builder.adjust(2)
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(
        text="❌ Удалить",
        callback_data=f"delete_channel_{channel_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔄 Изменить реакцию",
        callback_data=f"change_reaction_{channel_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="back_to_channels"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_reactions_keyboard() -> InlineKeyboardMarkup:
    reactions = ["👍", "❤️", "🔥", "🎉", "👏", "😮", "😢", "🤔"]
    builder = InlineKeyboardBuilder()
    for reaction in reactions:
        builder.add(InlineKeyboardButton(
            text=reaction,
            callback_data=f"set_reaction_{reaction}"
        ))
    builder.adjust(4)
    return builder.as_markup() 