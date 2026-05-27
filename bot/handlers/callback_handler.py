# bot/handlers/callback_handler.py
"""Inline button callback handlers."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import RuleRepository, UserRepository
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
        
        elif data == "do_clear":
            await self._do_clear(query, user_id)
        
        elif data == "cancel":
            await query.message.delete()
        
        elif data == "confirm_rules_yes":
            await self._confirm_rules_yes(query, context)
        
        elif data == "confirm_rules_no":
            await self._confirm_rules_no(query, context)
            
        elif data.startswith("set_persona:"):
            persona_name = data.split(":")[1]
            await self._set_persona(query, context, persona_name)
    
    async def _delete_rule(self, query, rule_id: int, user_id: int):
        """Delete a specific rule."""
        db = await get_db()
        rule_repo = RuleRepository(db)
        
        rule = await rule_repo.get_by_id(rule_id)
        if rule and rule.user_id == user_id:
            await rule_repo.delete(rule_id)
            await query.edit_message_text("✅ הכלל נמחק בהצלחה")
            log.info("Rule deleted", user_id=user_id, rule_id=rule_id)
            
            # Check if deleting this rule enables new matches
            processing_service = query.message.get_bot().application.bot_data.get("processing_service")
            if processing_service:
                from database.repositories import UserRepository, ListingRepository
                user_repo = UserRepository(db)
                listing_repo = ListingRepository(db)
                
                user = await user_repo.get_by_telegram_id(user_id)
                recent_listings = await listing_repo.get_recent_enrichments(hours=24)
                
                if user and recent_listings:
                    await query.message.reply_text("🔎 בודק אם מחיקת הכלל חשפה דירות חדשות...")
                    matches = await processing_service.match_user_to_listings(user, recent_listings, is_manual_trigger=True)
                    if matches > 0:
                        await query.message.reply_text(f"✨ מצאתי {matches} דירות שפספסנו קודם\\!")
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
        
    async def _do_clear(self, query, user_id: int):
        """Perform clearing all rules."""
        db = await get_db()
        rule_repo = RuleRepository(db)
        await rule_repo.delete_all_user_rules(user_id)
        
        log.info("User cleared all rules via button", user_id=user_id)
        
        # Get user persona
        user_repo = UserRepository(db)
        user_obj = await user_repo.get_by_telegram_id(user_id)
        persona_name = user_obj.persona if user_obj else 'barakush'
        
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        await query.edit_message_text(
            f"🗑️ כל כללי החיפוש שלך נמחקו\\.\n\nשלח הודעה חדשה כדי להתחיל מחדש\\!",
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
    
    async def _confirm_rules_yes(self, query, context: ContextTypes.DEFAULT_TYPE):
        """User confirmed rules - save all pending rules."""
        from database.repositories import UserRepository
        from models.search_rule import SearchRule
        
        pending_data = context.user_data.get('pending_rule_confirmation')
        if not pending_data:
            await query.edit_message_text("❌ לא נמצאו כללים ממתינים")
            return
        
        
        user_id = query.from_user.id if query.from_user else pending_data.get('user_id')
        # pending_rules is a list of SearchRule objects that were created but not saved
        all_pending_rules = pending_data.get('all_pending_rules', [])
        
        # If we have legacy data structure (just one type of rules), handle backward compat or just rules_data
        # But for now we rely on the new structure
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        
        added_count = 0
        
        # We need to handle conflicts for the pending rules just like we did in message_handler
        # but now we are actually saving them.
        existing_rules = await rule_repo.get_user_rules(user_id, active_only=True)
        
        for rule in all_pending_rules:
            # Re-check conflicts because state might have changed (race condition unlikely but good practice)
            should_save = True
            
            if rule.is_hard_rule:
                for existing in existing_rules:
                    if existing.rule_type == rule.rule_type and existing.is_active:
                         await rule_repo.delete(existing.id)
            
            elif rule.is_soft_rule:
                for existing in existing_rules:
                    if (existing.rule_type == rule.rule_type and 
                        existing.is_active and 
                        existing.value == rule.value):
                        should_save = False
                        break
            
            if should_save:
                # We need to re-bind the rule to the DB session if it was detached?
                # Actually SearchRule is just a model instance. rule_repo.create takes the model.
                await rule_repo.create(rule)
                added_count += 1
        
        # Clear pending state
        context.user_data.pop('pending_rule_confirmation', None)
        
        sass_response = pending_data.get('sass_response', '')
        escaped_sass = self._escape_markdown(sass_response) if sass_response else "_יאללה, קדימה לחפש\\!_"
        
        response = f"""
