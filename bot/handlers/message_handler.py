# bot/handlers/message_handler.py
"""Natural language message processing for rule definition."""

from telegram import Update
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository
from core.ai_engine import GeminiAIEngine
from models.search_rule import SearchRule, RuleType
from utils.validators import parse_rule_input
from utils.logger import Loggers

log = Loggers.bot()


class MessageHandler:
    """Handles natural language messages for rule definition."""
    
    def __init__(self, ai_engine: GeminiAIEngine = None):
        self.ai_engine = ai_engine
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process natural language rule input from user."""
        user = update.effective_user
        text = update.message.text.strip()
        
        if not text:
            return
        
        log.info("User message received", user_id=user.id, text=text[:50])
        
        # Parse rules using AI
        try:
            if self.ai_engine:
                rules_list, sass_response = await self.ai_engine.parse_user_rules(text)
            else:
                log.error("No AI engine available")
                return
        except Exception as e:
            log.error(f"Failed to parse rules: {e}")
            await update.message.reply_text(
                "אופס, המוח שלי קרס לרגע. נסה שוב? 😵‍💫",
                parse_mode='MarkdownV2'
            )
            return

        if not rules_list:
            await update.message.reply_text(
                "לא הבנתי כלום מאמי. נסה להיות יותר ספציפי (למשל: 'דירה בתל אביב ב-5000 שקל')",
                parse_mode='MarkdownV2'
            )
            return

        # Add rules to DB
        db = await get_db()
        rule_repo = RuleRepository(db)
        
        added_count = 0
        rules_to_add = []
        
        for rule_data in rules_list:
            rule_type = getattr(RuleType, rule_data["type"].upper(), RuleType.CUSTOM)
            
            rule = SearchRule(
                user_id=user.id,
                rule_type=rule_type,
                value=rule_data["value"],
                original_text=rule_data["original_text"]
            )
            
            await rule_repo.create(rule) # Changed from add_rule to create to match existing repo method
            rules_to_add.append(rule)
            added_count += 1
        
        log.info(f"Added {added_count} rules for user {user.id}")
        
        # Confirm to user
        escaped_sass = self._escape_markdown(sass_response) if sass_response else "_יצאתי לחפש לך, נראה מה אמצא..._"
        
        if added_count == 1:
            rule = rules_to_add[0]
            type_names = {
                RuleType.PRICE_MAX: "מחיר מקסימלי",
                RuleType.PRICE_MIN: "מחיר מינימלי",
                RuleType.BEDROOMS_MIN: "מינימום חדרים",
                RuleType.BEDROOMS_MAX: "מקסימום חדרים",
                RuleType.AREA: "מיקום",
                RuleType.CUSTOM: "דרישה מותאמת",
            }
            type_name = type_names.get(rule.rule_type, "כלל")
            
            response = f"""
✅ *קלטתי אותך:*

{self._get_rule_icon(rule.rule_type)} *{type_name}:* {rule.original_text}

_{escaped_sass}_
"""
        else:
            rules_text = "\n".join([
                f"• {r.original_text}" for r in rules_to_add
            ])
            rules_text = self._escape_markdown(rules_text)
            
            response = f"""
✅ *הוספתי {added_count} שריטות לרשימה:*

{rules_text}

_{escaped_sass}_
"""
        
        await update.message.reply_text(response, parse_mode='MarkdownV2')
    
    def _get_rule_icon(self, rule_type: RuleType) -> str:
        """Get emoji icon for rule type."""
        icons = {
            RuleType.PRICE_MAX: "💰",
            RuleType.PRICE_MIN: "💰",
            RuleType.BEDROOMS_MIN: "🛏️",
            RuleType.BEDROOMS_MAX: "🛏️",
            RuleType.AREA: "📍",
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
