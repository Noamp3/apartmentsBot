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
        
        if not ai_engine:
            log.error("AI engine not found in bot_data!")
            
        if ai_engine:
            try:
                log.info(f"Generating full dynamic welcome for user {user.first_name}")
                welcome_message = await ai_engine.generate_full_welcome(user.first_name or "נשמה")
                log.info(f"Generated welcome: {welcome_message[:50]}...")
                # Escape dynamic text for MarkdownV2
                welcome_message = ListingFormatter._escape_markdown(welcome_message) 
            except Exception as e:
                log.error(f"Failed to generate welcome: {e}")
                welcome_message = """
💅 *ברקוש כאן, והמוח שלי בחופשה (שגיאה)* 🏳️‍🌈

קרסתי, נשמה. אבל אני עדיין עובד:

*אז מה הלו"ז?*
תכתבו לי דרישות (למשל "דירה בפלורנטין 3 חדרים").

*פקודות:*
/rules \\- חוקים
/rejections \\- פסילות
/clear \\- איפוס
/help \\- עזרה

_תנסו שוב עוד מעט, אולי אני אתעורר על עצמי_
"""
        else:
             welcome_message = """
💅 *ברקוש כאן* 🏳️‍🌈
המערכת עולה... תכף איתכם.
"""
        
        await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        
        # Get dynamic sass
        ai_engine = context.bot_data.get("ai_engine")
        sass_footer = "_יאללה, תשלחו לי משהו, אני מתייבש פה\\!_"
        if ai_engine:
             try:
                sass = await ai_engine.get_random_sass()
                sass_footer = f"_{ListingFormatter._escape_markdown(sass)}_"
             except Exception:
                pass

        help_message = f"""
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

{sass_footer}
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
        
        # Get dynamic sass
        ai_engine = context.bot_data.get("ai_engine")
        sass_extra = ""
        if ai_engine:
             try:
                sass = await ai_engine.get_random_sass()
                sass_extra = f"\n\n_{ListingFormatter._escape_markdown(sass)}_"
             except Exception:
                pass

        await update.message.reply_text(
            f"🗑️ כל כללי החיפוש שלך נמחקו\\.\n\nשלח הודעה חדשה כדי להתחיל מחדש\\!{sass_extra}",
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

    async def sass(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sass command - give me some attitude."""
        ai_engine = context.bot_data.get("ai_engine")
        
        if ai_engine:
            try:
                sass = await ai_engine.get_random_sass()
                sass = ListingFormatter._escape_markdown(sass)
                await update.message.reply_text(f"💅 *{sass}*", parse_mode='MarkdownV2')
                return
            except Exception as e:
                log.error(f"Failed to generate sass: {e}")
        
        await update.message.reply_text("💅 *אני עייפה מדי בשביל זה עכשיו*", parse_mode='MarkdownV2')
    
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
        
        processing_service = context.bot_data.get("processing_service")
        
        if not processing_service:
            await update.message.reply_text("❌ שירות העיבוד לא זמין")
            return
            
        from database.repositories import UserRepository
        user_repo = UserRepository(db)
        user = await user_repo.get_by_telegram_id(user_id)
        
        if not user:
             await update.message.reply_text("❌ משתמש לא נמצא")
             return

        # Use ProcessingService with include_sent=True
        # This ensures we resend notifications even if they were sent before
        matches_found = await processing_service.match_user_to_listings(
            user, 
            recent_listings, 
            is_manual_trigger=True,
            include_sent=True
        )
        
        # Summary
        if matches_found > 0:
            summary = f"✅ נמצאו {matches_found} דירות מתאימות מהיממה האחרונה."
        else:
            summary = "❌ לא נמצאו דירות מתאימות מהיממה האחרונה.\nנסה לשנות את כללי החיפוש או המתן לדירות חדשות."
            
        await update.message.reply_text(summary)
