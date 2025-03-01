from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from config_data.config import ENCRYPTION_KEY, API_ID, API_HASH
from loader import dp, app_logger, activity_manager
from services.account_manager import AccountService
from states.states import AddAccountStates, AccountStates


@dp.message(Command("add_account"))
async def add_account_start(message: Message, state: FSMContext):
    app_logger.info(f"Пользователь @{message.from_user.username} запросил создание аккаунта.")
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
    app_logger.info(f"Пользователь @{message.from_user.username} ввел номер телефона: {phone}.")
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
        app_logger.error(f"Не удалось подключить аккаунт {data['phone']}: {e}")
        await state.clear()
        return

    session_str = client.session.save()
    service = AccountService(ENCRYPTION_KEY)
    await activity_manager.start_user_activity(message.from_user.id, service)
    app_logger.info("Запущена фоновая задача для входа в аккаунты")
    await service.create_account(message.from_user.id, data['phone'], session_str)
    await message.answer("Аккаунт успешно добавлен!")
    app_logger.info(f"Пользователь @{message.from_user.username} успешно добавил аккаунт.")
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
        await service.create_account(message.from_user.id, data['phone'], session_str)
        await activity_manager.start_user_activity(message.from_user.id, service)
        await message.answer("Аккаунт успешно добавлен!")
        app_logger.info(f"Пользователь @{message.from_user.username} успешно добавил аккаунт.")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}. Начните заново.")
        app_logger.error(f"Не удалось подключить аккаунт {data['phone']}: {e}")

    await data['client'].disconnect()
    await state.clear()


@dp.message(Command("my_accounts"))
async def list_accounts(message: Message):
    service = AccountService(ENCRYPTION_KEY)
    accounts = await service.get_user_accounts(message.from_user.id)
    app_logger.info(f"Пользователь @{message.from_user.username} запросил список своих аккаунтов")

    if not accounts:
        return await message.answer("У вас нет привязанных аккаунтов")

    text = "Ваши аккаунты:\n" + "\n".join(
        [f"{i + 1}. {acc.phone} ({'активен' if acc.is_active else 'неактивен'})"
         for i, acc in enumerate(accounts)]
    )
    await message.answer(text)


@dp.message(Command("toggle_account"))
async def toggle_account_start(message: Message, state: FSMContext):
    await message.answer("Введите номер аккаунта для включения/выключения:")
    await state.set_state(AccountStates.wait_toggle_phone)


@dp.message(AccountStates.wait_toggle_phone)
async def process_toggle(message: Message, state: FSMContext):
    service = AccountService(ENCRYPTION_KEY)
    success = await service.toggle_account(message.from_user.id, message.text)

    if success:
        await message.answer("Статус аккаунта изменен")
        app_logger.info(f"Пользователь @{message.from_user.username} изменил статус аккаунта {message.text}")
    else:
        await message.answer("Аккаунт не найден")
    await state.clear()
