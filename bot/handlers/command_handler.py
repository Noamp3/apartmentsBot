# bot/handlers/command_handler.py
"""Telegram command handlers (/start, /help, /rules, etc.)."""

from telegram import Update
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository, RejectionRepository, ListingRepository
from bot.formatters.listing_formatter import ListingFormatter
from core.matcher import ZeroAIUserMatcher
from utils.logger import Loggers

log = Loggers.bot()


class CommandHandler:
    """Handles Telegram bot commands."""
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - register user and show welcome."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        log.info("User started bot", 
                user_id=user.id, username=user.username, chat_id=chat_id)
        
        # Register user
        db = await get_db()
        user_repo = UserRepository(db)
        await user_repo.get_or_create(user.id, chat_id, user.username)
        
        # Generate dynamic welcome sass
        ai_engine = context.bot_data.get("ai_engine")
        dynamic_intro = ""
        if ai_engine:
            try:
                dynamic_intro = await ai_engine.generate_welcome_sass(user.first_name or "נשמה")
                # Escape dynamic text for MarkdownV2
                dynamic_intro = ListingFormatter._escape_markdown(dynamic_intro) 
            except Exception as e:
                log.error(f"Failed to generate welcome sass: {e}")
                dynamic_intro = "💅 *אמאלה, מי הגיע\\! ברקוש כאן להרים* 🏳️‍🌈"

        welcome_message = f"""
{dynamic_intro}

ברוכים הבאים לבוט הדירות היחיד שיודע להבדיל בין שיש קיסר לפורמייקה מתקלפת משנת 82'\\.

אני לא כאן כדי שתהיו נחמדים אליי, אני כאן כדי למצוא לכם דירה שתעיף לכם את הפוני \\(גם אם אין לכם\\)\\. אני אעבור על כל הזבל של יד2, אסתום את האף, ואשלח לכם רק את מה ששווה לצאת מהמיטה בשבילו\\.

*יאללה בוצ'ות שלי, מה הלירלור?*
• "דירה בתל אביב עד 5000, ותהיו עדינים איתי"
• "פלורנטין, 3 חדרים, שיהיה מקום לכל הדראג שלי"
• "דירה ליד הים, חייב מרפסת להזמין את הגברים"

*הוראות הפעלה \\(כי אתם לא הכי חדים\\):*
/rules \\- הרשימה שלי \\(שלא תגידו שלא אמרתי\\)
/rejections \\- כל הגועל נפש שסיננתי \\(ותגידו תודה\\)
/clear \\- יאללה ביי, למחוק הכל
/help \\- אחותי, הסתבכת?

_נו, תכתבו משהו, הוודג' שלי לא ישרוד לנצח\\!_
"""
        await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_message = """
📖 *הצילו, אני לא מבינה כלום*

טוב תקשיבי נשמה, אני לא המורה הפרטית שלך, אבל יאללה בואי נתקתק את זה\\.

*פשוט תגידי לי מה החלום הרטוב שלך:*
• "עד 5000 שקל" \\(כי כולנו עובדים קשה, לא רק את בצומת\\)
• "3 חדרים" \\(שיהיה מקום לאורגיות\\, או סתם לחתול\\)
• "פלורנטין" \\(אם את בקטע של עכברים ומחלות מין\\)
• "עם חניה" \\(בחלומות הלילה בצאת הכוכבים\\)

*פקודות שתצטרכו:*
/start \\- ריפרש, כמו בוטוקס
/rules \\- מה שביקשת \\(הרשימה המייגעת\\)
/rejections \\- כל מה שזרקתי לפח \\(וואו היה הרבה\\)
/matches \\- מה ששלחתי \\(אם היית עסוקה בלרדת על כרטיס אשראי\\)
/clear \\- למחוק הכל \\(כמו היסטוריית הגלישה שלך\\)
/status \\- כמה אני עובד קשה \\(יותר ממך, בטוח\\)

*טיפ של ברקוש:*
אני מחשב "מחיר אפקטיבי" עם תיווך, כדי שלא יזיינו אתכם במחיר \\(זה התפקיד שלי\\)\\. סתם, נשמה, אני כאן לעזור\\!

_יאללה, תשלחו לי משהו, אני מתייבש פה\\!_
"""
        await update.message.reply_text(help_message, parse_mode='MarkdownV2')
    
    async def rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rules command - show user's active rules."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        rules = await rule_repo.get_user_rules(user_id)
        
        message = ListingFormatter.format_rules_list(rules)
        await update.message.reply_text(message, parse_mode='MarkdownV2')
    
    async def rejections(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rejections command - show recently rejected listings."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rejection_repo = RejectionRepository(db)
        rejections = await rejection_repo.get_user_rejections(user_id, limit=10)
        
        message = ListingFormatter.format_rejections_summary(rejections)
        await update.message.reply_text(message, parse_mode='MarkdownV2')
    
    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear command - delete all user rules."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        await rule_repo.delete_all_user_rules(user_id)
        
        log.info("User cleared all rules", user_id=user_id)
        
        await update.message.reply_text(
            "🗑️ כל כללי החיפוש שלך נמחקו\\.\n\nשלח הודעה חדשה כדי להתחיל מחדש\\!",
            parse_mode='MarkdownV2'
        )
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show bot status."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        rejection_repo = RejectionRepository(db)
        
        rules = await rule_repo.get_user_rules(user_id)
        stats = await rejection_repo.get_rejection_stats(user_id)
        
        rules_count = len(rules)
        rejections_count = stats.get("total_rejections", 0)
        
        status_message = f"""
📊 *סטטוס*

*הכללים שלך:* {rules_count}
*דירות שנפסלו \\(7 ימים\\):* {rejections_count}

_הבוט פעיל וסורק דירות חדשות כל מספר דקות_
"""
        await update.message.reply_text(status_message, parse_mode='MarkdownV2')
    
    async def matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /matches command - resend matches from last 24h."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        # Immediate feedback
        await update.message.reply_text("🔎 מחפש התאמות מה-24 שעות האחרונות...")
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        listing_repo = ListingRepository(db)
        
        # Get active rules
        rules = await rule_repo.get_user_rules(user_id)
        if not rules:
            await update.message.reply_text(
                "📋 אין לך כללי חיפוש פעילים. השתמש בבוט כדי להגדיר מה אתה מחפש!",
                parse_mode='MarkdownV2'
            )
            return
        
        # Get recent listings (last 24 hours)
        recent_listings = await listing_repo.get_recent_enrichments(hours=24)
        
        matcher = ZeroAIUserMatcher()
        matches_found = 0
        
        for enriched in recent_listings:
            is_match, _ = matcher.evaluate_listing(enriched, rules)
            
            if is_match:
                matches_found += 1
                try:
                    # Use formatter but send directly via context.bot to ensure proper async execution
                    # independent of the main bot loop
                    message = ListingFormatter.format_listing(
                        enriched, 
                        bordering_note=""  # Simplification: re-matches don't check bordering logic explicitly here yet
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode='MarkdownV2',
                        disable_web_page_preview=False
                    )
                except Exception as e:
                    log.error(f"Failed to send match {enriched.listing.id}: {e}")
        
        # Summary
        if matches_found > 0:
            summary = f"✅ נמצאו {matches_found} דירות מתאימות מהיממה האחרונה."
        else:
            summary = "❌ לא נמצאו דירות מתאימות מהיממה האחרונה.\nנסה לשנות את כללי החיפוש או המתן לדירות חדשות."
            
        await update.message.reply_text(summary)
