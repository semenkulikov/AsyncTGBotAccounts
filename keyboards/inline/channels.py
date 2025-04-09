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
    builder.add(InlineKeyboardButton(
        text="⚙️ Настройки реакций",
        callback_data="reaction_settings"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_channel_actions_keyboard(channel_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="❌ Удалить",
        callback_data=f"delete_channel_{channel_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="🔄 Изменить реакцию",
        callback_data=f"change_reaction_{channel_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="⏱ Изменить интервал",
        callback_data=f"change_interval_{channel_id}"
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