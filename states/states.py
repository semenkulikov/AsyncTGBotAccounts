from aiogram.fsm.state import StatesGroup, State


class AdminPanel(StatesGroup):
    get_users = State()


class AddAccountStates(StatesGroup):
    wait_phone = State()
    wait_code = State()
    wait_2fa = State()

class AccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

class ChannelStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_reaction = State()
    waiting_for_interval = State()