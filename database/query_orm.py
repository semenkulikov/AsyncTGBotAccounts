from sqlalchemy.future import select
from database.models import User, Group, Account
from database.models import async_session


async def get_user_by_user_id(user_id: str):
    """ Функция для получения юзера по его Telegram ID """
    async with async_session() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalars().first()

async def get_user_by_id(user_id: int):
    """ Функция для получения юзера по его ID """
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

async def create_user(user_id: str, username: str, first_name: str, last_name: str, is_admin: bool = False):
    """ Функция для создания объекта User """
    async with async_session() as session:
        user = User(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_admin=is_admin
        )
        session.add(user)
        await session.commit()
        return user

async def get_group_by_group_id(group_id: str):
    """ Функция для получения группы по ее ID """
    async with async_session() as session:
        result = await session.execute(select(Group).where(Group.group_id == group_id))
        return result.scalars().first()

async def create_group(group_id: str, title: str, description: str = None, bio: str = None,
                       invite_link: str = None, location: str = None, username: str = None):
    """ Функция для создания объекта Группы """
    async with async_session() as session:
        group = Group(
            group_id=group_id,
            title=title,
            description=description,
            bio=bio,
            invite_link=invite_link,
            location=location,
            username=username
        )
        session.add(group)
        await session.commit()
        return group

async def get_all_users():
    """ Функция для получения всех юзеров """
    async with async_session() as session:
        result = await session.execute(select(User))
        return result.scalars().all()

async def update_user_invoice(user_id: str, invoice_path: str):
    """ Функция для обновления пути """
    async with async_session() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalars().first()
        if user:
            user.path_to_invoice = invoice_path
            await session.commit()
        return user

async def get_account_by_phone(phone: str):
    """ Функция для получения аккаунта по номеру """
    async with async_session() as session:
        result = await session.execute(select(Account).where(Account.phone == phone))
        return result.scalars().first()

async def get_accounts_count_by_user(user_id: str):
    """ Функция для получения количества аккаунтов пользователя. """
    async with async_session() as session:
        result = await session.execute(select(Account).where(Account.user_id == user_id))
        return len(result.scalars().all())
