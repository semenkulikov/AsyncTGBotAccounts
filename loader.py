import os
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from config_data.config import BOT_TOKEN, BASE_DIR

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=storage)

# Настройка логирования

log_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s - %(message)s')
logs_path = os.path.join(BASE_DIR, "logs")

if not os.path.exists(logs_path):
    os.makedirs(logs_path)

file_handler = RotatingFileHandler(
    os.path.join(logs_path, "bot.log"),
    mode='a', maxBytes=2*1024*1024, backupCount=1, encoding="utf8"
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.INFO)

app_logger = logging.getLogger("app_logger")
app_logger.setLevel(logging.INFO)
app_logger.addHandler(file_handler)
app_logger.addHandler(stream_handler)
