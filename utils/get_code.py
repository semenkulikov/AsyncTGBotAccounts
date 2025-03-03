import os

from telethon import TelegramClient, events
from telethon.network import ConnectionTcpAbridged
from telethon.sessions import StringSession
import sys
import re
from dotenv import find_dotenv, load_dotenv

if find_dotenv():
    load_dotenv()


API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")


def validate_code(text):
    patterns = [
        r'\b\d{5}\b',  # 5-значные коды
        r'\b\d{4}-\d{4}\b',  # Коды вида 1234-5678
        r'[A-Z0-9]{5}-[A-Z0-9]{5}',  # Коды из 10 символов с дефисом
        r'Код:\s*\d+',  # Коды после слова "Код:"
        r'code:\s*\d+',  # Английская версия
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    return None


def is_security_alert(text):
    security_keywords = [
        r'Вход с нового устройства',
        r'мы обнаружили вход в Ваш аккаунт',
        r'новый вход в аккаунт',
        r'подозрительная активность',
        r'security alert',
        r'new login detected',
        r'suspicious login attempt',
        r'кто-то вошел в ваш аккаунт',
        r'Incomplete login attempt',

    ]

    for keyword in security_keywords:
        if re.search(keyword, text, re.IGNORECASE):
            return True
    return False


async def main(session_str):
    client = TelegramClient(
        session=StringSession(session_str),
        api_id=API_ID,
        api_hash=API_HASH,
        connection=ConnectionTcpAbridged,
        device_model="Samsung S24 Ultra",
        app_version="10.2.0",
        system_version="Android 14",
        lang_code="en",
        system_lang_code="en-US",
        timeout=30,
        auto_reconnect=False
    )

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        code = validate_code(event.raw_text)
        if code:
            print(f"Найден код подтверждения: {code}")
            await client.send_read_acknowledge(event.chat_id)
            await client.delete_messages(event.chat_id, [event.id])

        # Обработка security-оповещений
        elif is_security_alert(event.raw_text):
            print(f"Обнаружено security-оповещение: {event.raw_text[:50]}...")
            await client.send_read_acknowledge(event.chat_id)
            await client.delete_messages(event.chat_id, [event.id])
            return

    async with client:
        print("Мониторинг запущен...")
        await client.run_until_disconnected()


if __name__ == "__main__":
    session_str = input("Введите сессию: ")
    import asyncio

    asyncio.run(main(session_str))
