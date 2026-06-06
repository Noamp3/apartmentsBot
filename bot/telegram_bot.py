# bot/telegram_bot.py
"""Main Telegram bot setup and runner."""

from typing import Optional
from telegram.ext import (
    Application, 
    CommandHandler as TGCommandHandler,
    MessageHandler as TGMessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from config import settings
from core.ai_engine import GeminiAIEngine
from bot.handlers.command_handler import CommandHandler
from bot.handlers.admin_command_handler import AdminCommandHandler
from bot.handlers.message_handler import MessageHandler
from bot.handlers.callback_handler import CallbackHandler
from bot.formatters.listing_formatter import ListingFormatter
from utils.logger import Loggers
from database import get_db
from database.repositories.user_repository import UserRepository

log = Loggers.bot()


class ApartmentBot:
    """Main Telegram bot for apartment hunting."""
    
    def __init__(self, token: str = None, ai_engine: GeminiAIEngine = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.ai_engine = ai_engine
        self.application: Optional[Application] = None
        
        # Initialize handlers
        self.command_handler = CommandHandler()
        self.admin_command_handler = AdminCommandHandler()
        self.message_handler = MessageHandler(ai_engine=ai_engine)
        self.callback_handler = CallbackHandler()
        self.formatter = ListingFormatter()
    
    async def setup(self):
        """Initialize and configure the bot."""
        log.info("Setting up Telegram bot")
        
        # Build application
        self.application = Application.builder().token(self.token).build()
        
        # Store AI engine in bot_data for handlers
        self.application.bot_data["ai_engine"] = self.ai_engine
        self.application.bot_data["command_handler"] = self.command_handler
        self.application.bot_data["admin_command_handler"] = self.admin_command_handler
        
        # Store processing service in bot_data (injected from main.py)
        if hasattr(self, "processing_service"):
            self.application.bot_data["processing_service"] = self.processing_service
            
        if hasattr(self, "app_instance"):
            self.application.bot_data["app_instance"] = self.app_instance
        
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
            TGCommandHandler("toggle_bordering", self.command_handler.toggle_bordering)
        )
        self.application.add_handler(
            TGCommandHandler("toggle_roomies", self.command_handler.toggle_roomies)
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
        self.application.add_handler(
            TGCommandHandler("sass", self.command_handler.sass)
        )
        self.application.add_handler(
            TGCommandHandler("persona", self.command_handler.persona)
        )
        self.application.add_handler(
            TGCommandHandler("admin", self.admin_command_handler.admin_panel)
        )
        self.application.add_handler(
            TGCommandHandler("admin_users", self.admin_command_handler.admin_users)
        )
        self.application.add_handler(
            TGCommandHandler("admin_logs", self.admin_command_handler.admin_logs)
        )
        self.application.add_handler(
            TGCommandHandler("admin_broadcast", self.admin_command_handler.admin_broadcast)
        )
        self.application.add_handler(
            TGCommandHandler("admin_scrape", self.admin_command_handler.admin_scrape)
        )
        self.application.add_handler(
            TGCommandHandler("admin_fb_login", self.admin_command_handler.admin_fb_login)
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
        
        # Add global error handler to log tracebacks and notify users clearly
        self.application.add_error_handler(self._error_handler)
        
        # Set commands menu
        try:
            from telegram import BotCommand
            await self.application.bot.set_my_commands([
                BotCommand("start", "Start the bot and get dynamic welcome 🚀"),
                BotCommand("matches", "Search and show matches from last 24h 🔎"),
                BotCommand("status", "Show bot & search statistics 📊"),
                BotCommand("rules", "Show current active search rules 📋"),
                BotCommand("persona", "Change agent persona 👤"),
                BotCommand("rejections", "Show recently rejected listings 🗑️"),
                BotCommand("clear", "Delete all active search rules ⚠️"),
                BotCommand("sass", "Get some custom attitude 💅"),
                BotCommand("help", "Get help and instructions ℹ️"),
            ])
            log.info("Telegram commands menu set successfully")
        except Exception as e:
            log.error(f"Failed to set Telegram commands: {e}")
            
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
        bordering_note: str = "",
        sass_intro: str = ""
    ):
        """Send a listing notification to a user."""
        if not self.application:
            log.error("Bot not initialized")
            return
        
        message = self.formatter.format_listing(enriched, bordering_note, sass_intro)
        
        # Enhanced logging
        try:
            db = await get_db()
            user_repo = UserRepository(db)
            user = await user_repo.get_by_chat_id(chat_id)
            
            user_info = f"User(telegram_id={user.telegram_id}, username={user.username})" if user else f"User(chat_id={chat_id}, UNKNOWN)"
            
            log.info("Sending notification", 
                    chat_id=chat_id, 
                    listing_id=enriched.listing.id,
                    user=user_info)
                    
            if settings.DEBUG:
                log.debug(f"FULL MESSAGE to {user_info}:\n{message}")
                log.debug(f"USER DETAILS: {user}")
                
        except Exception as e:
            log.warning(f"Error fetching user details for logging: {e}")
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='MarkdownV2',
                disable_web_page_preview=False
            )
        except Exception as e:
            log.error("Failed to send notification", 
                     chat_id=chat_id, error=str(e))
            raise e
    
    async def send_message(self, chat_id: int, text: str):
        """Send a plain message to a user."""
        if not self.application:
            return
        
        # Enhanced logging
        try:
            db = await get_db()
            user_repo = UserRepository(db)
            user = await user_repo.get_by_chat_id(chat_id)
            
            user_info = f"User(telegram_id={user.telegram_id}, username={user.username})" if user else f"User(chat_id={chat_id}, UNKNOWN)"
            
            log.info("Sending message", chat_id=chat_id, user=user_info)
            
            if settings.DEBUG:
                log.debug(f"FULL MESSAGE to {user_info}:\n{text}")
                log.debug(f"USER DETAILS: {user}")
                
        except Exception as e:
            log.warning(f"Error fetching user details for logging: {e}")
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=text
            )
        except Exception as e:
            log.error("Failed to send message", chat_id=chat_id, error=str(e))
            
    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log the error and notify the user if possible."""
        import traceback
        from telegram import Update
        
        # Log error message
        log.error(f"Telegram bot exception occurred: {context.error}")
        
        # Format and log the full traceback
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)
        log.error(f"Traceback:\n{tb_string}")
        
        # Notify the user
        if isinstance(update, Update) and update.effective_chat:
            try:
                # Get persona if possible to keep in-character error messages
                persona_name = 'barakush'
                try:
                    db = await get_db()
                    user_repo = UserRepository(db)
                    user = await user_repo.get_by_chat_id(update.effective_chat.id)
                    if user:
                        persona_name = user.persona
                except Exception:
                    pass
                
                fallback = "אופס, משהו השתבש... נסה שוב מאוחר יותר!"
                if persona_name == "barakush":
                    fallback = "אויש, משהו נדפק לי בסיסטם... תני לי דקה להתרענן ונסה שוב! 💅"
                elif persona_name == "yekke":
                    fallback = "שגיאת מערכת פנימית זוהתה. אנא פנה למנהל המערכת או נסה שוב."
                elif persona_name == "mom":
                    fallback = "הכל נפל פה! תעזוב אותי באמאש'ך ותנסה שוב עוד מעט."
                elif persona_name == "stoner":
                    fallback = "יו אחי, הכל הסתבך לי פה... תן לזה דקה ונסה שוב."
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=fallback
                )
            except Exception as e:
                log.error(f"Failed to send error message to user: {e}")
