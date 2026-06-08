# bot/handlers/message_handler.py
"""Natural language message processing for rule definition."""

from telegram import Update
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository, ListingRepository
from core.ai_engine import GeminiAIEngine
from models.search_rule import SearchRule, RuleType
from utils.validators import parse_rule_input
from utils.logger import Loggers
from utils.israeli_locations import get_location_db
from bot.handlers.decorators import ensure_user_exists
from bot.handlers.onboarding_handler import OnboardingHandler

log = Loggers.bot()


def clean_hebrew_location_text(text: str) -> str:
    """Clean common command/prefix words from Hebrew geographic search text."""
    import re
    # Remove leading/trailing whitespace
    text = text.strip()
    # Remove common prefix patterns
    prefixes = [
        r'^ו?(?:ת)?וסי[פף](?:י)?\s+(?:את\s+)?',
        r'^ו?להוסיף\s+(?:את\s+)?',
        r'^ו?(?:ת)?סיר(?:י)?\s+(?:את\s+)?',
        r'^ו?להסיר\s+(?:את\s+)?',
        r'^ו?בלי\s+',
        r'^ו?ללא\s+',
        r'^ו?עם\s+',
        r'^ו?מחק\s+(?:את\s+)?',
    ]
    for pattern in prefixes:
        text = re.sub(pattern, '', text)
    return text.strip()



