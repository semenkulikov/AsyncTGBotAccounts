import asyncio
from datetime import datetime, timedelta

from config_data.config import ADMIN_ID
from loader import bot, dp, app_logger
from services.services import service, activity_manager
from services.channel_manager import ChannelManager
from database.models import Base, engine, UserChannel, Account
import handlers


async def main():
    """ Функция - точка входа """
    # Инициализация базы данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app_logger.info("Подключение к базе данных...")

    # Запуск фоновых задач для существующих аккаунтов
    accounts = await service.get_all_active_accounts()
    user_ids = {acc.user_id for acc in accounts}

    for user_id in user_ids:
        try:
            await activity_manager.start_user_activity(user_id, service)
        except Exception:
            app_logger.info(f"Пользователь с ID: {user_id} не найден!")
    app_logger.info(f"Запущены фоновые задачи для {len(user_ids)} пользователей...")

    # Отправка уведомления администратору
    bot_data = await bot.get_me()
    app_logger.info(f"Бот @{bot_data.username} запущен...")
    await bot.send_message(
        int(ADMIN_ID),
        f"Бот @{bot_data.username} запущен."
    )
    app_logger.info(f"Отправлено уведомление администратору")

    # Запуск бота
    await dp.start_polling(bot)

    # Очистка при завершении
    for task in activity_manager.user_tasks.values():
        task.cancel()
    await asyncio.gather(*activity_manager.user_tasks.values(), return_exceptions=True)

if __name__ == '__main__':
    asyncio.run(main())
