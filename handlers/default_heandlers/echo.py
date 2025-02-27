from aiogram import types
from loader import dp

@dp.message()
async def bot_echo(message: types.Message):
    await message.reply(
        "Введите любую команду из меню, чтобы я начал работать\n"
        "Либо выберите одну из кнопок, которые я вам прислал"
    )
