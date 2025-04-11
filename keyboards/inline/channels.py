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

def get_reactions_keyboard(reactions: list[tuple[str, str]], selected_reactions: list[str] = None) -> InlineKeyboardMarkup:
    """Создает клавиатуру с доступными реакциями"""
    if selected_reactions is None:
        selected_reactions = []
        
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки реакций
    for emoji, callback_data in reactions:
        # Если реакция уже выбрана, добавляем галочку
        text = f"{'✅ ' if emoji in selected_reactions else ''}{emoji}"
        builder.add(InlineKeyboardButton(text=text, callback_data=callback_data))
    
    # Добавляем кнопку "Использовать все"
    builder.add(InlineKeyboardButton(
        text="✅ Использовать все" if len(selected_reactions) == len(reactions) else "Использовать все",
        callback_data="use_all_reactions"
    ))
    
    # Добавляем кнопку "Завершить"
    builder.add(InlineKeyboardButton(
        text="💾 Завершить",
        callback_data="finish_reactions"
    ))
    
    # Добавляем кнопку "Назад"
    builder.add(InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="back_to_channels"
    ))
    
    # Настраиваем расположение кнопок (5 в ряд для реакций, остальные по одной)
    builder.adjust(5, 1, 1, 1)
    
    return builder.as_markup() 

