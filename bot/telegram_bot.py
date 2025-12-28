# bot/telegram_bot.py
"""Main Telegram bot setup and runner."""

from typing import Optional
from telegram.ext import (
    Application, 
    CommandHandler as TGCommandHandler,
    MessageHandler as TGMessageHandler,
    CallbackQueryHandler,
    filters
)

from config import settings
from core.ai_engine import GeminiAIEngine
from bot.handlers.command_handler import CommandHandler
from bot.handlers.message_handler import MessageHandler
from bot.handlers.callback_handler import CallbackHandler
from bot.formatters.listing_formatter import ListingFormatter
from utils.logger import Loggers

log = Loggers.bot()


class ApartmentBot:
    """Main Telegram bot for apartment hunting."""
    
    def __init__(self, token: str = None, ai_engine: GeminiAIEngine = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.ai_engine = ai_engine
        self.application: Optional[Application] = None
        
        # Initialize handlers
        self.command_handler = CommandHandler()
        self.message_handler = MessageHandler(ai_engine=ai_engine)
        self.callback_handler = CallbackHandler()
        self.formatter = ListingFormatter()
    
    async def setup(self):
        """Initialize and configure the bot."""
        log.info("Setting up Telegram bot")
        
        # Build application
        self.application = Application.builder().token(self.token).build()
        
        # Add command handlers
        self.application.add_handler(
            TGCommandHandler("start", self.command_handler.start)
        )
        self.application.add_handler(
            TGCommandHandler("help", self.command_handler.help)
        )
        self.application.add_handler(
            TGCommandHandler("rules", self.command_handler.rules)
        )
        self.application.add_handler(
            TGCommandHandler("rejections", self.command_handler.rejections)
        )
        self.application.add_handler(
            TGCommandHandler("clear", self.command_handler.clear)
        )
        self.application.add_handler(
            TGCommandHandler("status", self.command_handler.status)
        )
        self.application.add_handler(
            TGCommandHandler("matches", self.command_handler.matches)
        )
        
        # Add message handler for natural language
        self.application.add_handler(
            TGMessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.message_handler.handle_message
            )
        )
        
        # Add callback handler for inline buttons
        self.application.add_handler(
            CallbackQueryHandler(self.callback_handler.handle_callback)
        )
        
        log.info("Bot setup complete")
    
    async def run(self):
        """Start the bot (polling mode)."""
        if not self.application:
            await self.setup()
        
        log.info("Starting bot in polling mode")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
    
    async def stop(self):
        """Stop the bot."""
        if self.application:
            log.info("Stopping bot")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
    
    async def send_listing_notification(
        self, 
        chat_id: int, 
        enriched: 'EnrichedListing',
        bordering_note: str = ""
    ):
        """Send a listing notification to a user."""
        if not self.application:
            log.error("Bot not initialized")
            return
        
        message = self.formatter.format_listing(enriched, bordering_note)
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='MarkdownV2',
                disable_web_page_preview=False
            )
            log.info("Notification sent", 
                    chat_id=chat_id, 
                    listing_id=enriched.listing.id)
        except Exception as e:
            log.error("Failed to send notification", 
                     chat_id=chat_id, error=str(e))
    
    async def send_message(self, chat_id: int, text: str):
        """Send a plain message to a user."""
        if not self.application:
            return
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=text
            )
        except Exception as e:
            log.error("Failed to send message", chat_id=chat_id, error=str(e))
