from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from config_data.config import ENCRYPTION_KEY, API_ID, API_HASH
from loader import dp
from services.account_manager import AccountService
from states.states import AddAccountStates


@dp.message(Command("add_account"))
async def add_account_start(message: Message, state: FSMContext):
    await message.answer("Введите номер телефона в формате +79123456789:")
    await state.set_state(AddAccountStates.wait_phone)


@dp.message(AddAccountStates.wait_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith('+'):
        return await message.answer("Неверный формат номера. Попробуйте снова:")

    client = TelegramClient(None, API_ID, API_HASH)
    await client.connect()
    sent_code = await client.send_code_request(phone)

    await state.update_data(phone=phone, client=client, sent_code=sent_code)
    await message.answer("Введите код подтверждения из SMS:")
    await state.set_state(AddAccountStates.wait_code)


@dp.message(AddAccountStates.wait_code)
async def process_code(message: Message, state: FSMContext):
    data = await state.get_data()
    code = message.text.strip()

    try:
        client = data['client']
        await client.sign_in(data['phone'], code, phone_code_hash=data['sent_code'].phone_code_hash)
    except SessionPasswordNeededError:
        await message.answer("Введите пароль двухфакторной аутентификации:")
        await state.set_state(AddAccountStates.wait_2fa)
        return
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}. Начните заново.")
        await state.clear()
        return

    session_str = client.session.save()
    service = AccountService(ENCRYPTION_KEY)
    await service.create_account(data['phone'], session_str)
    await message.answer("Аккаунт успешно добавлен!")
    await client.disconnect()
    await state.clear()


@dp.message(AddAccountStates.wait_2fa)
async def process_2fa(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()

    try:
        await data['client'].sign_in(password=password)
        session_str = data['client'].session.save()
        service = AccountService(ENCRYPTION_KEY)
        await service.create_account(data['phone'], session_str)
        await message.answer("Аккаунт успешно добавлен!")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}. Начните заново.")

    await data['client'].disconnect()
    await state.clear()
