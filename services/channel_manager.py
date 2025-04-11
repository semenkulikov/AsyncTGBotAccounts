from datetime import datetime, timedelta, UTC
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import UserChannel, AccountReaction
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import InputPeerChannel
from config_data.config import API_ID, API_HASH
import asyncio
from database.query_orm import get_user_by_user_id

class ChannelManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_channels(self, user_id: int) -> List[UserChannel]:
        """Получает список каналов пользователя"""
        query = select(UserChannel).where(UserChannel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def add_channel(
        self,
        user_id: int,
        channel_id: int,
        username: str,
        title: str
    ) -> bool:
        """Добавляет новый канал для пользователя"""
        try:
            channel = UserChannel(
                user_id=user_id,
                channel_id=channel_id,
                channel_username=username,
                channel_title=title,
                is_active=True
            )
            self.session.add(channel)
            await self.session.commit()
            return True
        except Exception as e:
            await self.session.rollback()
            raise e

    async def delete_channel(self, channel_id: int) -> bool:
        """Удаляет канал"""
        try:
            query = select(UserChannel).where(UserChannel.id == channel_id)
            result = await self.session.execute(query)
            channel = result.scalar_one_or_none()
            
            if channel:
                # Удаляем все реакции канала
                await self.session.execute(
                    select(AccountReaction).where(AccountReaction.channel_id == channel_id)
                )
                await self.session.delete(channel)
                await self.session.commit()
                return True
            return False
        except Exception as e:
            await self.session.rollback()
            raise e

    async def update_channel_reaction(self, channel_id: int, reaction: str) -> bool:
        """Обновляет реакцию для канала"""
        try:
            # Создаем новую реакцию
            new_reaction = AccountReaction(
                channel_id=channel_id,
                reaction=reaction,
                reacted_at=datetime.now(UTC)
            )
            self.session.add(new_reaction)
            await self.session.commit()
            return True
        except Exception as e:
            await self.session.rollback()
            raise e

    async def get_channel_reactions(self, channel_id: int) -> List[AccountReaction]:
        """Получает все реакции для канала"""
        query = select(AccountReaction).where(AccountReaction.channel_id == channel_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_last_reaction(self, channel_id: int) -> Optional[AccountReaction]:
        """Получает последнюю реакцию для канала"""
        query = select(AccountReaction).where(
            AccountReaction.channel_id == channel_id
        ).order_by(AccountReaction.reacted_at.desc())
        result = await self.session.execute(query)
        return result.scalars().first()

    async def check_new_posts(self, channel: UserChannel, client: TelegramClient) -> list[int]:
        try:
            # Получаем последние сообщения из канала
            messages = await client.get_messages(
                channel.channel_id,
                limit=10
            )
            
            new_post_ids = []
            for message in messages:
                # Добавляем часовой пояс UTC к message.date
                message_date = message.date.replace(tzinfo=UTC)
                if message_date > channel.last_checked.replace(tzinfo=UTC):
                    new_post_ids.append(message.id)
            
            channel.last_checked = datetime.now(UTC)
            await self.session.commit()
            
            return new_post_ids
        except Exception as e:
            print(f"Error checking posts for channel {channel.channel_id}: {e}")
            return []

    async def set_reaction(self, client: TelegramClient, channel_id: int, post_id: int, reaction: str) -> bool:
        try:
            await client.send_reaction(
                entity=channel_id,
                message=post_id,
                reaction=reaction
            )
            return True
        except Exception as e:
            print(f"Error setting reaction: {e}")
            return False

    async def process_channel_posts(self, channel: UserChannel, accounts: list) -> None:
        for account in accounts:
            if not account.is_active:
                continue
                
            async with TelegramClient(
                f'sessions/{account.phone}',
                API_ID,
                API_HASH
            ) as client:
                new_posts = await self.check_new_posts(channel, client)
                
                for post_id in new_posts:
                    success = await self.set_reaction(
                        client,
                        channel.channel_id,
                        post_id,
                        channel.reaction
                    )
                    
                    if success:
                        reaction = AccountReaction(
                            account_id=account.id,
                            channel_id=channel.id,
                            post_id=post_id,
                            reaction=channel.reaction
                        )
                        self.session.add(reaction)
                        await self.session.commit()
                        
                    await asyncio.sleep(5)  # Задержка между реакциями 