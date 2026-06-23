# bot/handlers/onboarding_handler.py
"""Onboarding wizard logic for new users."""

import re
from datetime import datetime, timedelta
from typing import Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository, ListingRepository
from core.ai_engine import GeminiAIEngine
from models.search_rule import SearchRule, RuleType
from utils.logger import Loggers
from utils.israeli_locations import get_location_db
from utils.text_utils import escape_markdown

log = Loggers.bot()


def clean_hebrew_location_text(text: str) -> str:
    """Clean common command/prefix words from Hebrew geographic search text."""
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


class OnboardingHandler:
    """Handles onboarding step-by-step logic and wizard states."""
    
    def __init__(self, ai_engine: Optional[GeminiAIEngine] = None):
        self.ai_engine = ai_engine
        
    def _escape_markdown(self, text: str) -> str:
        return escape_markdown(text)
        
    async def _safe_reply_text(self, update: Update, text: str, parse_mode: str = None, **kwargs):
        from bot.handlers.bot_utils import safe_reply_text
        await safe_reply_text(update, text, parse_mode=parse_mode, **kwargs)

    def _should_bypass_ai(self, text: str, step: str) -> bool:
        """Heuristics to check if input should bypass AI rule parsing during onboarding."""
        clean_text = text.strip()
        
        # Extract all numbers from the text (ignoring symbols/punctuation)
        numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', clean_text.replace(',', ''))]
        
        # Keywords for other categories
        price_keywords = ["שקל", "ש\"ח", "₪", "תקציב", "מחיר", "במחיר"]
        bedroom_keywords = ["חדר", "חדרים", "חצי", "beds", "rooms"]
        
        # Helper: does text contain any keyword from a list?
        def contains_any(kw_list):
            return any(kw in clean_text for kw in kw_list)
        
        has_price_indicator = contains_any(price_keywords) or any(num > 100 for num in numbers)
        has_bedroom_indicator = contains_any(bedroom_keywords) or any(0.5 <= num <= 10 for num in numbers)
        
        if step == "ask_location":
            # Bypass AI if there are no price or bedroom indicators
            return not (has_price_indicator or has_bedroom_indicator)
            
        elif step == "ask_budget":
            # Bypass AI if there are no bedroom indicators AND it contains at least one number
            return not has_bedroom_indicator and len(numbers) >= 1
            
        elif step == "ask_bedrooms":
            # Bypass AI if there are no price indicators
            return not has_price_indicator
            
        return False

    def _is_multi_rule(self, rules_list: list) -> bool:
        """Check if rules_list contains rules from at least 2 distinct categories."""
        categories = set()
        for r in rules_list:
            r_type = r.get("type", "")
            if r_type in ["area", "border_area"]:
                categories.add("location")
            elif r_type in ["price_min", "price_max"]:
                categories.add("price")
            elif r_type in ["bedrooms_min", "bedrooms_max"]:
                categories.add("bedrooms")
            elif r_type == "custom":
                categories.add("custom")
        return len(categories) >= 2

    async def _parse_border_constraints(self, border_text: str) -> list:
        """Parse border constraint text to determine matching neighborhoods."""
        # Preprocess: Ensure directional keywords are separated by commas
        normalized_text = border_text
        normalized_text = re.sub(
            r'(?<!,)\s+(צפו|דרו|מזרח|מערב)[א-ת]*', 
            lambda m: f", {m.group(0).strip()}", 
            normalized_text
        )
        
        constraints = {}
        location_db = get_location_db()
        
        # Extract directional constraints
        patterns = {
            'west_of': r'מערב(?:ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
            'east_of': r'מזרח(?:ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
            'north_of': r'צפונ(?:ה|ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
            'south_of': r'דרומ(?:ה|ית)?\s+(?:ל|מ)([א-ת\s]+?)(?:,|$|\s+ו)',
        }
        
        for constraint_type, pattern in patterns.items():
            matches = re.findall(pattern, normalized_text)
            if matches:
                border_name = matches[0].strip()
                constraints[constraint_type] = border_name
                log.info(f"Parsed border constraint: {constraint_type} = {border_name}")
        
        if not constraints:
            log.warning(f"No border constraints found in: {border_text}")
            return []
        
        # 1. Deterministic/Predefined matching
        neighborhoods = location_db.get_neighborhoods_within_borders(constraints)
        
        # 2. LLM Fallback
        if not neighborhoods and self.ai_engine:
            log.info(f"Deterministic matching returned no neighborhoods for '{border_text}'. Falling back to LLM resolution.")
            supported = list(location_db.tel_aviv_neighborhoods.keys())
            neighborhoods = await self.ai_engine.resolve_neighborhoods_via_llm(border_text, supported)
            neighborhoods = [n for n in neighborhoods if n in location_db.tel_aviv_neighborhoods]
            log.info(f"LLM fallback matched {len(neighborhoods)} neighborhoods: {', '.join(neighborhoods)}")
        else:
            log.info(f"Border constraints {constraints} matched {len(neighborhoods)} neighborhoods: {', '.join(neighborhoods)}")
        
        return neighborhoods

    async def handle_onboarding_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_obj: object, text: str):
        """Handle active onboarding step."""
        user_id = user_obj.telegram_id
        db = await get_db()
        user_repo = UserRepository(db)
        persona_name = user_obj.persona or 'barakush'
        
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        step = user_obj.onboarding_step
        log.info("Processing onboarding step", user_id=user_id, step=step, text=text[:50])
        
        if step in ["ask_location", "ask_budget", "ask_bedrooms"]:
            # Check if we should bypass AI parsing for a single-rule input
            bypass_ai = self._should_bypass_ai(text, step)
            
            # If we don't bypass AI AND we have an AI engine, attempt multi-rule parsing
            if not bypass_ai and self.ai_engine:
                try:
                    rules_list, sass_response = await self.ai_engine.parse_user_rules(text, persona=persona_name)
                    if rules_list and self._is_multi_rule(rules_list):
                        log.info("Multi-rule onboarding input detected. Direct completion.", user_id=user_id, rules_count=len(rules_list))
                        
                        # Merge newly parsed rules with any existing accumulated onboarding rules
                        existing_rules = context.user_data.get('onboarding_rules', [])
                        all_rules_data = list(existing_rules)
                        
                        # Overwrite conflicting rule types with the new values
                        for r_new in rules_list:
                            r_new_type = r_new["type"]
                            is_hard = r_new_type in ["price_max", "price_min", "bedrooms_min", "bedrooms_max", "size_min"]
                            if is_hard:
                                all_rules_data = [r for r in all_rules_data if r["type"] != r_new_type]
                            all_rules_data.append(r_new)
                            
                        # Pre-processing: Auto-generate max bedrooms if only min is present
                        has_min_beds = False
                        has_max_beds = False
                        min_beds_val = 0.0
                        for r in all_rules_data:
                            if r["type"] == "bedrooms_min":
                                has_min_beds = True
                                try:
                                    min_beds_val = float(r["value"])
                                except ValueError:
                                    min_beds_val = 0.0
                            elif r["type"] == "bedrooms_max":
                                has_max_beds = True
                        if has_min_beds and not has_max_beds and min_beds_val > 0:
                            max_val = min_beds_val + 3.0
                            all_rules_data.append({
                                "type": "bedrooms_max",
                                "value": max_val,
                                "original_text": f"מקסימום {max_val} חדרים (אוטומטי)"
                            })
                            
                        # Complete onboarding and save all rules to DB
                        await user_repo.update_onboarding_step(user_id, None)
                        
                        rule_repo = RuleRepository(db)
                        
                        search_rules_list = []
                        for r_data in all_rules_data:
                            r_type_str = r_data["type"]
                            rule_type = getattr(RuleType, r_type_str.upper(), RuleType.CUSTOM)
                            rule_value = r_data["value"]
                            original_text = r_data["original_text"]
                            
                            # Clean up original text for AREA and BORDER_AREA
                            if rule_type in (RuleType.AREA, RuleType.BORDER_AREA):
                                original_text = clean_hebrew_location_text(original_text)
                            
                            if rule_type == RuleType.BORDER_AREA:
                                neighborhoods = await self._parse_border_constraints(str(rule_value))
                                if neighborhoods:
                                    rule_value = ",".join(neighborhoods)
                                else:
                                    rule_type = RuleType.AREA
                                    original_text = clean_hebrew_location_text(original_text or str(rule_value))
                                    
                            rule = SearchRule(
                                user_id=user_id,
                                rule_type=rule_type,
                                value=str(rule_value),
                                original_text=original_text
                            )
                            await rule_repo.create(rule)
                            search_rules_list.append(rule)
                            
                        context.user_data.pop('onboarding_rules', None)
                        
                        sass_extra = ""
                        try:
                            sass = await self.ai_engine.get_random_sass(persona=persona_name)
                            sass_extra = f"\n\n_{self._escape_markdown(sass)}_"
                        except Exception:
                            pass
                            
                        rules_summary = []
                        type_names = {
                            RuleType.PRICE_MAX: "💰 מחיר מקסימלי",
                            RuleType.PRICE_MIN: "💰 מחיר מינימלי",
                            RuleType.BEDROOMS_MIN: "🛏️ מינימום חדרים",
                            RuleType.BEDROOMS_MAX: "🛏️ מקסימום חדרים",
                            RuleType.SIZE_MIN: "📏 מינימום גודל",
                            RuleType.AREA: "📍 מיקום",
                            RuleType.BORDER_AREA: "🗺️ אזור לפי גבולות",
                            RuleType.CUSTOM: "✨ דרישה מותאמת",
                        }
                        for rule in search_rules_list:
                            type_label = type_names.get(rule.rule_type, "• כלל")
                            escaped_text = self._escape_markdown(rule.original_text)
                            if rule.rule_type == RuleType.BORDER_AREA:
                                neighborhoods = [n.strip() for n in rule.value.split(",") if n.strip()]
                                count = len(neighborhoods)
                                neighborhoods_list_str = ", ".join(neighborhoods)
                                escaped_list = self._escape_markdown(neighborhoods_list_str)
                                rules_summary.append(
                                    f"{type_label}: {escaped_text} \\({count} שכונות\\)\n"
                                    f"  └ *שכונות שנבחרו:* {escaped_list}"
                                )
                            else:
                                rules_summary.append(f"{type_label}: {escaped_text}")
                            
                        rules_summary_str = "\n".join(rules_summary)
                        welcome_template = """
🎉 *מזל טוב\\! סיימנו להגדיר את החיפוש שלך\\!* 🚀

הנה הכללים ששמרתי בשבילך:
{rules_summary_str}

מכאן והלאה אני רץ כל כמה דקות על כל הפרסומים ביד2 ובקבוצות הפייסבוק הכי שוות, מסנן את כל הזבל ומביא לך רק מה שמתאים בול\\!{sass_extra}
"""
                        from bot.handlers.command_handler import get_main_menu_keyboard
                        await self._safe_reply_text(
                            update,
                            welcome_template.format(
                                rules_summary_str=rules_summary_str,
                                sass_extra=sass_extra
                            ),
                            parse_mode='MarkdownV2',
                            reply_markup=get_main_menu_keyboard()
                        )
                        
                        processing_service = context.bot_data.get("processing_service")
                        if processing_service:
                            listing_repo = ListingRepository(db)
                            recent_listings = await listing_repo.get_recent_enrichments(hours=24)
                            if recent_listings:
                                await update.message.reply_text("🔎 בודק אם יש משהו רלוונטי מהיממה האחרונה...")
                                matches = await processing_service.match_user_to_listings(
                                    user_obj, recent_listings, is_manual_trigger=True
                                )
                                if matches > 0:
                                    await update.message.reply_text(f"✨ מצאתי {matches} דירות מתאימות מהיממה האחרונה!")
                                else:
                                    from core.personas import get_persona
                                    p = get_persona(user_obj.persona)
                                    await update.message.reply_text(p.no_matches_found)
                        return
                except Exception as e:
                    log.error(f"Failed to parse multi-rule onboarding message: {e}")
                    # On error, fallback to step-by-step logic

        if step == "choose_persona":
            from core.personas import PERSONAS
            keyboard = []
            msg = "היי! 🏠 ברוכים הבאים לבוט הדירות שלכם! אני אסרוק עבורכם את יד2 וקבוצות פייסבוק כל כמה דקות ואשלח לכם רק את הדירות שמתאימות לכם בול.\n\nלפני שמתחילים, מי הנציג שאתם רוצים שילווה אתכם בחיפוש?"
            for name, p in PERSONAS.items():
                keyboard.append([
                    InlineKeyboardButton(f"{p.emoji} {p.display_name}", callback_data=f"set_persona:{name}")
                ])
            await self._safe_reply_text(
                update,
                msg,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        elif step == "ask_location":
            from utils.israeli_locations import get_location_db
            location_db = get_location_db()
            
            has_directions = any(x in text for x in ["מערב", "מזרח", "צפון", "דרום"])
            
            rules_to_save = []
            
            if has_directions:
                neighborhoods = await self._parse_border_constraints(text)
                if neighborhoods:
                    rules_to_save.append({
                        "type": "border_area",
                        "value": ",".join(neighborhoods),
                        "original_text": clean_hebrew_location_text(text)
                    })
                else:
                    # Fall back to standard area splitting and normalization
                    parts = re.split(r'\s+ו|\s+(?:או)\s+|\s*,\s*', text)
                    for part in parts:
                        part_stripped = part.strip()
                        if not part_stripped:
                            continue
                        cleaned_part = clean_hebrew_location_text(part_stripped)
                        normalized = location_db.normalize_location(cleaned_part)
                        rules_to_save.append({
                            "type": "area",
                            "value": normalized["neighborhood"] if normalized["neighborhood"] else cleaned_part,
                            "original_text": cleaned_part
                        })
            else:
                parts = re.split(r'\s+ו|\s+(?:או)\s+|\s*,\s*', text)
                for part in parts:
                    part_stripped = part.strip()
                    if not part_stripped:
                        continue
                    cleaned_part = clean_hebrew_location_text(part_stripped)
                    normalized = location_db.normalize_location(cleaned_part)
                    rules_to_save.append({
                        "type": "area",
                        "value": normalized["neighborhood"] if normalized["neighborhood"] else cleaned_part,
                        "original_text": cleaned_part
                    })
            
            context.user_data['onboarding_rules'] = rules_to_save
            await user_repo.update_onboarding_step(user_id, "ask_budget")
            
            await self._safe_reply_text(
                update,
                persona_def.onboarding_ask_budget,
                parse_mode='MarkdownV2'
            )
            
        elif step == "ask_budget":
            digits = [int(d) for d in re.findall(r'\d+', text.replace(',', '').replace('.', ''))]
            if not digits:
                error_msg = "אופס, לא מצאתי מספר בתשובה שלך. אנא הזן תקציב במספר בלבד (למשל: 5000):"
                if persona_name == "barakush":
                    error_msg = "מאמי, אני צריכה מספרים, לא סיפורים 💅 תביאי לי רק את המחיר (למשל: 5000):"
                elif persona_name == "yekke":
                    error_msg = "שגיאה: קלט לא חוקי. נא להזין ערך מספרי בלבד לתקציב המרבי (למשל: 5000):"
                elif persona_name == "mom":
                    error_msg = "אוי, לא הבנתי כמה כסף זה! תכתוב לי רק את המספר בבקשה נשמה שלי (למשל: 5000):"
                elif persona_name == "stoner":
                    error_msg = "לא הכי זרם לי המספר אחי, תביא לי רק ספרות גבר (למשל: 5000):"
                
                await self._safe_reply_text(update, error_msg)
                return
            
            onboarding_rules = context.user_data.get('onboarding_rules', [])
            
            if len(digits) >= 2:
                min_price = min(digits)
                max_price = max(digits)
                onboarding_rules.append({
                    "type": "price_min",
                    "value": min_price,
                    "original_text": f"מחיר מינימלי {min_price}₪"
                })
                onboarding_rules.append({
                    "type": "price_max",
                    "value": max_price,
                    "original_text": f"עד {max_price}₪"
                })
            else:
                price_val = digits[0]
                is_min = any(x in text for x in ["לפחות", "מינימום", "מעל", "מ-"])
                if is_min:
                    onboarding_rules.append({
                        "type": "price_min",
                        "value": price_val,
                        "original_text": f"מחיר מינימלי {price_val}₪"
                    })
                else:
                    onboarding_rules.append({
                        "type": "price_max",
                        "value": price_val,
                        "original_text": f"עד {price_val}₪"
                    })
                    
            context.user_data['onboarding_rules'] = onboarding_rules
            await user_repo.update_onboarding_step(user_id, "ask_bedrooms")
            
            await self._safe_reply_text(
                update,
                persona_def.onboarding_ask_bedrooms,
                parse_mode='MarkdownV2'
            )
            
        elif step == "ask_bedrooms":
            digits = [float(d) for d in re.findall(r'\d+(?:\.\d+)?', text)]
            
            min_beds = None
            max_beds = None
            
            if len(digits) >= 2:
                min_beds = min(digits)
                max_beds = max(digits)
            elif len(digits) == 1:
                min_beds = digits[0]
                if any(x in text for x in ["עד", "מקסימום"]):
                    max_beds = min_beds
                    min_beds = 1.0
                else:
                    min_beds = digits[0]
                    max_beds = min_beds + 3.0
            else:
                min_beds = 2.0
                max_beds = 5.0
                
            onboarding_rules = context.user_data.get('onboarding_rules', [])
            
            onboarding_rules.append({
                "type": "bedrooms_min",
                "value": min_beds,
                "original_text": f"מינימום {min_beds} חדרים"
            })
            
            onboarding_rules.append({
                "type": "bedrooms_max",
                "value": max_beds,
                "original_text": f"מקסימום {max_beds} חדרים"
            })
            
            await user_repo.update_onboarding_step(user_id, None)
            
            rule_repo = RuleRepository(db)
            search_rules_list = []
            
            for r_data in onboarding_rules:
                rule_type = getattr(RuleType, r_data["type"].upper(), RuleType.CUSTOM)
                rule = SearchRule(
                    user_id=user_id,
                    rule_type=rule_type,
                    value=str(r_data["value"]),
                    original_text=r_data["original_text"]
                )
                await rule_repo.create(rule)
                search_rules_list.append(rule)
                
            context.user_data.pop('onboarding_rules', None)
            
            sass_extra = ""
            if self.ai_engine:
                try:
                    sass = await self.ai_engine.get_random_sass(persona=persona_name)
                    sass_extra = f"\n\n_{self._escape_markdown(sass)}_"
                except Exception:
                    pass
            
            rules_summary = []
            type_names = {
                RuleType.PRICE_MAX: "💰 מחיר מקסימלי",
                RuleType.PRICE_MIN: "💰 מחיר מינימלי",
                RuleType.BEDROOMS_MIN: "🛏️ מינימום חדרים",
                RuleType.BEDROOMS_MAX: "🛏️ מקסימום חדרים",
                RuleType.SIZE_MIN: "📏 מינימום גודל",
                RuleType.AREA: "📍 מיקום",
                RuleType.BORDER_AREA: "🗺️ אזור לפי גבולות",
                RuleType.CUSTOM: "✨ דרישה מותאמת",
            }
            
            for rule in search_rules_list:
                type_label = type_names.get(rule.rule_type, "• כלל")
                escaped_text = self._escape_markdown(rule.original_text)
                if rule.rule_type == RuleType.BORDER_AREA:
                    neighborhoods = [n.strip() for n in rule.value.split(",") if n.strip()]
                    count = len(neighborhoods)
                    neighborhoods_list_str = ", ".join(neighborhoods)
                    escaped_list = self._escape_markdown(neighborhoods_list_str)
                    rules_summary.append(
                        f"{type_label}: {escaped_text} \\({count} שכונות\\)\n"
                        f"  └ *שכונות שנבחרו:* {escaped_list}"
                    )
                else:
                    rules_summary.append(f"{type_label}: {escaped_text}")
                
            rules_summary_str = "\n".join(rules_summary)
            welcome_template = """
🎉 *מזל טוב\\! סיימנו להגדיר את החיפוש שלך\\!* 🚀

הנה הכללים ששמרתי בשבילך:
{rules_summary_str}

מכאן והלאה אני רץ כל כמה דקות על כל הפרסומים ביד2 ובקבוצות הפייסבוק הכי שוות, מסנן את כל הזבל ומביא לך רק מה שמתאים בול\\!{sass_extra}
"""
            
            from bot.handlers.command_handler import get_main_menu_keyboard
            await self._safe_reply_text(
                update,
                welcome_template.format(
                    rules_summary_str=rules_summary_str,
                    sass_extra=sass_extra
                ),
                parse_mode='MarkdownV2',
                reply_markup=get_main_menu_keyboard()
            )
            
            processing_service = context.bot_data.get("processing_service")
            if processing_service:
                listing_repo = ListingRepository(db)
                recent_listings = await listing_repo.get_recent_enrichments(hours=24)
                if recent_listings:
                    await update.message.reply_text("🔎 בודק אם יש משהו רלוונטי מהיממה האחרונה...")
                    matches = await processing_service.match_user_to_listings(
                        user_obj, recent_listings, is_manual_trigger=True
                    )
                    if matches > 0:
                        await update.message.reply_text(f"✨ מצאתי {matches} דירות מתאימות מהיממה האחרונה!")
                    else:
                        from core.personas import get_persona
                        p = get_persona(user_obj.persona)
                        await update.message.reply_text(p.no_matches_found)
