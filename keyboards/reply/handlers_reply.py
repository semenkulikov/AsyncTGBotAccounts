from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def handlers_reply() -> ReplyKeyboardMarkup:
    """Клавиатура для главного меню с основными командами"""
    kb = ReplyKeyboardBuilder()
    
    # Добавляем кнопки для основных команд
    kb.button(text="Добавить аккаунт")  # Соответствует команде /add_account
    kb.button(text="Мои аккаунты")       # Соответствует команде /my_accounts
    kb.button(text="Мои каналы")         # Соответствует команде /my_channels
    kb.button(text="Изменить статус")    # Соответствует команде /toggle_account

    kb.adjust(2)  # Располагаем кнопки в 2 колонки
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="Выберите команду")
