from aiogram import types
from loader import dp
from aiogram.fsm.context import FSMContext
from handlers.custom_handlers.account_handlers import add_account_start, list_accounts, toggle_account_start
from handlers.custom_handlers.channel_handlers import channels_handler

@dp.message()
async def bot_echo(message: types.Message, state: FSMContext):
    # Проверяем текст сообщения и вызываем соответствующий хендлер
    if message.text == "Добавить аккаунт":
        await add_account_start(message, state)
    elif message.text == "Мои аккаунты":
        await list_accounts(message)
    elif message.text == "Изменить статус":
        await toggle_account_start(message, state)
    elif message.text == "Мои каналы":
        await channels_handler(message)
    else:
        await message.reply(
            "Введите любую команду из меню, чтобы я начал работать\n"
            "Либо выберите одну из кнопок, которые я вам прислал"
        )
