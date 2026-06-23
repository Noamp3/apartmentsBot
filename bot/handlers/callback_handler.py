# bot/handlers/callback_handler.py
"""Inline button callback handlers."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import html
import os
from pathlib import Path

from config import settings
from database import get_db
from database.repositories import RuleRepository, UserRepository
from utils.logger import Loggers
from bot.handlers.decorators import ensure_user_exists

log = Loggers.bot()


class CallbackHandler:
    """Handles inline button callbacks."""
    
    @ensure_user_exists
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
            
        elif data == "toggle_bordering":
            await self._toggle_bordering(query, user_id)
            
        elif data == "toggle_roomies":
            await self._toggle_roomies(query, user_id)
            
        elif data == "toggle_sublets":
            await self._toggle_sublets(query, user_id)
            
        elif data.startswith("set_persona:"):
            persona_name = data.split(":")[1]
            await self._set_persona(query, context, persona_name)
            
        elif data.startswith("admin_"):
            db = await get_db()
            user_repo = UserRepository(db)
            user_obj = await user_repo.get_by_telegram_id(user_id)
            if not user_obj or not user_obj.is_admin:
                await query.answer("שגיאה: אין לך הרשאות ניהול!", show_alert=True)
                return
            
            # Sub-menus routing
            if data == "admin_menu_main":
                await self._show_admin_dashboard(query, context)
            elif data == "admin_menu_users":
                await self._show_admin_users(query, context)
            elif data == "admin_menu_recent_listings":
                await self._show_admin_recent_listings(query, context)
            elif data == "admin_menu_logs":
                await self._show_admin_logs(query, context)
            elif data.startswith("admin_menu_fb"):
                await self._show_admin_fb_menu(update, context)
            elif data == "admin_menu_change_frequency_prompt":
                await self._show_change_frequency_prompt(update, context)
            elif data.startswith("admin_menu_set_frequency:"):
                mins = int(data.split(":")[1])
                await self._set_frequency(update, context, mins)
            elif data == "admin_menu_toggle_auto_adjust":
                await self._toggle_auto_adjust(update, context)
            elif data == "admin_menu_clear":
                await self._show_admin_clear_menu(query, context)
            elif data == "admin_menu_server":
                await self._show_admin_server_stats(query, context)
            elif data == "admin_menu_gemini":
                await self._show_admin_gemini_test(query, context)
            elif data == "admin_menu_change_retries_prompt":
                await self._show_change_retries_prompt(update, context)
            elif data == "admin_broadcast_prompt":
                await self._prompt_admin_broadcast(query, context)
            elif data.startswith("admin_clear_table:"):
                table_name = data.split(":")[1]
                await self._confirm_clear_table_prompt(query, table_name)
            elif data.startswith("admin_do_clear_table:"):
                table_name = data.split(":")[1]
                await self._do_clear_table(query, table_name)
            elif data.startswith("admin_view_user:"):
                user_id_to_view = int(data.split(":")[1])
                await self._show_admin_user_detail(query, context, user_id_to_view)
            elif data.startswith("admin_user_rules:"):
                user_id_to_view = int(data.split(":")[1])
                await self._show_admin_user_rules(query, context, user_id_to_view)
            elif data.startswith("admin_user_matches:"):
                user_id_to_view = int(data.split(":")[1])
                await self._show_admin_user_matches(query, context, user_id_to_view)
    
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
                        from core.personas import get_persona
                        p = get_persona(user.persona)
                        await query.message.reply_text(p.no_matches_found)
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
        
        # Reset onboarding step to choose_persona
        user_repo = UserRepository(db)
        await user_repo.update_onboarding_step(user_id, "choose_persona")
        
        # Prompt for persona selection to start over
        from core.personas import PERSONAS
        keyboard = []
        msg = "🗑️ *כל כללי החיפוש שלך נמחקו\\.*\nבוא נגדיר את החיפוש מחדש\\! מי הנציג שאתה רוצה שילווה אותך?"
        for name, p in PERSONAS.items():
            keyboard.append([
                InlineKeyboardButton(f"{p.emoji} {p.display_name}", callback_data=f"set_persona:{name}")
            ])
            
        await query.edit_message_text(
            msg,
            parse_mode='MarkdownV2',
            reply_markup=InlineKeyboardMarkup(keyboard)
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
        
        # Delete rules marked for deletion first (replaces modified active rules)
        rules_to_delete = pending_data.get('rules_to_delete', [])
        for r_id in rules_to_delete:
            await rule_repo.delete(r_id)
            
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
                    await query.message.reply_text(f"✨ מצאתי {matches} שידוכים קודמים\\!")
                else:
                    from core.personas import get_persona
                    p = get_persona(user.persona)
                    await query.message.reply_text(p.no_matches_found)
    
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
        """Escape special Markdown V2 characters (using central helper)."""
        from utils.text_utils import escape_markdown
        return escape_markdown(text)
    
    async def _safe_edit_message_text(self, query, text: str, parse_mode: str = None):
        """Edit message safely, handling Markdown errors gracefully (using central helper)."""
        from bot.handlers.bot_utils import safe_edit_message_text
        await safe_edit_message_text(query, text, parse_mode=parse_mode)
    
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
        
        user_obj = await user_repo.get_by_telegram_id(user_id)
        is_onboarding = user_obj and user_obj.onboarding_step == "choose_persona"
        
        if is_onboarding:
            await user_repo.update_onboarding_step(user_id, "ask_location")
            context.user_data['onboarding_rules'] = []
            
            # Since these static templates are already perfectly pre-escaped in personas.py,
            # we send them directly without dynamic escaping to preserve rich bold/italic formatting.
            escaped_msg = f"{persona_def.switch_confirmation}\n\n{persona_def.onboarding_welcome}"
        else:
            escaped_msg = persona_def.switch_confirmation
        
        await query.edit_message_text(
            escaped_msg,
            parse_mode='MarkdownV2'
        )

    async def _confirm_clear_table_prompt(self, query, table_name: str):
        """Show prompt to confirm dropping/clearing a table."""
        keyboard = [
            [
                InlineKeyboardButton("💥 כן, נקה לגמרי", callback_data=f"admin_do_clear_table:{table_name}"),
                InlineKeyboardButton("❌ ביטול", callback_data="cancel")
            ]
        ]
        
        # Friendly table names in Hebrew
        table_names_he = {
            "seen_listings": "היסטוריית סריקה (Seen listings)",
            "enriched_listings": "דירות מועשרות (Enriched)",
            "rejection_logs": "יומני פסילות (Rejections)",
            "ai_cache": "מטמון AI (Cache)",
            "users": "כל המשתמשים, הכללים והיסטוריית ההודעות (Reset All Users)"
        }
        
        he_name = table_names_he.get(table_name, table_name)
        
        await query.edit_message_text(
            f"⚠️ <b>אזהרה חמורה!</b>\n\nהאם אתה בטוח שברצונך למחוק ולאפס את הטבלה: <b>{html.escape(he_name)}</b>?\n\nפעולה זו תמחק את כל הנתונים ולא ניתן לשחזר אותם!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
    async def _do_clear_table(self, query, table_name: str):
        """Execute the table clear (drop + initialize)."""
        db = await get_db()
        
        try:
            # Drop dependent tables in correct order
            tables_to_drop = []
            if table_name == "users":
                tables_to_drop = ["rejection_logs", "search_rules", "sent_notifications", "users"]
            elif table_name == "seen_listings":
                tables_to_drop = ["listing_fingerprints", "seen_listings"]
            else:
                tables_to_drop = [table_name]
                
            for table in tables_to_drop:
                await db.connection.execute(f"DROP TABLE IF EXISTS {table}")
                
            await db.connection.commit()
            
            # Recreate dropped tables and indexes
            await db.initialize()
            
            # Re-register the current admin if users was dropped so they don't lock themselves out
            if table_name == "users":
                user_repo = UserRepository(db)
                await user_repo.get_or_create(
                    telegram_id=query.from_user.id,
                    chat_id=query.message.chat_id if query.message else query.from_user.id,
                    username=query.from_user.username
                )
                
            await query.edit_message_text(f"✅ הטבלה/ות `{table_name}` אופסו ונבנו מחדש בהצלחה!")
            log.info(f"Admin cleared table: {table_name}", user_id=query.from_user.id)
        except Exception as e:
            log.error(f"Error clearing table {table_name}: {e}", exc_info=True)
            await query.edit_message_text(f"❌ שגיאה באיפוס הטבלה: {e}")

    async def _toggle_bordering(self, query, user_id: int):
        """Toggle bordering neighborhoods search preference."""
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user_obj = await user_repo.get_by_telegram_id(user_id)
        if not user_obj:
            await query.answer("❌ משתמש לא נמצא")
            return
            
        new_status = not user_obj.allow_bordering_neighborhoods
        await user_repo.update_allow_bordering(user_id, new_status)
        
        # Reload rules and user object
        rules = await rule_repo.get_user_rules(user_id)
        
        # Get formatted rules list
        from bot.formatters.listing_formatter import ListingFormatter
        message = ListingFormatter.format_rules_list(rules, new_status, user_obj.allow_roomies, user_obj.allow_sublets)
        
        # Re-build toggle inline buttons
        button_border = "❌ השבת שכונות גובלות" if new_status else "✅ הפעל שכונות גובלות"
        button_roomies = "❌ השבת דירות שותפים" if user_obj.allow_roomies else "✅ הפעל דירות שותפים"
        button_sublets = "❌ השבת סאבלטים" if user_obj.allow_sublets else "✅ הפעל סאבלטים"
        keyboard = [
            [InlineKeyboardButton(button_border, callback_data="toggle_bordering")],
            [InlineKeyboardButton(button_roomies, callback_data="toggle_roomies")],
            [InlineKeyboardButton(button_sublets, callback_data="toggle_sublets")]
        ]
        
        # Friendly feedback
        persona_name = user_obj.persona
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        status_text = "פעיל כעת! אשלח לך גם דירות בשכונות סמוכות 😉" if new_status else "כבוי! אשלח לך אך ורק דירות בשכונות שהגדרת במפורש 🎯"
        
        # Show alert with feedback
        await query.answer(f"{persona_def.emoji} חיפוש בשכונות גובלות {status_text}", show_alert=True)
        
        # Edit the message to show the updated status
        await self._safe_edit_message_text(query, message, parse_mode='MarkdownV2')
        # Edit the message with the new inline keyboard as well
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
    async def _toggle_roomies(self, query, user_id: int):
        """Toggle roommate search preference."""
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user_obj = await user_repo.get_by_telegram_id(user_id)
        if not user_obj:
            await query.answer("❌ משתמש לא נמצא")
            return
            
        new_status = not user_obj.allow_roomies
        await user_repo.update_allow_roomies(user_id, new_status)
        
        # Reload rules and user object
        rules = await rule_repo.get_user_rules(user_id)
        
        # Get formatted rules list
        from bot.formatters.listing_formatter import ListingFormatter
        message = ListingFormatter.format_rules_list(rules, user_obj.allow_bordering_neighborhoods, new_status, user_obj.allow_sublets)
        
        # Re-build toggles inline buttons
        button_border = "❌ השבת שכונות גובלות" if user_obj.allow_bordering_neighborhoods else "✅ הפעל שכונות גובלות"
        button_roomies = "❌ השבת דירות שותפים" if new_status else "✅ הפעל דירות שותפים"
        button_sublets = "❌ השבת סאבלטים" if user_obj.allow_sublets else "✅ הפעל סאבלטים"
        keyboard = [
            [InlineKeyboardButton(button_border, callback_data="toggle_bordering")],
            [InlineKeyboardButton(button_roomies, callback_data="toggle_roomies")],
            [InlineKeyboardButton(button_sublets, callback_data="toggle_sublets")]
        ]
        
        # Friendly feedback
        persona_name = user_obj.persona
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        status_text = "מאופשר כעת! אשלח לך גם דירות שותפים 😉" if new_status else "מנוטרל! אשלח לך אך ורק דירות שלמות (ללא שותפים) 🎯"
        
        # Show alert with feedback
        await query.answer(f"{persona_def.emoji} קבלת דירות שותפים {status_text}", show_alert=True)
        
        # Edit the message to show the updated status
        await self._safe_edit_message_text(query, message, parse_mode='MarkdownV2')
        # Edit the message with the new inline keyboard as well
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
    async def _toggle_sublets(self, query, user_id: int):
        """Toggle sublet search preference."""
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user_obj = await user_repo.get_by_telegram_id(user_id)
        if not user_obj:
            await query.answer("❌ משתמש לא נמצא")
            return
            
        new_status = not user_obj.allow_sublets
        await user_repo.update_allow_sublets(user_id, new_status)
        
        # Reload rules and user object
        rules = await rule_repo.get_user_rules(user_id)
        
        # Get formatted rules list
        from bot.formatters.listing_formatter import ListingFormatter
        message = ListingFormatter.format_rules_list(rules, user_obj.allow_bordering_neighborhoods, user_obj.allow_roomies, new_status)
        
        # Re-build toggles inline buttons
        button_border = "❌ השבת שכונות גובלות" if user_obj.allow_bordering_neighborhoods else "✅ הפעל שכונות גובלות"
        button_roomies = "❌ השבת דירות שותפים" if user_obj.allow_roomies else "✅ הפעל דירות שותפים"
        button_sublets = "❌ השבת סאבלטים" if new_status else "✅ הפעל סאבלטים"
        keyboard = [
            [InlineKeyboardButton(button_border, callback_data="toggle_bordering")],
            [InlineKeyboardButton(button_roomies, callback_data="toggle_roomies")],
            [InlineKeyboardButton(button_sublets, callback_data="toggle_sublets")]
        ]
        
        # Friendly feedback
        persona_name = user_obj.persona
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        status_text = "מאופשר כעת! אשלח לך גם סאבלטים 😉" if new_status else "מנוטרל! אשלח לך אך ורק דירות רגילות (ללא סאבלטים) 🎯"
        
        # Show alert with feedback
        await query.answer(f"{persona_def.emoji} קבלת סאבלטים {status_text}", show_alert=True)
        
        # Edit the message to show the updated status
        await self._safe_edit_message_text(query, message, parse_mode='MarkdownV2')
        # Edit the message with the new inline keyboard as well
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_dashboard(self, query, context):
        """Go back to main admin panel screen."""
        admin_command_handler = context.bot_data.get("admin_command_handler")
        if admin_command_handler:
            dashboard, reply_markup = await admin_command_handler.get_admin_dashboard_data()
            await query.edit_message_text(
                dashboard,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

    async def _show_admin_users(self, query, context):
        """Show all registered users in-message."""
        db = await get_db()
        rule_repo = RuleRepository(db)
        from datetime import datetime
        import html
        
        # Get users
        rows = await db.fetch_all("SELECT * FROM users ORDER BY created_at DESC LIMIT 30")
        
        if not rows:
            msg = "אין משתמשים רשומים במערכת."
            keyboard = [[InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]]
        else:
            msg = f"👤 <b>משתמשים רשומים במערכת ({len(rows)}):</b>\n\n"
            keyboard = []
            user_buttons = []
            
            for row in rows:
                row_dict = dict(row)
                telegram_id = row_dict["telegram_id"]
                username = html.escape(row_dict["username"] or "אין")
                is_active = "פעיל ✅" if row_dict["is_active"] else "כבוי ❌"
                is_admin = "👑 מנהל" if row_dict.get("is_admin") else "משתמש"
                persona = html.escape(row_dict.get("persona") or "barakush")
                created_at = row["created_at"]
                
                # Count user's rules
                rules = await rule_repo.get_user_rules(telegram_id)
                rules_count = len(rules)
                
                # Try to format created_at nicely
                try:
                    dt = datetime.fromisoformat(created_at)
                    date_str = dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    date_str = created_at
                    
                msg += f"• <b>{telegram_id}</b> | @{username} | {is_admin}\n"
                msg += f"  נציג: <code>{persona}</code> | סטטוס: {is_active} | כללים: {rules_count}\n"
                msg += f"  הצטרף ב: {date_str}\n\n"
                
                # Create user button
                btn_label = f"👤 @{row_dict['username']}" if row_dict["username"] else f"👤 {telegram_id}"
                user_buttons.append(InlineKeyboardButton(btn_label, callback_data=f"admin_view_user:{telegram_id}"))
                
            # Chunk user buttons into pairs of 2
            for i in range(0, len(user_buttons), 2):
                keyboard.append(user_buttons[i:i+2])
                
            # Add back button
            keyboard.append([InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")])
            
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_recent_listings(self, query, context):
        """Show the last 10 enriched listings."""
        db = await get_db()
        rows = await db.fetch_all(
            "SELECT title, source, url, extracted_price, extracted_bedrooms, extracted_size, extracted_neighborhood, enriched_at "
            "FROM enriched_listings ORDER BY enriched_at DESC LIMIT 10"
        )
        import html
        
        if not rows:
            msg = "לא נמצאו דירות מועשרות במערכת."
        else:
            msg = "🏠 <b>10 הדירות האחרונות שנסרקו והועשרו:</b>\n\n"
            from datetime import datetime
            for i, row in enumerate(rows):
                title = html.escape(row["title"] or "ללא כותרת")
                url = html.escape(row["url"] or "")
                price = row["extracted_price"]
                beds = row["extracted_bedrooms"]
                size = row["extracted_size"] if "extracted_size" in row.keys() else None
                neighborhood = html.escape(row["extracted_neighborhood"] or "לא ידוע")
                source = html.escape(row["source"] or "לא ידוע")
                
                enriched_at = row["enriched_at"]
                try:
                    dt = datetime.fromisoformat(enriched_at)
                    time_str = dt.strftime("%d/%m %H:%M")
                except Exception:
                    time_str = enriched_at
                    
                price_str = f"{price:,} ₪" if price else "לא צוין מחיר"
                beds_str = f"{beds} חדרים" if beds else "לא צוין חדרים"
                size_str = f"{size} מ\"ר" if size else "לא צוין גודל"
                
                msg += f"{i+1}. <b><a href=\"{url}\">{title[:40]}</a></b>\n"
                msg += f"   💰 {price_str} | 🛏️ {beds_str} | 📏 {size_str} | 📍 {neighborhood}\n"
                msg += f"   📱 מקור: {source} | ⏱️ נסרק ב: {time_str}\n\n"
                
        keyboard = [[InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]]
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_logs(self, query, context):
        """Show error logs summary in-message and send file."""
        import json
        from pathlib import Path
        from datetime import datetime, timedelta, timezone
        from io import BytesIO
        import html
        
        errors_path = Path("logs/errors.log")
        if not errors_path.exists():
            await query.answer("❌ לא נמצא קובץ לוג שגיאות.", show_alert=True)
            return
            
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=1)
        
        recent_errors = []
        error_counts = {}
        
        try:
            with open(errors_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        ts_str = entry.get("timestamp")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts >= cutoff:
                                recent_errors.append(entry)
                                msg = entry.get("message", "Unknown error")
                                error_counts[msg] = error_counts.get(msg, 0) + 1
                    except Exception:
                        pass
        except Exception as e:
            await query.answer(f"❌ שגיאה בקריאת הלוגים: {e}", show_alert=True)
            return
            
        if not recent_errors:
            msg = "✅ אין שגיאות לוג ב-24 השעות האחרונות!"
            keyboard = [[InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]]
            await self._safe_edit_message_text(query, msg, parse_mode="HTML")
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        # Format a summary of errors
        summary = f"📋 <b>סיכום שגיאות ב-24 השעות האחרונות:</b>\n"
        summary += f"סה\"כ שגיאות: {len(recent_errors)}\n\n"
        summary += "<b>סוגי שגיאות נפוצים:</b>\n"
        sorted_counts = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        for errMsg, count in sorted_counts:
            short_msg = html.escape(errMsg[:60]) + ("..." if len(errMsg) > 60 else "")
            summary += f"• <code>{short_msg}</code>: {count} פעמים\n"
            
        summary += "\n*5 השגיאות האחרונות במלואן:* (קובץ מלא נשלח בצ'אט)"
        
        # Send full log as a file attachment
        try:
            log_content = ""
            for entry in reversed(recent_errors):
                log_content += f"=== ERROR AT {entry.get('timestamp')} ===\n"
                log_content += f"Logger: {entry.get('logger')} | Module: {entry.get('module')} | Func: {entry.get('function')}:{entry.get('line')}\n"
                log_content += f"Message: {entry.get('message')}\n"
                if entry.get("exception"):
                     log_content += f"Traceback:\n{entry.get('exception')}\n"
                log_content += "\n" + "="*50 + "\n\n"
                
            bio = BytesIO(log_content.encode("utf-8"))
            bio.name = f"errors_last_24h_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=bio,
                caption="📄 קובץ שגיאות מלא ל-24 השעות האחרונות"
            )
        except Exception as e:
            log.error(f"Failed to send logs file: {e}")
            
        keyboard = [[InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]]
        await self._safe_edit_message_text(query, summary, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_fb_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show Facebook credentials and file status, plus launch login button."""
        import os
        from datetime import datetime
        
        query = update.callback_query
        data = query.data if isinstance(query.data, str) else ""
        storage_state_path = "data/fb_storage_state.json"
        cookies_path = "data/fb_cookies.json"
        
        db = await get_db()
        from database.repositories.system_repository import SystemRepository
        system_repo = SystemRepository(db)
        
        # Get last scraping run
        last_run = await system_repo.get_last_run()
        
        # Get scheduler and properties
        app_instance = context.bot_data.get("app_instance")
        scheduler = app_instance.scheduler if app_instance else None
        
        interval = scheduler.interval if scheduler else settings.SCRAPE_INTERVAL_MINUTES
        auto_adjust = getattr(scheduler, "auto_adjust", True) if scheduler else True
        next_run = scheduler.get_next_run_time() if scheduler else None
        
        status_msg = "🔐 <b>ניהול וסטטיסטיקות סריקה ופייסבוק:</b>\n\n"
        
        status_msg += "⏱️ <b>קצב והגדרות סריקה:</b>\n"
        status_msg += f"• תדירות סריקה נוכחית: <code>{interval}</code> דקות\n"
        status_msg += f"• כיוונון אוטומטי (לפי קבוצות ומכסה): <code>{'כן ✅' if auto_adjust else 'לא ❌'}</code>\n"
        if next_run:
            status_msg += f"• ריצה הבאה מתוזמנת: <code>{next_run.strftime('%H:%M:%S')}</code>\n\n"
        else:
            status_msg += "• ריצה הבאה מתוזמנת: <code>לא פעיל / כבוי</code>\n\n"
            
        status_msg += "📊 <b>סבב סריקה אחרון:</b>\n"
        if last_run:
            status_str = "רצה כעת 🔄"
            if last_run["status"] == "completed":
                status_str = "הושלם בהצלחה ✅"
            elif last_run["status"] == "partial_success":
                status_str = "הושלם חלקית ⚠️"
            elif last_run["status"] == "failed":
                status_str = "נכשל ❌"
                
            try:
                start_dt = datetime.fromisoformat(last_run["start_time"])
                start_str = start_dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                start_str = last_run["start_time"]
                
            duration = last_run["duration_seconds"] or 0.0
            
            status_msg += f"• סטטוס: <code>{status_str}</code>\n"
            status_msg += f"• זמן התחלה: <code>{start_str}</code>\n"
            status_msg += f"• משך סבב: <code>{duration:.1f}</code> שניות\n"
            status_msg += f"• פייסבוק: נסרקו <code>{last_run['fb_total']}</code> (חדשים: <code>{last_run['fb_new']}</code>) {'❌' if last_run['fb_failed'] else ''}\n"
            status_msg += f"• יד2: נסרקו <code>{last_run['yad2_total']}</code> (חדשים: <code>{last_run['yad2_new']}</code>) {'❌' if last_run['yad2_failed'] else ''}\n"
            if last_run["error_message"]:
                status_msg += f"• שגיאה: <code>{last_run['error_message']}</code>\n"
            status_msg += "\n"
        else:
            status_msg += "• לא נמצאו ריצות קודמות\n\n"
            
        # Get all facebook groups to display their scraping stats
        from database.repositories.facebook_group_repository import FacebookGroupRepository
        fb_group_repo = FacebookGroupRepository(db)
        groups = await fb_group_repo.get_all_groups()
        
        status_msg += "📋 <b>סטטיסטיקת קבוצות פייסבוק:</b>\n"
        if groups:
            for g in groups:
                g_label = g.name if g.name else g.label
                status_msg += f"• {html.escape(g_label)}: <code>{g.last_scraped_count}</code>\n"
        else:
            status_msg += "• אין קבוצות מוגדרות\n"
        status_msg += "\n"
            
        status_msg += "🔑 <b>חיבור פייסבוק:</b>\n"
        if os.path.exists(storage_state_path):
            mtime = os.path.getmtime(storage_state_path)
            date_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            size_kb = os.path.getsize(storage_state_path) / 1024
            status_msg += f"✅ <b>קובץ Session:</b> קיים\n  עודכן: <code>{date_str}</code>\n  גודל: <code>{size_kb:.1f} KB</code>\n\n"
        else:
            status_msg += "❌ <b>קובץ Session:</b> חסר\n\n"
            
        if os.path.exists(cookies_path):
            mtime = os.path.getmtime(cookies_path)
            date_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            size_kb = os.path.getsize(cookies_path) / 1024
            status_msg += f"✅ <b>קובץ Cookies:</b> קיים\n  עודכן: <code>{date_str}</code>\n  גודל: <code>{size_kb:.1f} KB</code>\n\n"
        else:
            status_msg += "❌ <b>קובץ Cookies:</b> חסר\n\n"
            
        status_msg += "_תוכל להתחיל התחברות אינטראקטיבית חדשה, לשנות תדירות סריקה או ללחוץ על הרצה ידנית._"
        
        keyboard = [
            [
                InlineKeyboardButton("👥 ניהול קבוצות פייסבוק", callback_data="admin_menu_fb_groups"),
                InlineKeyboardButton("⏱️ תדירות סריקה", callback_data="admin_menu_change_frequency_prompt")
            ],
            [
                InlineKeyboardButton("🔑 התחל התחברות אינטראקטיבית", callback_data="admin_menu_fb_login_trigger"),
                InlineKeyboardButton("🔄 הרצת סורק ידנית", callback_data="admin_menu_fb_scrape_trigger")
            ],
            [InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]
        ]
        
        # Route special action triggers
        if data == "admin_menu_fb_login_trigger":
            # Call fb login command
            admin_command_handler = context.bot_data.get("admin_command_handler")
            if admin_command_handler:
                await query.answer("מתנייד להתחברות לפייסבוק...", show_alert=False)
                await admin_command_handler.admin_fb_login(update=update, context=context)
                return
        elif data == "admin_menu_fb_scrape_trigger":
            admin_command_handler = context.bot_data.get("admin_command_handler")
            if admin_command_handler:
                await query.answer("מפעיל סריקה ידנית...", show_alert=False)
                await admin_command_handler.admin_scrape(update=update, context=context)
                return
        elif data == "admin_menu_fb_groups":
            await self._show_admin_fb_groups_menu(update, context)
            return
        elif data == "admin_menu_fb_group_add":
            await self._prompt_add_fb_group(update, context)
            return
        elif data == "admin_menu_fb_group_remove_list":
            await self._show_remove_fb_groups_list(update, context)
            return
        elif data.startswith("admin_menu_fb_group_remove:"):
            group_id = int(data.split(":")[1])
            await self._remove_fb_group(update, context, group_id)
            return
                
        await self._safe_edit_message_text(query, status_msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_change_frequency_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show prompt with preset frequencies and toggle auto-adjust."""
        query = update.callback_query
        
        db = await get_db()
        from database.repositories.system_repository import SystemRepository
        system_repo = SystemRepository(db)
        
        app_instance = context.bot_data.get("app_instance")
        scheduler = app_instance.scheduler if app_instance else None
        
        interval = scheduler.interval if scheduler else settings.SCRAPE_INTERVAL_MINUTES
        auto_adjust = getattr(scheduler, "auto_adjust", True) if scheduler else True
        
        msg = f"⏱️ <b>הגדרת תדירות סריקה מותאמת אישית:</b>\n\n"
        msg += f"תדירות נוכחית: <code>{interval}</code> דקות.\n"
        msg += f"כיוונון אוטומטי (מבוסס מכסת Gemini): <code>{'פעיל ✅' if auto_adjust else 'כבוי ❌'}</code>\n\n"
        msg += "בחר אחת מהתדירויות הבאות כקבועות (זה יכבה כיוונון אוטומטי):"
        
        keyboard = [
            [
                InlineKeyboardButton("5 דק׳", callback_data="admin_menu_set_frequency:5"),
                InlineKeyboardButton("10 דק׳", callback_data="admin_menu_set_frequency:10")
            ],
            [
                InlineKeyboardButton("15 דק׳", callback_data="admin_menu_set_frequency:15"),
                InlineKeyboardButton("30 דק׳", callback_data="admin_menu_set_frequency:30")
            ],
            [
                InlineKeyboardButton("60 דק׳", callback_data="admin_menu_set_frequency:60"),
                InlineKeyboardButton("120 דק׳", callback_data="admin_menu_set_frequency:120")
            ],
            [
                InlineKeyboardButton(
                    "🔄 הפעל/כבה כיוונון אוטומטי",
                    callback_data="admin_menu_toggle_auto_adjust"
                )
            ],
            [InlineKeyboardButton("↩️ חזרה", callback_data="admin_menu_fb")]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _set_frequency(self, update: Update, context: ContextTypes.DEFAULT_TYPE, minutes: int):
        """Set a fixed frequency and disable auto-adjust."""
        query = update.callback_query
        
        db = await get_db()
        from database.repositories.system_repository import SystemRepository
        system_repo = SystemRepository(db)
        
        # Save to DB
        await system_repo.set_scrape_interval(minutes)
        await system_repo.set_auto_adjust_interval(False)
        
        # Apply to scheduler
        app_instance = context.bot_data.get("app_instance")
        scheduler = app_instance.scheduler if app_instance else None
        if scheduler:
            scheduler.auto_adjust = False
            scheduler.update_interval(minutes)
            
        await query.answer(f"⏱️ תדירות הסריקה עודכנה ל-{minutes} דקות (כיוונון אוטומטי כבוי)", show_alert=True)
        await self._show_admin_fb_menu(update, context)

    async def _toggle_auto_adjust(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle auto-adjust interval based on quota limits."""
        query = update.callback_query
        
        db = await get_db()
        from database.repositories.system_repository import SystemRepository
        system_repo = SystemRepository(db)
        
        app_instance = context.bot_data.get("app_instance")
        scheduler = app_instance.scheduler if app_instance else None
        
        current_auto_adjust = getattr(scheduler, "auto_adjust", True) if scheduler else True
        new_auto_adjust = not current_auto_adjust
        
        # Save to DB
        await system_repo.set_auto_adjust_interval(new_auto_adjust)
        
        # Apply to scheduler
        if scheduler:
            scheduler.auto_adjust = new_auto_adjust
            if new_auto_adjust:
                # Let it recalculate optimal interval immediately
                optimal = scheduler.calculate_optimal_interval()
                scheduler.update_interval(optimal)
                alert_text = f"✅ כיוונון אוטומטי הופעל. התדירות הותאמה ל-{optimal} דקות."
            else:
                # Revert to default/saved config interval
                saved_interval = await system_repo.get_scrape_interval()
                interval = saved_interval or settings.SCRAPE_INTERVAL_MINUTES
                scheduler.update_interval(interval)
                alert_text = f"❌ כיוונון אוטומטי כבוי. התדירות נקבעה ל-{interval} דקות."
        else:
            alert_text = "ההגדרה נשמרה בבסיס הנתונים."
            
        await query.answer(alert_text, show_alert=True)
        await self._show_change_frequency_prompt(update, context)

    async def _show_admin_fb_groups_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show the menu with current Facebook groups and actions to add/remove."""
        query = update.callback_query
        db = await get_db()
        from database.repositories.facebook_group_repository import FacebookGroupRepository
        fb_group_repo = FacebookGroupRepository(db)
        groups = await fb_group_repo.get_all_groups()
        
        msg = "👥 <b>ניהול קבוצות פייסבוק לסריקה</b>\n\n"
        if groups:
            msg += "<b>הקבוצות הפעילות כעת במערכת:</b>\n"
            for idx, g in enumerate(groups, 1):
                if g.name:
                    msg += f"{idx}. <b>{html.escape(g.name)}</b>\n   <code>{html.escape(g.url)}</code>\n"
                else:
                    msg += f"{idx}. <code>{html.escape(g.url)}</code>\n"
        else:
            msg += "❌ אין קבוצות פייסבוק מוגדרות במערכת.\n"
            
        msg += "\nבחר אחת מהפעולות הבאות:"
        
        keyboard = [
            [InlineKeyboardButton("➕ הוסף קבוצת פייסבוק", callback_data="admin_menu_fb_group_add")],
            [InlineKeyboardButton("❌ הסר קבוצת פייסבוק", callback_data="admin_menu_fb_group_remove_list")],
            [InlineKeyboardButton("↩️ חזרה לתפריט פייסבוק", callback_data="admin_menu_fb")]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _prompt_add_fb_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt the admin to enter the URL of the new Facebook group."""
        query = update.callback_query
        
        context.user_data["admin_waiting_for_fb_group"] = True
        
        msg = (
            "✍️ <b>הוספת קבוצת פייסבוק חדשה</b>\n\n"
            "אנא שלח את כתובת ה-URL של קבוצת הפייסבוק (למשל: <code>https://www.facebook.com/groups/123456</code>).\n\n"
            "שלח <code>ביטול</code> או <code>cancel</code> כדי לבטל את הפעולה."
        )
        
        keyboard = [
            [InlineKeyboardButton("↩️ ביטול וחזרה", callback_data="admin_menu_fb_groups")]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_remove_fb_groups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show the list of Facebook groups with inline buttons to delete them."""
        query = update.callback_query
        db = await get_db()
        from database.repositories.facebook_group_repository import FacebookGroupRepository
        fb_group_repo = FacebookGroupRepository(db)
        groups = await fb_group_repo.get_all_groups()
        
        msg = "❌ <b>הסרת קבוצת פייסבוק</b>\n\nבחר את הקבוצה שברצונך להסיר מהרשימה:\n"
        
        keyboard = []
        if groups:
            for g in groups:
                # Use name if available, else first part of URL or group ID to keep button text reasonable
                display_name = g.name if g.name else g.url.split("/groups/")[-1].strip("/")
                if len(display_name) > 30:
                    display_name = display_name[:27] + "..."
                keyboard.append([InlineKeyboardButton(f"🗑️ {display_name}", callback_data=f"admin_menu_fb_group_remove:{g.id}")])
                
        keyboard.append([InlineKeyboardButton("↩️ חזרה", callback_data="admin_menu_fb_groups")])
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _remove_fb_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: int):
        """Delete the selected Facebook group and update the scraper."""
        query = update.callback_query
        db = await get_db()
        from database.repositories.facebook_group_repository import FacebookGroupRepository
        fb_group_repo = FacebookGroupRepository(db)
        
        group = await fb_group_repo.get_by_id(group_id)
        if group:
            await fb_group_repo.delete(group_id)
            await query.answer(f"הקבוצה הוסרה בהצלחה", show_alert=True)
            
            # Reload scraper group URLs
            app_instance = context.bot_data.get("app_instance")
            if app_instance:
                await app_instance.reload_facebook_groups()
        else:
            await query.answer("שגיאה: הקבוצה לא נמצאה", show_alert=True)
            
        await self._show_admin_fb_groups_menu(update, context)

    async def _show_admin_clear_menu(self, query, context):
        """Show clean menu with dropping buttons."""
        msg = (
            "🧹 <b>תפריט ניקוי ואיפוס טבלאות במסד הנתונים</b>\n\n"
            "⚠️ <b>אזהרה:</b> מחיקת טבלאות היא פעולה בלתי הפיכה ובלתי ניתנת לשחזור! "
            "אנא השתמש בזהירות מירבית."
        )
        
        keyboard = [
            [
                InlineKeyboardButton("🗑️ נקה היסטוריית סריקה (Seen)", callback_data="admin_clear_table:seen_listings"),
                InlineKeyboardButton("🗑️ נקה דירות מועשרות", callback_data="admin_clear_table:enriched_listings")
            ],
            [
                InlineKeyboardButton("🗑️ נקה יומני פסילות", callback_data="admin_clear_table:rejection_logs"),
                InlineKeyboardButton("🗑️ נקה מטמון AI", callback_data="admin_clear_table:ai_cache")
            ],
            [
                InlineKeyboardButton("💥 איפוס משתמשים וכללים", callback_data="admin_clear_table:users")
            ],
            [
                InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")
            ]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_server_stats(self, query, context):
        """Show diagnostic system and directory statistics."""
        import platform
        import os
        import sys
        import shutil
        from pathlib import Path
        import html
        
        # Disk usage
        total, used, free = shutil.disk_usage(".")
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)
        
        # DB sizes
        db_size_mb = 0.0
        db_path = Path("apartment_bot.db")
        if db_path.exists():
            db_size_mb = db_path.stat().st_size / (1024 * 1024)
            
        wal_size_mb = 0.0
        wal_path = Path("apartment_bot.db-wal")
        if wal_path.exists():
            wal_size_mb = wal_path.stat().st_size / (1024 * 1024)
            
        msg = f"""🖥️ <b>אבחון וסטטיסטיקות שרת:</b>

💻 <b>פרטי מערכת הפעלה:</b>
• מערכת הפעלה: <code>{html.escape(platform.system())}</code>
• גרסת הפצה: <code>{html.escape(platform.release())}</code>
• ארכיטקטורה: <code>{html.escape(platform.machine())}</code>

🐍 <b>סביבת ריצה:</b>
• גרסת Python: <code>{html.escape(sys.version.split()[0])}</code>
• מעבדים (CPU Cores): <code>{os.cpu_count()}</code>

💾 <b>שטח אחסון בשרת:</b>
• סה"כ דיסק: <code>{total_gb:.1f} GB</code>
• בשימוש: <code>{used_gb:.1f} GB</code> (<code>{used/total*100:.1f}%</code>)
• פנוי: <code>{free_gb:.1f} GB</code>

🗄️ <b>קבצי מסד הנתונים:</b>
• גודל DB: <code>{db_size_mb:.2f} MB</code>
• גודל DB WAL: <code>{wal_size_mb:.2f} MB</code>"""
        keyboard = [[InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]]
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_gemini_test(self, query, context):
        """Test Gemini AI engine connection."""
        ai_engine = context.bot_data.get("ai_engine")
        
        if not ai_engine:
            msg = f"""❌ מנוע AI (ai_engine) אינו מוגדר ב-bot_data!
🔁 <b>ניסיונות חוזרים (AI Retries):</b> <code>{settings.GEMINI_503_RETRIES}</code>"""
        else:
            await query.answer("בודק חיבור למנוע ה-AI... אנא המתן", show_alert=False)
            try:
                # Call Gemini content generator with a simple fast prompt
                from datetime import datetime
                t0 = datetime.now()
                test_response = await ai_engine.generate_content("Respond with exactly: OK")
                duration = (datetime.now() - t0).total_seconds()
                
                model_name = getattr(ai_engine, "current_model", "Gemini")
                
                msg = f"""🧪 <b>תוצאת בדיקת Gemini AI:</b>

✅ <b>סטטוס:</b> מחובר ותקין!
🤖 <b>מודל פעיל:</b> <code>{html.escape(model_name)}</code>
🔁 <b>ניסיונות חוזרים (AI Retries):</b> <code>{settings.GEMINI_503_RETRIES}</code>
⏱️ <b>זמן תגובה:</b> <code>{duration:.2f} שניות</code>
💬 <b>תשובה מהספק:</b> <code>{html.escape(test_response.strip())}</code>"""
            except Exception as e:
                msg = f"""🧪 <b>תוצאת בדיקת Gemini AI:</b>

❌ <b>שגיאה:</b> החיבור נכשל!
🔁 <b>ניסיונות חוזרים (AI Retries):</b> <code>{settings.GEMINI_503_RETRIES}</code>
⚠️ <b>פירוט:</b>
<code>{html.escape(str(e))}</code>"""
                
        keyboard = [
            [InlineKeyboardButton("⚙️ הגדר כמות ניסיונות", callback_data="admin_menu_change_retries_prompt")],
            [InlineKeyboardButton("↩️ חזרה לתפריט ראשי", callback_data="admin_menu_main")]
        ]
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_change_retries_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt admin to enter the new number of AI retries."""
        query = update.callback_query
        context.user_data["admin_waiting_for_ai_retries"] = True
        
        msg = (
            "🔁 <b>הגדרת כמות ניסיונות חוזרים של AI (AI Retries)</b>\n\n"
            f"כמות הניסיונות הנוכחית: <code>{settings.GEMINI_503_RETRIES}</code>\n\n"
            "נא שלח כעת את כמות הניסיונות החוזרים הרצויה (מספר שלם חיובי בין 1 ל-50).\n"
            "אם ברצונך לבטל, שלח את המילה <code>cancel</code> או <code>ביטול</code>."
        )
        
        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data="admin_menu_main")]]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _prompt_admin_broadcast(self, query, context):
        """Prompt admin to enter the text message for broadcasting."""
        context.user_data["admin_waiting_for_broadcast"] = True
        
        msg = (
            "📢 <b>שידור הודעה מערכת לכלל המשתמשים</b>\n\n"
            "אנא כתוב ושלח כעת את הודעת הטקסט שברצונך להפיץ לכולם.\n"
            "אם ברצונך לבטל את השידור, שלח את המילה <code>cancel</code> או <code>ביטול</code>."
        )
        
        keyboard = [[InlineKeyboardButton("❌ ביטול", callback_data="admin_menu_main")]]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_user_detail(self, query, context, user_id: int):
        """Show details of a specific user."""
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user = await user_repo.get_by_telegram_id(user_id)
        if not user:
            await query.answer("❌ המשתמש לא נמצא במערכת", show_alert=True)
            return
            
        # Count rules
        rules = await rule_repo.get_user_rules(user_id)
        rules_count = len(rules)
        
        # Count matches (sent notifications)
        row = await db.fetch_one("SELECT COUNT(*) as count FROM sent_notifications WHERE user_id = ?", (user_id,))
        matches_count = row["count"] if row else 0
        
        import html
        from datetime import datetime
        
        username = html.escape(user.username or "אין")
        is_active = "פעיל ✅" if user.is_active else "כבוי ❌"
        is_admin = "👑 מנהל" if user.is_admin else "משתמש"
        persona = html.escape(user.persona or "barakush")
        bordering = "מאופשר ✅" if user.allow_bordering_neighborhoods else "מנוטרל ❌"
        roomies_status = "מאופשר ✅" if user.allow_roomies else "מנוטרל ❌"
        
        try:
            dt = datetime.fromisoformat(user.created_at)
            date_str = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            date_str = user.created_at
            
        msg = f"""👤 <b>פרטי משתמש: @{username}</b>

• <b>מזהה טלגרם:</b> <code>{user_id}</code>
• <b>מזהה צ'אט:</b> <code>{user.chat_id}</code>
• <b>תפקיד:</b> {is_admin}
• <b>סטטוס:</b> {is_active}
• <b>נציג מלווה:</b> <code>{persona}</code>
• <b>שכונות גובלות:</b> {bordering}
• <b>דירות שותפים:</b> {roomies_status}
• <b>תאריך הצטרפות:</b> {date_str}
• <b>סה"כ כללים:</b> <code>{rules_count}</code>
• <b>סה"כ התאמות (שידוכים):</b> <code>{matches_count}</code>"""

        keyboard = [
            [
                InlineKeyboardButton(f"📋 כללי חיפוש ({rules_count})", callback_data=f"admin_user_rules:{user_id}"),
                InlineKeyboardButton(f"🏠 דירות שהתאימו ({matches_count})", callback_data=f"admin_user_matches:{user_id}")
            ],
            [
                InlineKeyboardButton("↩️ חזרה לרשימת משתמשים", callback_data="admin_menu_users")
            ]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_user_rules(self, query, context, user_id: int):
        """Show active rules for a specific user."""
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user = await user_repo.get_by_telegram_id(user_id)
        if not user:
            await query.answer("❌ המשתמש לא נמצא במערכת", show_alert=True)
            return
            
        rules = await rule_repo.get_user_rules(user_id)
        rules_count = len(rules)
        
        row = await db.fetch_one("SELECT COUNT(*) as count FROM sent_notifications WHERE user_id = ?", (user_id,))
        matches_count = row["count"] if row else 0
        
        from bot.formatters.listing_formatter import ListingFormatter
        rules_text = ListingFormatter.format_rules_list(rules, user.allow_bordering_neighborhoods)
        
        username_esc = ListingFormatter._escape_markdown(user.username or str(user_id))
        msg = f"📋 *כללי חיפוש עבור @{username_esc}:*\n\n{rules_text}"
        
        keyboard = [
            [
                InlineKeyboardButton("👤 פרטי משתמש", callback_data=f"admin_view_user:{user_id}"),
                InlineKeyboardButton(f"🏠 דירות שהתאימו ({matches_count})", callback_data=f"admin_user_matches:{user_id}")
            ],
            [
                InlineKeyboardButton("↩️ חזרה לרשימת משתמשים", callback_data="admin_menu_users")
            ]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="MarkdownV2")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_admin_user_matches(self, query, context, user_id: int):
        """Show matching listings sent to a specific user."""
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user = await user_repo.get_by_telegram_id(user_id)
        if not user:
            await query.answer("❌ המשתמש לא נמצא במערכת", show_alert=True)
            return
            
        rules = await rule_repo.get_user_rules(user_id)
        rules_count = len(rules)
        
        rows = await db.fetch_all(
            """
            SELECT el.title, el.url, el.extracted_price, el.extracted_bedrooms, el.extracted_size, el.extracted_neighborhood, el.source, sn.sent_at
            FROM enriched_listings el
            JOIN sent_notifications sn ON el.listing_id = sn.listing_id
            WHERE sn.user_id = ?
            ORDER BY sn.sent_at DESC
            LIMIT 10
            """,
            (user_id,)
        )
        
        import html
        from datetime import datetime
        
        username = html.escape(user.username or str(user_id))
        
        if not rows:
            msg = f"🏠 <b>דירות שהתאימו עבור @{username}:</b>\n\nלא נמצאו התאמות שנשלחו למשתמש זה."
        else:
            msg = f"🏠 <b>10 הדירות האחרונות שהתאימו עבור @{username}:</b>\n\n"
            for i, row in enumerate(rows):
                title = html.escape(row["title"] or "ללא כותרת")
                url = html.escape(row["url"] or "")
                price = row["extracted_price"]
                beds = row["extracted_bedrooms"]
                size = row["extracted_size"] if "extracted_size" in row.keys() else None
                neighborhood = html.escape(row["extracted_neighborhood"] or "לא ידוע")
                source = html.escape(row["source"] or "לא ידוע")
                sent_at = row["sent_at"]
                
                try:
                    dt = datetime.fromisoformat(sent_at)
                    time_str = dt.strftime("%d/%m %H:%M")
                except Exception:
                    time_str = sent_at
                    
                price_str = f"{price:,} ₪" if price else "לא צוין מחיר"
                beds_str = f"{beds} חדרים" if beds else "לא צוין חדרים"
                size_str = f"{size} מ\"ר" if size else "לא צוין גודל"
                source_name = "פייסבוק" if source == "facebook" else "Yad2"
                
                msg += f"{i+1}. <b><a href=\"{url}\">{title[:40]}</a></b>\n"
                msg += f"   💰 {price_str} | 🛏️ {beds_str} | 📏 {size_str} | 📍 {neighborhood}\n"
                msg += f"   📱 מקור: {source_name} | ⏱️ נשלח ב: {time_str}\n\n"
                
        keyboard = [
            [
                InlineKeyboardButton("👤 פרטי משתמש", callback_data=f"admin_view_user:{user_id}"),
                InlineKeyboardButton(f"📋 כללי חיפוש ({rules_count})", callback_data=f"admin_user_rules:{user_id}")
            ],
            [
                InlineKeyboardButton("↩️ חזרה לרשימת משתמשים", callback_data="admin_menu_users")
            ]
        ]
        
        await self._safe_edit_message_text(query, msg, parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

