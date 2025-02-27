from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def handlers_reply() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="Тестовая кнопка 1")
    kb.button(text="Тестовая 2")
    kb.button(text="Тестовая 3")
    kb.adjust(3)
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="Выберите одну из кнопок")
