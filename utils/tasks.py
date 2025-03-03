import asyncio

from services.account_manager import AccountService


async def background_cleanup_task(service: AccountService):
    """ Фоновая таска для очистки кеша """
    while True:
        await asyncio.sleep(3600)  # Каждый час
        await service.clear_session_cache()
