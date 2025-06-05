# Инициализация сервисов
from config_data.config import ENCRYPTION_KEY
from services.account_manager import AccountService, UserActivityManager

service = AccountService(ENCRYPTION_KEY)
activity_manager = UserActivityManager()

# Устанавливаем account_service для channel_manager
from services.channel_manager import account_service

# Важно! Инициализируем переменную account_service в channel_manager
account_service = service