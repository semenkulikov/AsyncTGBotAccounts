# Инициализация сервисов
from config_data.config import ENCRYPTION_KEY
from services.account_manager import AccountService, UserActivityManager

service = AccountService(ENCRYPTION_KEY)
activity_manager = UserActivityManager()