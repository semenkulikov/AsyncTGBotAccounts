from aiogram.fsm.state import StatesGroup, State


class AdminPanel(StatesGroup):
    get_users = State()
    search_channels = State()
    waiting_for_channel_search = State()


class AddAccountStates(StatesGroup):
    wait_phone = State()
    wait_code = State()
    wait_2fa = State()

class AccountStates(StatesGroup):
    wait_toggle_phone = State()

class ChannelStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_reaction = State()
    waiting_for_interval = State()
    waiting_for_count_reaction = State()
    waiting_for_count_views = State()
    waiting_for_channel_search = State()
