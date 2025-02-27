from aiogram.fsm.state import StatesGroup, State


class AdminPanel(StatesGroup):
    get_users = State()