✅ *מעולה\\! שמרתי {added_count} כללים*

{escaped_sass}
"""
        
        await self._safe_edit_message_text(query, response, parse_mode='MarkdownV2')
        log.info(f"Rules confirmed and saved", user_id=user_id, count=added_count)
        
        # Trigger immediate matching with new rules
        processing_service = context.bot_data.get("processing_service")
        if processing_service:
            from database.repositories import ListingRepository
            listing_repo = ListingRepository(db)
            user_repo = UserRepository(db)
            
            user = await user_repo.get_by_telegram_id(user_id)
            recent_listings = await listing_repo.get_recent_enrichments(hours=24)
            
            if user and recent_listings:
                await query.message.reply_text("🔎 בודק אם יש משהו רלוונטי מהיממה האחרונה...")
                matches = await processing_service.match_user_to_listings(
                    user, recent_listings, is_manual_trigger=True
                )
                if matches > 0:
                    await query.message.reply_text(f"✨ מצאתי {matches} שידוכים קודמים\!")
    
    async def _confirm_rules_no(self, query, context: ContextTypes.DEFAULT_TYPE):
        """User declined - clear pending rules and ask to try again."""
        # Clear pending state
        context.user_data.pop('pending_rule_confirmation', None)
        
        response = """
❌ בסדר מאמי, ביטלתי את הכללים. 

נסה שוב להגדיר מה את/ה מחפש/ת 🏠
"""
        
        await query.edit_message_text(response)
        log.info("Rules declined by user", user_id=query.from_user.id)
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special Markdown V2 characters."""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', 
                        '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    async def _safe_edit_message_text(self, query, text: str, parse_mode: str = None):
        """Edit message safely, handling Markdown errors gracefully."""
        from telegram.error import BadRequest
        try:
            await query.edit_message_text(text, parse_mode=parse_mode)
        except BadRequest as e:
            if "can't parse entities" in str(e).lower():
                log.exception(f"Markdown parsing failed in callback. Message: {text[:200]}...")
                # Fallback to plain text
                fallback_text = text.replace("_", "").replace("*", "").replace("\\", "") + "\n\n(שגיאת עיצוב)"
                try:
                    await query.edit_message_text(fallback_text, parse_mode=None)
                except Exception as e2:
                    log.error(f"Failed to send fallback message: {e2}")
            else:
                log.error(f"Telegram API error editing message: {e}")
                raise e
        except Exception as e:
            log.error(f"Unexpected error editing message: {e}")
    
    @staticmethod
    def create_rules_confirmation_keyboard() -> InlineKeyboardMarkup:
        """Create keyboard for rule confirmation."""
        keyboard = [
            [
                InlineKeyboardButton("✅ כן, נכון", callback_data="confirm_rules_yes"),
                InlineKeyboardButton("❌ לא, ביטול", callback_data="confirm_rules_no"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
        
    async def _set_persona(self, query, context: ContextTypes.DEFAULT_TYPE, persona_name: str):
        """Switch user persona and reply with custom message."""
        user_id = query.from_user.id
        
        db = await get_db()
        user_repo = UserRepository(db)
        await user_repo.update_persona(user_id, persona_name)
        
        log.info(f"User changed persona to {persona_name}", user_id=user_id)
        
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        escaped_msg = self._escape_markdown(persona_def.switch_confirmation)
        
        await query.edit_message_text(
            escaped_msg,
            parse_mode='MarkdownV2'
        )
