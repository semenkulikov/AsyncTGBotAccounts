from aiogram.filters import Command, StateFilter

from aiogram import types
from aiogram.fsm.context import FSMContext
from loader import dp, bot, app_logger
from config_data.config import ALLOWED_USERS, ADMIN_ID, ENCRYPTION_KEY
from keyboards.inline.accounts import users_markup
from keyboards.inline.channels import admin_channels_markup, get_channel_actions_keyboard
from states.states import AdminPanel
from sqlalchemy.future import select
from database.models import User, UserChannel, async_session
from services.channel_manager import ChannelManager


@dp.message(Command('admin_panel'))
async def admin_panel(message: types.Message, state: FSMContext):
    if int(message.from_user.id) in ALLOWED_USERS:
        app_logger.info(f"Администратор @{message.from_user.username} вошел в админ панель.")
        markup = await users_markup()
        await message.answer("Админ-панель:", reply_markup=markup)
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
    elif call.data == "channels":
        # Переход к списку каналов
        await show_channels(call, state)
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


# Добавляем кнопку каналов в клавиатуру пользователей
@dp.callback_query(lambda call: call.data == "channels")
async def show_channels(call: types.CallbackQuery, state: FSMContext):
    """Показывает список всех каналов в системе"""
    try:
        async with async_session() as session:
            channel_manager = ChannelManager(session)
            # Получаем все каналы из базы данных
            result = await session.execute(select(UserChannel).limit(10))
            channels = result.scalars().all()
            
            if not channels:
                await call.message.edit_text(
                    "В системе нет каналов",
                    reply_markup=await admin_channels_markup()
                )
            else:
                await call.message.edit_text(
                    "Список каналов в системе:",
                    reply_markup=await admin_channels_markup(channels)
                )
                
            await state.set_state(AdminPanel.search_channels)
    except Exception as e:
        app_logger.error(f"Ошибка при получении списка каналов: {e}")
        await call.answer("Произошла ошибка при получении списка каналов")


@dp.callback_query(StateFilter(AdminPanel.search_channels), lambda call: call.data == "search_channel")
async def search_channel_start(call: types.CallbackQuery, state: FSMContext):
    """Начинает процесс поиска канала"""
    await call.message.edit_text("Введите название или юзернейм канала для поиска:")
    await state.set_state(AdminPanel.waiting_for_channel_search)


@dp.message(StateFilter(AdminPanel.waiting_for_channel_search))
async def search_channel_process(message: types.Message, state: FSMContext):
    """Обрабатывает поисковый запрос по каналам"""
    search_query = message.text.strip()
    
    if not search_query:
        await message.answer("Пожалуйста, введите поисковый запрос")
        return
        
    try:
        async with async_session() as session:
            channel_manager = ChannelManager(session)
            channels = await channel_manager.search_channels(search_query)
            
            if not channels:
                await message.answer(
                    f"По запросу '{search_query}' ничего не найдено",
                    reply_markup=await admin_channels_markup()
                )
            else:
                await message.answer(
                    f"Результаты поиска по запросу '{search_query}':",
                    reply_markup=await admin_channels_markup(channels)
                )
                
            await state.set_state(AdminPanel.search_channels)
    except Exception as e:
        app_logger.error(f"Ошибка при поиске каналов: {e}")
        await message.answer("Произошла ошибка при поиске каналов")


@dp.callback_query(StateFilter(AdminPanel.search_channels), lambda call: call.data.startswith("admin_channel_"))
async def show_channel_details(call: types.CallbackQuery, state: FSMContext):
    """Показывает детали канала и варианты действий"""
    channel_id = int(call.data.split("_")[-1])
    
    try:
        async with async_session() as session:
            channel_manager = ChannelManager(session)
            channel = await channel_manager.get_channel(channel_id)
            
            if not channel:
                await call.answer("Канал не найден")
                return
                
            # Получаем текущие реакции канала
            try:
                available_reactions, user_reactions = await channel_manager.get_channel_reactions(channel.id)
            except Exception:
                available_reactions, user_reactions = [], []
                
            user_reactions = available_reactions if user_reactions is None else user_reactions
            reactions_text = " ".join(user_reactions) if user_reactions else "не выбраны"
            
            text = f"📢 Канал: {channel.channel_title}\n"
            text += f"Username: @{channel.channel_username}\n"
            text += f"ID: {channel.channel_id}\n"
            text += f"Статус: {'активен' if channel.is_active else 'неактивен'}\n"
            text += f"Минимальное количество реакций: {channel.min_reactions}\n"
            text += f"Максимальное количество реакций: {channel.max_reactions}\n"
            text += f"Количество просмотров: {channel.views}\n"
            text += f"Реакции: {reactions_text}\n"
            
            await call.message.edit_text(
                text,
                reply_markup=get_channel_actions_keyboard(channel.id, 0, 1)
            )
    except Exception as e:
        app_logger.error(f"Ошибка при получении информации о канале: {e}")
        await call.answer("Произошла ошибка при получении информации о канале")


@dp.callback_query(StateFilter(AdminPanel.search_channels), lambda call: call.data == "back_to_admin")
async def back_to_admin_panel(call: types.CallbackQuery, state: FSMContext):
    """Возвращает в главное меню админки"""
    await call.answer()
    markup = await users_markup()
    await call.message.edit_text("Админ-панель:", reply_markup=markup)
    await state.set_state(AdminPanel.get_users)