class MessageHandler:
    """Handles natural language messages for rule definition."""
    
    def __init__(self, ai_engine: GeminiAIEngine = None):
        self.ai_engine = ai_engine
        self.onboarding_handler = OnboardingHandler(ai_engine)
    
    async def _safe_reply_text(self, update: Update, text: str, parse_mode: str = None, **kwargs):
        """Send message safely, handling Markdown errors gracefully (using central helper)."""
        from bot.handlers.bot_utils import safe_reply_text
        await safe_reply_text(update, text, parse_mode=parse_mode, **kwargs)

    @ensure_user_exists
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process natural language rule input from user."""
        user = update.effective_user
        text = update.message.text.strip()
        
        if not text:
            return
            
        # Get user object to check onboarding step
        db = await get_db()
        user_repo = UserRepository(db)
        user_obj = await user_repo.get_by_telegram_id(user.id)
        
        # Intercept system broadcast from admin
        if context.user_data.get("admin_waiting_for_broadcast"):
            # Clear state first
            context.user_data.pop("admin_waiting_for_broadcast", None)
            
            # Cancel option
            if text.lower() in ("cancel", "ביטול"):
                await update.message.reply_text("❌ שידור ההודעה בוטל.")
                # Show main dashboard
                admin_command_handler = context.bot_data.get("admin_command_handler")
                if admin_command_handler:
                    dashboard, reply_markup = await admin_command_handler.get_admin_dashboard_data()
                    await update.message.reply_text(
                        dashboard,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                return
                
            # Perform broadcast
            broadcast_text = text
            await update.message.reply_text(f"📢 מתחיל שידור הודעה לכל המשתמשים הפעילים...")
            
            import asyncio
            # Get all active users
            users = await user_repo.get_all_active()
            
            if not users:
                await update.message.reply_text("אין משתמשים פעילים במערכת לשידור.")
                return
                
            sent_count = 0
            failed_count = 0
            
            import html
            for u in users:
                try:
                    await context.bot.send_message(
                        chat_id=u.chat_id,
                        text=f"📢 <b>הודעת מערכת:</b>\n\n{html.escape(broadcast_text)}",
                        parse_mode="HTML"
                    )
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    log.error(f"Failed to send broadcast to user {u.telegram_id}: {e}")
                    failed_count += 1
                    
            await update.message.reply_text(
                f"✅ השידור הושלם!\n"
                f"• נשלח בהצלחה: {sent_count}\n"
                f"• נכשל: {failed_count}"
            )
            
            # Show dashboard again
            admin_command_handler = context.bot_data.get("admin_command_handler")
            if admin_command_handler:
                dashboard, reply_markup = await admin_command_handler.get_admin_dashboard_data()
                await update.message.reply_text(
                    dashboard,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            return
        
        # Intercept interactive Facebook login commands (highest priority)
        fb_interactive = context.bot_data.get("fb_interactive_login")
        if (fb_interactive 
            and fb_interactive.get("active") 
            and fb_interactive.get("chat_id") == user.id):
            command = text.strip()
            log.info("Interactive FB login command received", user_id=user.id, command=command)
            queue = fb_interactive.get("queue")
            if queue:
                queue.put_nowait(command)
            return
        
        # Intercept if user is in onboarding
        if user_obj and user_obj.onboarding_step:
            await self.onboarding_handler.handle_onboarding_step(update, context, user_obj, text)
            return

        # Intercept 2FA verification response if bot is waiting for a Facebook login code
        if context.bot_data.get("fb_login_waiting_for_2fa") == user.id:
            code = text.strip()
            log.info("Intercepting 2FA response message from admin", user_id=user.id, code=code)
            
            # Send immediate feedback
            await update.message.reply_text(f"🔑 קוד 2FA התקבל: `{code}`.\nמגיש כעת לפייסבוק, אנא המתן...")
            
            # Set the future result and clear state
            future = context.bot_data.get("fb_login_future")
            if future and not future.done():
                future.set_result(code)
            context.bot_data["fb_login_waiting_for_2fa"] = None
            return
        
        log.info("User message received", user_id=user.id, text=text[:50])
        
        # Check if we have a pending rule confirmation and the user is modifying the neighborhoods
        pending_data = context.user_data.get('pending_rule_confirmation')
        
        remove_patterns = [
            r'(?:^|\s)ו?(?:ת)?סיר(?:י)?\s+(?:את\s+)?([א-ת\s\d\'-]+)',
            r'(?:^|\s)ו?בלי\s+([א-ת\s\d\'-]+)',
            r'(?:^|\s)ו?ללא\s+([א-ת\s\d\'-]+)',
            r'(?:^|\s)ו?להסיר\s+(?:את\s+)?([א-ת\s\d\'-]+)',
            r'(?:^|\s)ו?מחק\s+(?:את\s+)?([א-ת\s\d\'-]+)',
        ]
        
        add_patterns = [
            r'(?:^|\s)ו?(?:ת)?וסי[פף](?:י)?\s+(?:את\s+)?([א-ת\s\d\'-]+)',
            r'(?:^|\s)ו?להוסיף\s+(?:את\s+)?([א-ת\s\d\'-]+)',
            r'(?:^|\s)ו?עם\s+([א-ת\s\d\'-]+)',
        ]
        
        if not pending_data:
            import re
            has_mod_keywords = False
            for pattern in remove_patterns + add_patterns:
                if re.search(pattern, text):
                    has_mod_keywords = True
                    break
                    
            if has_mod_keywords:
                db = await get_db()
                rule_repo = RuleRepository(db)
                active_rules = await rule_repo.get_user_rules(user.id, active_only=True)
                
                if active_rules:
                    cloned_rules = []
                    rules_to_delete = []
                    for r in active_rules:
                        cloned = SearchRule(
                            user_id=r.user_id,
                            rule_type=r.rule_type,
                            value=r.value,
                            original_text=r.original_text
                        )
                        cloned_rules.append(cloned)
                        rules_to_delete.append(r.id)
                    
                    pending_data = {
                        'user_id': user.id,
                        'all_pending_rules': cloned_rules,
                        'border_rules_data': [],
                        'rules_to_delete': rules_to_delete,
                        'sass_response': 'עדכנתי את הכללים שלך!'
                    }
                    context.user_data['pending_rule_confirmation'] = pending_data

        if pending_data:
            import re
            
            location_db = get_location_db()
            
            removed_neighborhoods = []
            added_neighborhoods = []
            is_modification = False
            
            # Split the message into independent clauses to avoid greedy regex crossing boundaries
            clauses = re.split(r'\s+ו(?=[א-ת])|\s*,\s*|\s+ו?גם\s+', text)
            
            for clause in clauses:
                clause = clause.strip()
                if not clause:
                    continue
                    
                # Removals
                for pattern in remove_patterns:
                    matches = re.findall(pattern, clause)
                    for m in matches:
                        n_name = m.strip()
                        parts = re.split(r'\s+ו|\s+(?:או)\s+|\s*,\s*', n_name)
                        for part in parts:
                            normalized = location_db.normalize_location(part)["neighborhood"]
                            if normalized:
                                removed_neighborhoods.append(normalized)
                                is_modification = True
                                
                # Additions
                for pattern in add_patterns:
                    matches = re.findall(pattern, clause)
                    for m in matches:
                        n_name = m.strip()
                        parts = re.split(r'\s+ו|\s+(?:או)\s+|\s*,\s*', n_name)
                        for part in parts:
                            normalized = location_db.normalize_location(part)["neighborhood"]
                            if normalized:
                                added_neighborhoods.append(normalized)
                                is_modification = True
                            
            # Remove duplicates
            removed_neighborhoods = list(set(removed_neighborhoods))
            added_neighborhoods = list(set(added_neighborhoods))
            
            if is_modification:
                all_pending_rules = pending_data.get('all_pending_rules', [])
                rules_adjusted = False
                updated_pending_rules = []
                
                # Apply changes to all pending rules
                for rule in all_pending_rules:
                    if rule.rule_type == RuleType.BORDER_AREA:
                        current = [n.strip() for n in rule.value.split(",") if n.strip()]
                        
                        # Apply removals
                        for r_name in removed_neighborhoods:
                            if r_name in current:
                                current.remove(r_name)
                                
                        # Apply additions
                        for a_name in added_neighborhoods:
                            if a_name not in current:
                                current.append(a_name)
                                
                        if current:
                            rule.value = ",".join(current)
                            updated_pending_rules.append(rule)
                            rules_adjusted = True
                        else:
                            rules_adjusted = True
                    elif rule.rule_type == RuleType.AREA:
                        if rule.value in removed_neighborhoods:
                            rules_adjusted = True
                        else:
                            updated_pending_rules.append(rule)
                    else:
                        updated_pending_rules.append(rule)
                
                # Handle additions that aren't already covered by AREA or BORDER_AREA rules
                existing_areas = set()
                for rule in updated_pending_rules:
                    if rule.rule_type == RuleType.AREA:
                        existing_areas.add(rule.value)
                    elif rule.rule_type == RuleType.BORDER_AREA:
                        existing_areas.update(n.strip() for n in rule.value.split(",") if n.strip())
                
                for a_name in added_neighborhoods:
                    if a_name not in existing_areas:
                        new_rule = SearchRule(
                            user_id=user.id,
                            rule_type=RuleType.AREA,
                            value=a_name,
                            original_text=a_name
                        )
                        updated_pending_rules.append(new_rule)
                        rules_adjusted = True
                
                if rules_adjusted:
                    pending_data['all_pending_rules'] = updated_pending_rules
                    log.info("Updated pending rules with user adjustments", user_id=user.id)
                    
                # Re-format confirmation message
                confirmation_msg = self._format_rules_confirmation_message(updated_pending_rules, pending_data.get('border_rules_data'))
                
                # Highlight what was changed
                mod_actions = []
                if removed_neighborhoods:
                    mod_actions.append(f"❌ הסרתי את: {', '.join(removed_neighborhoods)}")
                if added_neighborhoods:
                    mod_actions.append(f"➕ הוספתי את: {', '.join(added_neighborhoods)}")
                    
                escaped_mod = self._escape_markdown("\n".join(mod_actions))
                full_message = f"✍️ *עדכנתי את האזור לבקשתך\\!*\n{escaped_mod}\n\n{confirmation_msg}"
                
                from bot.handlers.callback_handler import CallbackHandler
                keyboard = CallbackHandler.create_rules_confirmation_keyboard()
                
                await self._safe_reply_text(
                    update,
                    full_message,
                    reply_markup=keyboard,
                    parse_mode='MarkdownV2'
                )
                return
        
        # Check if text matches any of our persistent reply keyboard options
        menu_mappings = {
            "🔎 חיפוש התאמות": "matches",
            "📊 סטטוס": "status",
            "📋 הכללים שלי": "rules",
            "👤 החלפת נציג": "persona",
            "🗑️ דירות שנפסלו": "rejections",
            "💅 קצת יחס": "sass",
            "ℹ️ עזרה": "help"
        }
        
        if text in menu_mappings:
            command = menu_mappings[text]
            command_handler = context.bot_data.get("command_handler")
            if command_handler and hasattr(command_handler, command):
                log.info("Routing reply keyboard menu option", user_id=user.id, option=text, command=command)
                handler_func = getattr(command_handler, command)
                await handler_func(update, context)
                return
        
        # Parse rules using AI
        try:
            if self.ai_engine:
                db = await get_db()
                user_repo = UserRepository(db)
                user_obj = await user_repo.get_by_telegram_id(user.id)
                persona_name = user_obj.persona if user_obj else 'barakush'
                
                rules_list, sass_response = await self.ai_engine.parse_user_rules(text, persona=persona_name)
            else:
                log.error("No AI engine available")
                return
        except Exception as e:
            log.error(f"Failed to parse rules: {e}")
            await self._safe_reply_text(
                update,
                "אופס, המוח שלי קרס לרגע. נסה שוב? 😵‍💫",
                parse_mode='MarkdownV2'
            )
            return

        if not rules_list:
            await self._safe_reply_text(
                update,
                "לא הבנתי כלום מאמי. נסה להיות יותר ספציפי (למשל: 'דירה בתל אביב ב-5000 שקל')",
                parse_mode='MarkdownV2'
            )
            
            # Send help message if command handler is available
            command_handler = context.bot_data.get("command_handler")
            if command_handler:
                await command_handler.help(update, context)
            return

        # Add rules to DB
        db = await get_db()
        rule_repo = RuleRepository(db)
        
        added_count = 0
        rules_to_add = []
        border_rules_pending = []  # Border rules that need confirmation
        
        # Get existing active rules to check for conflicts
        existing_rules = await rule_repo.get_user_rules(user.id, active_only=True)

        # --- Pre-processing: Auto-generate MAX bedrooms if only MIN is present ---
        has_min_beds = False
        has_max_beds = False
        min_beds_val = 0
        
        for r in rules_list:
            if r["type"] == "bedrooms_min":
                has_min_beds = True
                try:
                    min_beds_val = float(r["value"])
                except ValueError:
                    min_beds_val = 0
            elif r["type"] == "bedrooms_max":
                has_max_beds = True
        
        if has_min_beds and not has_max_beds and min_beds_val > 0:
            max_val = int(min_beds_val + 3)
            log.info(f"Auto-generating max bedrooms rule: {max_val} (min + 3)")
            rules_list.append({
                "type": "bedrooms_max",
                "value": max_val,
                "original_text": f"מקסימום {max_val} חדרים (אוטומטי)"
            })
            
        # --- Pre-processing: Enforce explicit text for split rules ---
        for r in rules_list:
            r_type = r["type"]
            r_val = r["value"]
            # If original text looks like a range (contains digit-digit or "עד"), rewrite it
            # This is a heuristic to fix "3-6 rooms" appearing as description for specific rules
            if any(x in r["original_text"] for x in ["-", "עד", "בין"]) and r_type in ["bedrooms_min", "bedrooms_max", "price_min", "price_max"]:
                if r_type == "bedrooms_min":
                    r["original_text"] = f"מינימום {r_val} חדרים"
                elif r_type == "bedrooms_max":
                    r["original_text"] = f"מקסימום {r_val} חדרים"
                elif r_type == "price_min":
                    r["original_text"] = f"מחיר מינימלי {r_val}₪"
                elif r_type == "price_max":
                    r["original_text"] = f"מחיר מקסימלי {r_val}₪"

        for rule_data in rules_list:
            rule_type = getattr(RuleType, rule_data["type"].upper(), RuleType.CUSTOM)
            rule_value = rule_data["value"]
            original_text = rule_data["original_text"]
            
            # Clean up command prefixes from original text for AREA and BORDER_AREA
            if rule_type in (RuleType.AREA, RuleType.BORDER_AREA):
                original_text = clean_hebrew_location_text(original_text)
            
            # If value is returned as a list, join it cleanly with commas
            if isinstance(rule_value, list):
                rule_value = ",".join(str(item) for item in rule_value)
            
            # Process BORDER_AREA rules: convert border descriptions to neighborhoods
            if rule_type == RuleType.BORDER_AREA:
                neighborhoods = await self._parse_border_constraints(rule_value)
                if neighborhoods:
                    # Store as comma-separated list of neighborhoods
                    neighborhood_list = ",".join(neighborhoods)
                    
                    # Don't save yet - store for confirmation
                    border_rules_pending.append({
                        'rule_type': rule_type,
                        'value': neighborhood_list,
                        'original_text': original_text,
                        'neighborhoods': neighborhoods,
                        'border_description': rule_value
                    })
                    log.info(f"Border rule parsed: {rule_value} → {len(neighborhoods)} neighborhoods")
                    continue  # Skip adding to rules_to_add for now
                else:
                    # Failed to parse borders (no directional terms), fall back to treating it as a standard AREA rule!
                    log.warning(f"Failed to parse border rule: {rule_value}. Falling back to standard AREA rule.")
                    rule_type = RuleType.AREA
                    original_text = clean_hebrew_location_text(original_text or str(rule_value))
            
            rule = SearchRule(
                user_id=user.id,
                rule_type=rule_type,
                value=str(rule_value),
                original_text=original_text
            )
            
            should_add = True
            
            # Conflict Resolution Logic:
            
            # 1. Hard Rules (Price, Bedrooms) - singleton per type
            if rule.is_hard_rule:
                for existing in existing_rules:
                    if existing.rule_type == rule.rule_type and existing.is_active:
                        log.info(f"Replacing existing rule {existing.id} ({existing.rule_type.name}) with new value")
                        await rule_repo.delete(existing.id)
            
            # 2. Soft Rules (Area, Custom) - additive but check duplicates
            elif rule.is_soft_rule:
                for existing in existing_rules:
                    if (existing.rule_type == rule.rule_type and 
                        existing.is_active and 
                        existing.value == rule.value):
                        log.info(f"Duplicate rule found: {existing.value}, skipping addition")
                        should_add = False
                        break
            
            if should_add:
                rules_to_add.append(rule)
                added_count += 1
        
        # --- UNIVERSAL CONFIRMATION FLOW ---
        # ALL rules now require confirmation before saving
        
        pending_rules_to_save = []
        
        # Add standard rules to pending
        pending_rules_to_save.extend(rules_to_add)
        
        # Create SearchRule objects for border rules and add to pending
        for b_data in border_rules_pending:
            rule = SearchRule(
                user_id=user.id,
                rule_type=b_data['rule_type'],
                # CRITICAL FIX: For BORDER_AREA, value must be CSV of neighborhoods for Matcher!
                # We keep the description in the original_text or we lose it, but Matcher needs the list.
                value=",".join(b_data['neighborhoods']) if b_data['rule_type'] == RuleType.BORDER_AREA else b_data['value'],
                original_text=clean_hebrew_location_text(b_data['original_text'])
            )
            pending_rules_to_save.append(rule)
        
        if not pending_rules_to_save:
            # No valid rules parsed
            return
        
        log.info(f"Pending {len(pending_rules_to_save)} rules for user confirmation")
        
        # Store everything in context for confirmation
        context.user_data['pending_rule_confirmation'] = {
            'user_id': user.id,
            'all_pending_rules': pending_rules_to_save,
            'border_rules_data': border_rules_pending,  # For detailed border display
            'sass_response': sass_response
        }
        
        # Format confirmation message showing ALL rules
        confirmation_msg = self._format_rules_confirmation_message(pending_rules_to_save, border_rules_pending)
        
        from bot.handlers.callback_handler import CallbackHandler
        keyboard = CallbackHandler.create_rules_confirmation_keyboard()
        
        await self._safe_reply_text(
            update,
            confirmation_msg,
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )
        return
    
    def _format_rules_confirmation_message(self, all_rules: list, border_rules_data: list = None) -> str:
        """Format a confirmation message showing ALL rules being added.
        
        Args:
            all_rules: List of SearchRule objects to be saved
            border_rules_data: Optional list of border rule dicts with 'neighborhoods' for detailed display
        
        Returns:
            Formatted confirmation message in MarkdownV2
        """
        type_names = {
            RuleType.PRICE_MAX: "💰 מחיר מקסימלי",
            RuleType.PRICE_MIN: "💰 מחיר מינימלי",
            RuleType.BEDROOMS_MIN: "🛏️ מינימום חדרים",
            RuleType.BEDROOMS_MAX: "🛏️ מקסימום חדרים",
            RuleType.AREA: "📍 מיקום",
            RuleType.BORDER_AREA: "🗺️ אזור לפי גבולות",
            RuleType.CUSTOM: "✨ דרישה מותאמת",
        }
        
        rules_text_lines = []
        
        for rule in all_rules:
            type_label = type_names.get(rule.rule_type, "• כלל")
            escaped_text = self._escape_markdown(rule.original_text)
            
            # For border rules, show the exact list of selected neighborhoods
            if rule.rule_type == RuleType.BORDER_AREA:
                neighborhoods = [n.strip() for n in rule.value.split(",") if n.strip()]
                neighborhood_count = len(neighborhoods)
                neighborhoods_list_str = ", ".join(neighborhoods)
                escaped_list = self._escape_markdown(neighborhoods_list_str)
                rules_text_lines.append(
                    f"{type_label}: {escaped_text} \\({neighborhood_count} שכונות\\)\n"
                    f"  └ *שכונות שנבחרו:* {escaped_list}"
                )
            else:
                rules_text_lines.append(f"{type_label}: {escaped_text}")
        
        rules_text = "\n".join(rules_text_lines)
        
        message = f"""
