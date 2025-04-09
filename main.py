import asyncio
from datetime import datetime, timedelta

from config_data.config import ADMIN_ID
from loader import bot, dp, app_logger
from services.services import service, activity_manager
from services.channel_manager import ChannelManager
from database.models import Base, engine, UserChannel, Account
import handlers

async def check_channels():
    while True:
        try:
            async with engine.begin() as session:
                channel_manager = ChannelManager(session)
                channels = await channel_manager.get_user_channels()
                
                for channel in channels:
                    if not channel.is_active:
                        continue
                        
                    accounts = await service.get_user_accounts(channel.user_id)
                    await channel_manager.process_channel_posts(channel, accounts)
                    
                    await asyncio.sleep(10)  # Задержка между проверками каналов
                    
        except Exception as e:
            app_logger.error(f"Error in channel checking task: {e}")
            await asyncio.sleep(60)  # Задержка при ошибке

async def main():
    # Инициализация базы данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app_logger.info("Подключение к базе данных...")

    # Запуск фоновых задач для существующих аккаунтов
    accounts = await service.get_all_active_accounts()
    user_ids = {acc.user_id for acc in accounts}

    for user_id in user_ids:
        await activity_manager.start_user_activity(user_id, service)
    app_logger.info(f"Запущены фоновые задачи для {len(user_ids)} аккаунтов...")

    # Запуск задачи проверки каналов
    asyncio.create_task(check_channels())
    app_logger.info("Запущена задача проверки каналов...")

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
