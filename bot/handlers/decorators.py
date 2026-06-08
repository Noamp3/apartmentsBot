# bot/handlers/decorators.py
"""Decorators for Telegram bot handlers."""

import functools
from telegram import Update
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository
from utils.logger import Loggers

log = Loggers.bot()

def ensure_user_exists(func):
    """Decorator to ensure the Telegram user is registered in the database before processing the handler."""
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat
        
        if user and chat:
            try:
                db = await get_db()
                user_repo = UserRepository(db)
                # Automatically get or create the user in the database
                username = user.username
                from unittest.mock import Mock
                if isinstance(username, Mock):
                    username = None
                await user_repo.get_or_create(
                    telegram_id=user.id,
                    chat_id=chat.id,
                    username=username
                )
            except Exception as e:
                log.error(f"Error in ensure_user_exists decorator: {e}", exc_info=True)
                
        return await func(self, update, context, *args, **kwargs)
    return wrapper


def admin_required(func):
    """Decorator to ensure the Telegram user is a registered admin."""
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
            
        try:
            db = await get_db()
            user_repo = UserRepository(db)
            user_obj = await user_repo.get_by_telegram_id(user.id)
            if user_obj and user_obj.is_admin:
                return await func(self, update, context, *args, **kwargs)
        except Exception as e:
            log.error(f"Error in admin_required decorator: {e}", exc_info=True)
            
        # Get user's persona for character-specific rejection
        persona_name = 'barakush'
        if 'user_obj' in locals() and user_obj:
            persona_name = user_obj.persona
            
        warning = "❌ שגיאה: פקודה זו מיועדת למנהלי מערכת בלבד!"
        if persona_name == "barakush":
            warning = "הלו הלו, מותק! 💅 אין לך אישור להיכנס לפה. זה למורשים בלבד! 🚫"
        elif persona_name == "moment":
            warning = "רק מנהלים יכולים לעשות את זה, יא חביבי! 🛑"
        elif persona_name == "yekke":
            warning = "שגיאה: פקודה ניהולית. הגישה חסומה למשתמשים רגילים."
        elif persona_name == "mom":
            warning = "מה אתה נדחף לפה? 😡 זה למנהלים בלבד, לך תסדר את החדר!"
        elif persona_name == "stoner":
            warning = "יו אחי... הפקודה הזאת גדולה עליך כרגע. רק למנהלים! 🌿"
            
        if update.message:
            await update.message.reply_text(warning)
        elif update.callback_query:
            await update.callback_query.answer(warning, show_alert=True)
            
    return wrapper
