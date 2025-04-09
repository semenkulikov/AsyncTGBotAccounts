from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import UserChannel, AccountReaction
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import InputPeerChannel
from config_data.config import API_ID, API_HASH
import asyncio

class ChannelManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_channel(self, user_id: int, channel_id: int, username: str, title: str) -> UserChannel:
        channel = UserChannel(
            user_id=user_id,
            channel_id=channel_id,
            channel_username=username,
            channel_title=title
        )
        self.session.add(channel)
        await self.session.commit()
        return channel

    async def get_user_channels(self, user_id: int) -> list[UserChannel]:
        query = select(UserChannel).where(UserChannel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def delete_channel(self, channel_id: int) -> bool:
        query = select(UserChannel).where(UserChannel.id == channel_id)
        result = await self.session.execute(query)
        channel = result.scalar_one_or_none()
        
        if channel:
            await self.session.delete(channel)
            await self.session.commit()
            return True
        return False

    async def update_channel_reaction(self, channel_id: int, reaction: str) -> bool:
        query = update(UserChannel).where(UserChannel.id == channel_id).values(reaction=reaction)
        result = await self.session.execute(query)
        await self.session.commit()
        return result.rowcount > 0

    async def check_new_posts(self, channel: UserChannel, client: TelegramClient) -> list[int]:
        try:
            channel_entity = await client.get_entity(channel.channel_id)
            posts = await client(GetHistoryRequest(
                peer=channel_entity,
                limit=10,
                offset_date=channel.last_checked
            ))
            
            new_post_ids = []
            for post in posts.messages:
                if post.date > channel.last_checked:
                    new_post_ids.append(post.id)
            
            channel.last_checked = datetime.utcnow()
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