# bot/handlers/message_handler.py
"""Natural language message processing for rule definition."""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from database import get_db
from database.repositories import UserRepository, RuleRepository
from core.ai_engine import GeminiAIEngine
from models.search_rule import SearchRule, RuleType
from utils.validators import parse_rule_input
from utils.logger import Loggers
from utils.israeli_locations import get_location_db
from bot.handlers.decorators import ensure_user_exists

log = Loggers.bot()


class MessageHandler:
    """Handles natural language messages for rule definition."""
    
    def __init__(self, ai_engine: GeminiAIEngine = None):
        self.ai_engine = ai_engine
    
    async def _safe_reply_text(self, update: Update, text: str, parse_mode: str = None, **kwargs):
        """Send message safely, handling Markdown errors gracefully."""
        try:
            await update.message.reply_text(text, parse_mode=parse_mode, **kwargs)
        except BadRequest as e:
            if "can't parse entities" in str(e).lower():
                log.exception(f"Markdown parsing failed for message: {text[:200]}... Falling back to plain text.")
                # Fallback to plain text
                fallback_text = text.replace("_", "").replace("*", "") + "\n\n(שגיאת עיצוב - מציג טקסט רגיל)"
                try:
                    await update.message.reply_text(fallback_text, parse_mode=None, **kwargs)
                except Exception as e2:
                    log.error(f"Failed to send fallback message: {e2}")
            else:
                log.error(f"Telegram API error sending message: {e}")
                # Re-raise if it's not a parsing error (e.g. Chat Not Found)
                raise e
        except Exception as e:
            log.error(f"Unexpected error sending message: {e}")

    @ensure_user_exists
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process natural language rule input from user."""
        user = update.effective_user
        text = update.message.text.strip()
        
        if not text:
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
                original_text=b_data['original_text']
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
            
            # For border rules, add neighborhood count
            if rule.rule_type == RuleType.BORDER_AREA and border_rules_data:
                for b_data in border_rules_data:
                    # Match by original_text because rule.value is now the CSV list
                    if b_data['original_text'] == rule.original_text:
                        neighborhood_count = len(b_data.get('neighborhoods', []))
                        rules_text_lines.append(f"{type_label}: {escaped_text} \\({neighborhood_count} שכונות\\)")
                        break
                else: # This else belongs to the for loop, meaning no match was found
                    rules_text_lines.append(f"{type_label}: {escaped_text}")
            else:
                rules_text_lines.append(f"{type_label}: {escaped_text}")
        
        rules_text = "\n".join(rules_text_lines)
        
        message = f"""
📋 *רגע, בוא נוודא שהבנתי נכון:*

{rules_text}

*זה נכון?*
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
        """Escape special Markdown V2 characters."""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', 
                        '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
        return message
    
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
