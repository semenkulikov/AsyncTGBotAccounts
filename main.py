import os
import asyncio
from loader import bot, dp, app_logger
from services.account_manager import AccountService, AccountActivity
from utils.set_bot_commands import set_default_commands
from database.models import Base, engine
from config_data.config import ADMIN_ID, ENCRYPTION_KEY, API_ID, API_HASH
import handlers

async def main():
    # Создание таблиц в базе данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app_logger.info("Подключение к базе данных...")

    await set_default_commands()
    app_logger.info("Загрузка базовых команд...")

    me = await bot.get_me()
    app_logger.info(f"Бот @{me.username} запущен.")

    # Запуск фоновой задачи
    service = AccountService(ENCRYPTION_KEY)
    activity = AccountActivity(API_ID, API_HASH, service)
    asyncio.create_task(activity.random_activity_loop())
    app_logger.info("Запущена фоновая задача для входа в аккаунты")

    try:
        await bot.send_message(ADMIN_ID, "Бот запущен.")
    except Exception as e:
        app_logger.error(f"Ошибка при отправке сообщения администратору: {e}")

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
