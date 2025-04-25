import asyncio
import datetime

from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from telethon import TelegramClient
from telethon import types as tg_types
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession
from services.services import activity_manager, service
from config_data.config import ENCRYPTION_KEY, API_ID, API_HASH
from loader import dp, app_logger
from services.account_manager import AccountService
from states.states import AddAccountStates, AccountStates


@dp.message(Command("add_account"))
async def add_account_start(message: Message, state: FSMContext):
    app_logger.info(f"Пользователь @{message.from_user.username} запросил создание аккаунта.")
    await message.answer("Введите номер телефона в формате +79123456789:")
    await state.set_state(AddAccountStates.wait_phone)


@dp.message(AddAccountStates.wait_phone)
async def process_phone(message: Message, state: FSMContext):
    """ Хендлер для приема номера телефона """
    phone = message.text.strip()
    if not phone.startswith('+'):
        await message.answer("Неверный формат номера. Попробуйте снова")
        await state.clear()
        return

    # Явно создаем новую строковую сессию
    session = StringSession()

    try:
        client = TelegramClient(
            session=session,
            api_id=API_ID,
            api_hash=API_HASH,
            device_model="Xiaomi Redmi Note 13",
            app_version="10.1.5",
            system_version="Android 13",
            lang_code="ru",
            system_lang_code="ru-RU"
        )
        await client.connect()
        await asyncio.sleep(2)  # Anti-flood delay

        sent_code = await client.send_code_request(phone)

        await state.update_data(
            phone=phone,
            client=client,
            sent_code=sent_code,
            session=session  # Сохраняем объект сессии
        )
        app_logger.info(f"Пользователь @{message.from_user.username} ввел номер телефона: {phone}.")
        await message.answer("Введите код подтверждения из SMS:")
        await state.set_state(AddAccountStates.wait_code)

    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", parse_mode=None)
        await client.disconnect()
        await state.clear()


@dp.message(AddAccountStates.wait_code)
async def process_code(message: Message, state: FSMContext):
    """ Хендлер для приема кода авторизации """
    data = await state.get_data()
    code = message.text.strip()

    try:
        client = data['client']
        session = client.session

        # Явное сохранение сессии перед авторизацией
        if not isinstance(session, StringSession):
            client.session = StringSession()

        await client.sign_in(
            phone=data['phone'],
            code=code,
            phone_code_hash=data['sent_code'].phone_code_hash
        )
        session_str = data['client'].session.save()
        if not await AccountService(ENCRYPTION_KEY).validate_session(session_str):
            raise ValueError("Invalid session")

        # Дополнительная проверка сессии
        me = await client.get_me()
        if not me or not me.phone:
            raise ValueError("Не удалось получить данные аккаунта")

        service = AccountService(ENCRYPTION_KEY)
        await activity_manager.start_user_activity(message.from_user.id, service)
        app_logger.info("Запущена фоновая задача для входа в аккаунты")
        await service.create_account(message.from_user.id, data['phone'], session_str)

        # Отправляем подтверждение
        await message.answer(f"""
        ✅ Аккаунт {me.phone} успешно добавлен!
        Устройство: Samsung S24 Ultra
        Дата подключения: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}
                """)

        app_logger.info(f"Пользователь @{message.from_user.username} успешно добавил аккаунт.")
        await client.disconnect()
        await state.clear()

    except SessionPasswordNeededError:
        await message.answer("Введите пароль двухфакторной аутентификации:")
        await state.set_state(AddAccountStates.wait_2fa)
        return
    except tg_types.PhoneCodeExpiredError:
        await message.answer("Код устарел. Запросите новый код.")
        await process_phone(message, state)
    except Exception as e:
        data['attempts'] += 1
        if data['attempts'] > 3:
            await message.answer("Слишком много попыток. Начните заново.")
            await state.clear()


@dp.message(AddAccountStates.wait_2fa)
async def process_2fa(message: Message, state: FSMContext):
    """ Хендлер для обработки 2FA авторизации """
    password = message.text.strip()
    data = await state.get_data()

    try:
        client = data['client']
        session = data['session']

        # Явное сохранение сессии перед авторизацией
        if not isinstance(session, StringSession):
            client.session = StringSession()

        try:
            await client.sign_in(
                password=password,
                phone_code_hash=data['sent_code'].phone_code_hash
            )
        except FloodWaitError as e:
            await message.answer(f"Слишком много попыток. Попробуйте через {e.seconds} секунд")
            return

        # Проверка и сохранение сессии
        if not client.session:
            raise ValueError("Сессия не создана")

        session_str = session.save()
        app_logger.debug(f"Сохранена строка сессии: {session_str}")

        if not session_str or len(session_str) < 50:
            raise ValueError("Неверный формат сессии")

        # Дополнительная проверка через получение информации об аккаунте
        me = await client.get_me()
        if not me or not me.phone:
            raise ValueError("Не удалось получить информацию об аккаунте")


        # Валидация сессии
        service = AccountService(ENCRYPTION_KEY)
        if not await service.validate_session(session_str):
            raise ValueError("Невалидная сессия")

        # Шифрование пароля
        encrypted_password = service.cipher.encrypt(password.encode()).decode()

        await activity_manager.start_user_activity(message.from_user.id, service)
        app_logger.info("Запущена фоновая задача для входа в аккаунты")

        # Сохранение в базу данных
        await service.create_account(
            user_id=message.from_user.id,
            phone=data['phone'],
            session_str=session_str,
            two_factor=encrypted_password
        )

        # Отправляем подтверждение
        await message.answer(f"""
        ✅ Аккаунт {me.phone} успешно добавлен!
        Устройство: Samsung S24 Ultra
        Дата подключения: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}
                """)
        app_logger.info(f"Успешная авторизация 2FA для {data['phone']}")

    except Exception as e:
        error_msg = f"Ошибка: {str(e)}"
        await message.answer(f"❌ {error_msg}\nНачните заново.", parse_mode=None)
        app_logger.error(f"2FA failed: {error_msg}")

    finally:
        if client:
            await client.disconnect()
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
    await message.answer(text, parse_mode=None)


@dp.message(Command("toggle_account"))
async def toggle_account_start(message: Message, state: FSMContext):
    await message.answer("Введите номер аккаунта для включения/выключения:")
    await state.set_state(AccountStates.wait_toggle_phone)


@dp.message(AccountStates.wait_toggle_phone)
async def process_toggle(message: Message, state: FSMContext):
    success, old_status, new_status = await service.toggle_account(message.from_user.id, message.text)

    if success:
        status_change = (f"Статус изменен с {'активен' if old_status else 'неактивен'} на "
                         f"{'активен' if new_status else 'неактивен'}")
        await message.answer(f"✅ {status_change}")
        app_logger.info(f"Статус аккаунта {message.text} изменен: {status_change}")

        # Остановка задач для неактивных аккаунтов
        if new_status:
            # Если аккаунт теперь активен, запускаем цикл активности
            await activity_manager.start_account_activity(message.text, service)
        else:
            await activity_manager.stop_account_activity(message.text)

    else:
        await message.answer("Аккаунт не найден")
    await state.clear()
