# bot/notifications/dispatcher.py
"""Notification provider and dispatch architecture."""

import asyncio
from abc import ABC, abstractmethod
from typing import List
from models.listing import EnrichedListing
from utils.logger import Loggers

log = Loggers.bot()


class BaseNotificationProvider(ABC):
    """Abstract base class for all notification delivery channels."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider channel (e.g. 'telegram')."""
        pass
        
    @abstractmethod
    async def send_notification(self, chat_id: int, enriched: EnrichedListing, sass_intro: str = "") -> bool:
        """Send notification to the specified recipient.
        
        Returns:
            bool: True if sent successfully, False otherwise.
        """
        pass


class TelegramNotificationProvider(BaseNotificationProvider):
    """Notification provider implementing delivery via Telegram bot."""
    
    def __init__(self, bot):
        self.bot = bot
        
    @property
    def name(self) -> str:
        return "telegram"
        
    async def send_notification(self, chat_id: int, enriched: EnrichedListing, sass_intro: str = "") -> bool:
        """Send notification via Telegram."""
        # Allow exceptions to propagate to the dispatcher
        await self.bot.send_listing_notification(
            chat_id=chat_id,
            enriched=enriched,
            sass_intro=sass_intro
        )
        return True


class NotificationDispatcher:
    """Coordinates dispatching matching notifications to registered channels."""
    
    def __init__(self):
        self.providers: List[BaseNotificationProvider] = []
        
    def register_provider(self, provider: BaseNotificationProvider):
        """Register a delivery provider channel."""
        self.providers.append(provider)
        log.info(f"Registered notification provider: {provider.name}")
        
    async def dispatch(self, chat_id: int, enriched: EnrichedListing, sass_intro: str = "") -> int:
        """Send notification across all registered providers.
        
        Returns:
            int: Number of successfully delivered notification channels.
        """
        if not self.providers:
            log.warning("No notification providers registered with the dispatcher!")
            return 0
            
        success_count = 0
        tasks = [provider.send_notification(chat_id, enriched, sass_intro) for provider in self.providers]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        exceptions = []
        
        for idx, result in enumerate(results):
            provider_name = self.providers[idx].name
            if isinstance(result, Exception):
                log.error(f"Provider {provider_name} raised exception during dispatch: {result}")
                exceptions.append(result)
            elif result is True:
                success_count += 1
                
        # Re-raise critical exceptions (like user blocked/deleted) so that
        # the processing layer can handle user cleanup (e.g. deleting the user).
        for exc in exceptions:
            exc_str = str(exc)
            if "Chat not found" in exc_str or "Forbidden" in exc_str or "Unauthorized" in exc_str:
                raise exc
                
        return success_count
