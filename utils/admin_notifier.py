# utils/admin_notifier.py
"""Logging handler to notify administrators of errors and exceptions via Telegram."""

import logging
import asyncio
import time
import sys
import html
import traceback
from typing import List, Optional

# Dedicated logger for the notifier to prevent recursion
notifier_log = logging.getLogger("apt_bot.admin_notifier")
notifier_log.propagate = False  # DO NOT propagate to root logger!

class TelegramAdminNotificationHandler(logging.Handler):
    """Logging handler that sends ERROR and CRITICAL log messages to bot administrators."""
    
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.bot = None
        self._notification_timestamps: List[float] = []
        self._is_sending = False
        
        # Set a standard formatter to capture time, level, logger, message, and traceback
        self.setFormatter(logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s:\n%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))

    def set_bot(self, bot):
        """Set the bot instance for sending messages."""
        self.bot = bot
        notifier_log.info("Telegram bot instance bound to admin error notification handler.")

    def emit(self, record: logging.LogRecord):
        # Do not process if bot is not configured
        if not self.bot:
            return
            
        # Avoid recursion from notifier logger or special recursion flags
        if record.name == "apt_bot.admin_notifier" or getattr(record, "_from_notifier", False):
            return
            
        # Prevent re-entry if we're currently in the process of sending
        if self._is_sending:
            return
            
        try:
            now = time.time()
            # Prune timestamps older than 1 hour (3600 seconds)
            self._notification_timestamps = [t for t in self._notification_timestamps if now - t < 3600]
            
            # Check rate limit: maximum 5 notifications in an hour
            if len(self._notification_timestamps) >= 5:
                # Direct print to stderr to avoid logging propagation/recursion
                sys.stderr.write(
                    f"[AdminNotifier] Notification rate limit reached (5/hour). Log error ignored: {record.getMessage()}\n"
                )
                return
                
            # Register timestamp synchronously to prevent race conditions in rapid emissions
            self._notification_timestamps.append(now)
            self._is_sending = True
            
            # Format the log record (includes traceback if present)
            message = self.format(record)
            
            # Get the running event loop to schedule sending asynchronously
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
                
            if loop and loop.is_running():
                loop.create_task(self._notify_admins(message, now))
            else:
                sys.stderr.write(
                    f"[AdminNotifier] No running event loop. Could not send error: {record.getMessage()}\n"
                )
        except Exception as e:
            sys.stderr.write(f"[AdminNotifier] Error in emit: {e}\n")
            traceback.print_exc(file=sys.stderr)
        finally:
            self._is_sending = False

    async def _notify_admins(self, message: str, now: float):
        # Double check bot and prevent re-entry
        if not self.bot:
            return
            
        try:
            from database import get_db
            db = await get_db()
            
            # Retrieve all administrator chat IDs
            admin_rows = await db.fetch_all("SELECT chat_id FROM users WHERE is_admin = 1")
            if not admin_rows:
                return
                
            # Truncate message to avoid exceeding Telegram's 4096 character limit
            max_len = 3500
            truncated_msg = message
            if len(message) > max_len:
                truncated_msg = message[:max_len] + "\n...(truncated)"
                
            # Format using HTML block representation
            formatted_text = (
                f"🚨 <b>שגיאת מערכת / Exception Detected</b>\n\n"
                f"<pre>{html.escape(truncated_msg)}</pre>"
            )
            
            sent_to_any = False
            for row in admin_rows:
                chat_id = row["chat_id"]
                try:
                    await self.bot.application.bot.send_message(
                        chat_id=chat_id,
                        text=formatted_text,
                        parse_mode='HTML'
                    )
                    sent_to_any = True
                except Exception as send_err:
                    # Fallback to plain text if HTML parsing has issues
                    try:
                        await self.bot.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"🚨 שגיאת מערכת / Exception Detected:\n\n{truncated_msg}"
                        )
                        sent_to_any = True
                    except Exception as fallback_err:
                        sys.stderr.write(
                            f"[AdminNotifier] Failed to notify admin {chat_id}: {fallback_err}\n"
                        )
                        
            # If sending failed for all admins, remove the timestamp so we don't block subsequent messages
            if not sent_to_any:
                try:
                    self._notification_timestamps.remove(now)
                except ValueError:
                    pass
                
        except Exception as err:
            sys.stderr.write(f"[AdminNotifier] Error in _notify_admins: {err}\n")
            traceback.print_exc(file=sys.stderr)


# Global instance to be imported and registered
admin_notifier_handler = TelegramAdminNotificationHandler()
