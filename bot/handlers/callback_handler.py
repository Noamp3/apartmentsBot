# bot/handlers/callback_handler.py
"""Inline button callback handlers."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import RuleRepository
from utils.logger import Loggers

log = Loggers.bot()


class CallbackHandler:
    """Handles inline button callbacks."""
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process inline button callbacks."""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        
        log.info("Callback received", user_id=user_id, data=data)
        
        if data.startswith("delete_rule:"):
            rule_id = int(data.split(":")[1])
            await self._delete_rule(query, rule_id, user_id)
        
        elif data == "show_more_rejections":
            await self._show_more_rejections(query, user_id)
        
        elif data == "confirm_clear":
            await self._confirm_clear(query, user_id)
        
        elif data == "cancel":
            await query.message.delete()
    
    async def _delete_rule(self, query, rule_id: int, user_id: int):
        """Delete a specific rule."""
        db = await get_db()
        rule_repo = RuleRepository(db)
        
        rule = await rule_repo.get_by_id(rule_id)
        if rule and rule.user_id == user_id:
            await rule_repo.delete(rule_id)
            await query.edit_message_text("✅ הכלל נמחק בהצלחה")
            log.info("Rule deleted", user_id=user_id, rule_id=rule_id)
        else:
            await query.edit_message_text("❌ לא נמצא כלל למחיקה")
    
    async def _show_more_rejections(self, query, user_id: int):
        """Show more rejected listings."""
        from database.repositories import RejectionRepository
        from bot.formatters.listing_formatter import ListingFormatter
        
        db = await get_db()
        rejection_repo = RejectionRepository(db)
        rejections = await rejection_repo.get_user_rejections(user_id, limit=20)
        
        message = ListingFormatter.format_rejections_summary(rejections)
        await query.edit_message_text(message, parse_mode='MarkdownV2')
    
    async def _confirm_clear(self, query, user_id: int):
        """Confirm clearing all rules."""
        keyboard = [
            [
                InlineKeyboardButton("✅ כן, מחק הכל", callback_data="do_clear"),
                InlineKeyboardButton("❌ ביטול", callback_data="cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⚠️ *האם אתה בטוח שברצונך למחוק את כל הכללים?*",
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
    
    @staticmethod
    def create_rule_keyboard(rules: list) -> InlineKeyboardMarkup:
        """Create keyboard for rule management."""
        keyboard = []
        
        for rule in rules:
            text = f"🗑️ {rule.original_text[:30]}"
            callback = f"delete_rule:{rule.id}"
            keyboard.append([InlineKeyboardButton(text, callback_data=callback)])
        
        keyboard.append([InlineKeyboardButton("🗑️ מחק הכל", callback_data="confirm_clear")])
        
        return InlineKeyboardMarkup(keyboard)
