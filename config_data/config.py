import os
from dotenv import load_dotenv, find_dotenv

if not find_dotenv():
    exit('Переменные окружения не загружены, так как отсутствует файл .env')
else:
    load_dotenv()


DEFAULT_COMMANDS = (
    ('start', "Запустить бота"),
    ('help', "Вывести справку"),
    ("add_account", "Добавить аккаунт"),
    ('my_accounts', "Мои аккаунты"),
    ('my_channels', "Мои каналы"),
    ('toggle_account', "Изменить статус аккаунта (Вкл\Выкл)")
)
ADMIN_COMMANDS = (
    ("admin_panel", "Админка"),
)

ADMIN_ID = int(os.getenv('ADMIN_ID'))
ALLOWED_USERS = [int(ADMIN_ID)]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOT_TOKEN = os.getenv('BOT_TOKEN')
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

CHECK_INTERVAL_MIN = 60  # 10 минут
CHECK_INTERVAL_MAX = 360 # 1 час

DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(BASE_DIR, 'database', 'accounts.db')}"