📋 *רגע, בוא נוודא שהבנתי נכון:*

{rules_text}

*זה נכון?*

💡 *טיפ:* את\\(ה\\) יכול\\(ה\\) להגיב ישירות להודעה זו כדי להוסיף או להסיר שכונות מהרשימה\\!
לדוגמה:
• _"להסיר את בבלי"_ או _"בלי בבלי"_
• _"להוסיף את פלורנטין"_ או _"תוסיף את פלורנטין"_
"""
        return message
    
    
    def _get_rule_icon(self, rule_type: RuleType) -> str:
        """Get emoji icon for rule type."""
        icons = {
            RuleType.PRICE_MAX: "💰",
            RuleType.PRICE_MIN: "💰",
            RuleType.BEDROOMS_MIN: "🛏️",
            RuleType.BEDROOMS_MAX: "🛏️",
            RuleType.AREA: "📍",
            RuleType.BORDER_AREA: "🗺️",
            RuleType.CUSTOM: "✨",
        }
        return icons.get(rule_type, "•")
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special Markdown V2 characters (using central helper)."""
        from utils.text_utils import escape_markdown
        return escape_markdown(text)

    
    def _format_border_confirmation_message(self, border_rules_data: list) -> str:
        """Format a confirmation message for border area rules.
        
        Args:
            border_rules_data: List of dicts with 'original_text' and 'neighborhoods'
        
        Returns:
            Formatted confirmation message in MarkdownV2
        """
        if len(border_rules_data) == 1:
            rule_data = border_rules_data[0]
            original = self._escape_markdown(rule_data['original_text'])
            neighborhoods = rule_data['neighborhoods']
            
            # Show first 8 neighborhoods, then "and X more"
            shown_neighborhoods = neighborhoods[:8]
            remaining_count = len(neighborhoods) - len(shown_neighborhoods)
            
            neighborhoods_text = "\n".join([
                f"• {self._escape_markdown(n.strip())}" 
                for n in shown_neighborhoods
            ])
            
            if remaining_count > 0:
                neighborhoods_text += f"\n_\\(ועוד {remaining_count} שכונות\\.\\.\\.\\)_"
            
            message = f"""
🗺️ *רגע, בוא נוודא שהבנתי נכון:*

את\\/ה מחפש\\(ת\\) דירה *{original}*

זה אומר שאני אחפש רק באזורים האלה:
{neighborhoods_text}

*זה נכון?*
"""
        else:
            # Multiple border rules
            rules_summary = "\n".join([
                f"• {self._escape_markdown(r['original_text'])}" 
                for r in border_rules_data
            ])
            
            message = f"""
🗺️ *רגע, בוא נוודא שהבנתי נכון:*

הגדרת כמה איזורים:
{rules_summary}

*זה נכון?*
"""
        
        return message
    
    async def _parse_border_constraints(self, border_text: str) -> list:
        """Parse border constraint text to determine matching neighborhoods.
        
        Args:
            border_text: Text like "מערב לאיילון, צפונית ליפו, דרומית לארלוזורוב"
        
        Returns:
            List of neighborhood names that satisfy all constraints
        """
        import re
        
        # Preprocess: Ensure directional keywords (using roots to handle final letters)
        # are separated by commas if not already, so regexes capture them correctly.
        # This handles inputs without commas like "מערב לאיילון צפונית ליפו ודרומית לארלוזורוב".
        normalized_text = border_text
        normalized_text = re.sub(
            r'(?<!,)\s+(צפו|דרו|מזרח|מערב)[א-ת]*', 
            lambda m: f", {m.group(0).strip()}", 
            normalized_text
        )
        
        constraints = {}
        location_db = get_location_db()
        
        # Extract directional constraints
        # Format: "direction ל/מ border_name"
        patterns = {
            'west_of': r'מערב(?:ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
            'east_of': r'מזרח(?:ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
            'north_of': r'צפונ(?:ה|ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
            'south_of': r'דרומ(?:ה|ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
        }
        
        for constraint_type, pattern in patterns.items():
            matches = re.findall(pattern, normalized_text)
            if matches:
                # Get the first (and typically only) border name for this direction
                border_name = matches[0].strip()
                constraints[constraint_type] = border_name
                log.info(f"Parsed border constraint: {constraint_type} = {border_name}")
        
        if not constraints:
            log.warning(f"No border constraints found in: {border_text}")
            return []
        
        # 1. Deterministic/Predefined matching
        neighborhoods = location_db.get_neighborhoods_within_borders(constraints)
        
        # 2. LLM Fallback: If deterministic matching returned no neighborhoods and AI is available,
        # fallback to LLM resolution so that unrecognized or custom borders are resolved intelligently!
        if not neighborhoods and self.ai_engine:
            log.info(f"Deterministic matching returned no neighborhoods for '{border_text}'. Falling back to LLM resolution.")
            supported = list(location_db.tel_aviv_neighborhoods.keys())
            neighborhoods = await self.ai_engine.resolve_neighborhoods_via_llm(border_text, supported)
            
            # Post-process: Filter to ensure only valid, supported neighborhoods are matched
            neighborhoods = [n for n in neighborhoods if n in location_db.tel_aviv_neighborhoods]
            log.info(f"LLM fallback matched {len(neighborhoods)} neighborhoods: {', '.join(neighborhoods)}")
        else:
            log.info(f"Border constraints {constraints} matched {len(neighborhoods)} neighborhoods: {', '.join(neighborhoods)}")
        
        return neighborhoods
