# bot/handlers/bot_utils.py
"""Helper utilities for Telegram bot handlers."""

from telegram import Update
from telegram.error import BadRequest
from utils.logger import Loggers

log = Loggers.bot()


async def safe_reply_text(update: Update, text: str, parse_mode: str = None, **kwargs):
    """Send message safely, handling Markdown errors gracefully."""
    try:
        await update.message.reply_text(text, parse_mode=parse_mode, **kwargs)
    except BadRequest as e:
        if "can't parse entities" in str(e).lower():
            log.exception(f"Markdown parsing failed for message: {text[:200]}... Falling back to plain text.")
            # Fallback to plain text
            fallback_text = text.replace("_", "").replace("*", "").replace("\\", "").replace("[", "").replace("]", "").replace("(", "").replace(")", "") + "\n\n(שגיאת עיצוב)"
            try:
                await update.message.reply_text(fallback_text, parse_mode=None, **kwargs)
            except Exception as e2:
                log.error(f"Failed to send fallback message: {e2}")
        else:
            log.error(f"Telegram API error sending message: {e}")
            raise e
    except Exception as e:
        log.error(f"Unexpected error sending message: {e}")


async def safe_edit_message_text(query, text: str, parse_mode: str = None, **kwargs):
    """Edit message safely, handling Markdown errors gracefully."""
    try:
        await query.edit_message_text(text, parse_mode=parse_mode, **kwargs)
    except BadRequest as e:
        if "can't parse entities" in str(e).lower():
            log.exception(f"Markdown parsing failed in callback/edit. Message: {text[:200]}...")
            # Fallback to plain text
            fallback_text = text.replace("_", "").replace("*", "").replace("\\", "").replace("[", "").replace("]", "").replace("(", "").replace(")", "") + "\n\n(שגיאת עיצוב)"
            try:
                await query.edit_message_text(fallback_text, parse_mode=None, **kwargs)
            except Exception as e2:
                log.error(f"Failed to edit fallback message: {e2}")
        else:
            log.error(f"Telegram API error editing message: {e}")
            raise e
    except Exception as e:
        log.error(f"Unexpected error editing message: {e}")
