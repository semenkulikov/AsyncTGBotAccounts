import asyncio
from loader import bot, dp, app_logger, activity_manager
from services.account_manager import AccountService, UserActivityManager
from config_data.config import ADMIN_ID, ENCRYPTION_KEY, API_ID, API_HASH
from database.models import Base, engine
import handlers


async def main():
    # Инициализация базы данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app_logger.info("Подключение к базе данных...")

    # Инициализация сервисов
    service = AccountService(ENCRYPTION_KEY)

    # Запуск фоновых задач для существующих аккаунтов
    accounts = await service.get_all_active_accounts()
    user_ids = {acc.user_id for acc in accounts}


    for user_id in user_ids:
        await activity_manager.start_user_activity(user_id, service)
    app_logger.info(f"Запущены фоновые задачи для {len(user_ids)} аккаунтов...")

    # Запуск бота
    await dp.start_polling(bot)
    app_logger.info("Бот запущен...")

    # Очистка при завершении
    for task in activity_manager.user_tasks.values():
        task.cancel()
    await asyncio.gather(*activity_manager.user_tasks.values(), return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
