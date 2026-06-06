# bot/handlers/command_handler.py
"""Telegram command handlers (/start, /help, /rules, etc.)."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository, RejectionRepository, ListingRepository
from bot.formatters.listing_formatter import ListingFormatter
from core.matcher import ZeroAIUserMatcher
from utils.logger import Loggers
from utils.text_utils import escape_markdown
from bot.handlers.decorators import ensure_user_exists
from bot.handlers.bot_utils import safe_reply_text

log = Loggers.bot()


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Returns the persistent main menu reply keyboard."""
    keyboard = [
        [KeyboardButton("🔎 חיפוש התאמות"), KeyboardButton("📊 סטטוס")],
        [KeyboardButton("📋 הכללים שלי"), KeyboardButton("👤 החלפת נציג")],
        [KeyboardButton("🗑️ דירות שנפסלו"), KeyboardButton("💅 קצת יחס")],
        [KeyboardButton("ℹ️ עזרה")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


class CommandHandler:
    """Handles Telegram bot commands."""
    
    async def _safe_reply_text(self, update: Update, text: str, parse_mode: str = None, **kwargs):
        """Send message safely, handling Markdown errors gracefully (using central helper)."""
        await safe_reply_text(update, text, parse_mode=parse_mode, **kwargs)

    @ensure_user_exists
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - register user and show welcome."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        log.info("User started bot", 
                 user_id=user.id, username=user.username, chat_id=chat_id)
        
        # Register user
        db = await get_db()
        user_repo = UserRepository(db)
        user_obj = await user_repo.get_or_create(user.id, chat_id, user.username)
        
        # Check if user needs onboarding (no active search rules or currently in onboarding step)
        rule_repo = RuleRepository(db)
        user_rules = await rule_repo.get_user_rules(user.id, active_only=True)
        
        is_onboarding_needed = (user_obj.onboarding_step is not None) or (not user_rules)
        
        if is_onboarding_needed:
            # Set state to choose_persona
            await user_repo.update_onboarding_step(user.id, "choose_persona")
            
            # Show the persona selection keyboard
            from core.personas import PERSONAS
            keyboard = []
            msg = f"היי *{escape_markdown(user.first_name or 'נשמה')}*\\! 🏠 ברוכים הבאים לבוט הדירות שלכם\\!\nאני אסרוק עבורכם את יד2 וקבוצות פייסבוק כל כמה דקות ואשלח לכם רק את הדירות שמתאימות לכם בול\\.\n\nלפני שנתחיל, מי הנציג שאתה רוצה שילווה אותך בחיפוש?"
            for name, p in PERSONAS.items():
                keyboard.append([
                    InlineKeyboardButton(f"{p.emoji} {p.display_name}", callback_data=f"set_persona:{name}")
                ])
            await self._safe_reply_text(
                update,
                msg,
                parse_mode='MarkdownV2',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        persona_name = user_obj.persona if hasattr(user_obj, 'persona') else 'barakush'
        
        # Generate dynamic welcome sass for onboarded user
        ai_engine = context.bot_data.get("ai_engine")
        
        if not ai_engine:
            log.error("AI engine not found in bot_data!")
            
        if ai_engine:
            try:
                log.info(f"Generating full dynamic welcome for user {user.first_name} with persona {persona_name}")
                welcome_message = await ai_engine.generate_full_welcome(user.first_name or "נשמה", persona=persona_name)
                log.info(f"Generated welcome: {welcome_message[:50]}...")
                # Escape dynamic text for MarkdownV2
                welcome_message = escape_markdown(welcome_message) 
            except Exception as e:
                log.error(f"Failed to generate welcome: {e}")
                from core.personas import get_persona
                welcome_message = get_persona(persona_name).fallback_welcome
        else:
             welcome_message = """
💅 *ברקוש כאן* 🏳️‍🌈
המערכת עולה... תכף איתכם.
"""
        
        await self._safe_reply_text(
            update,
            welcome_message, 
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
        )
    
    @ensure_user_exists
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        user_id = update.effective_user.id
        db = await get_db()
        user_repo = UserRepository(db)
        user_obj = await user_repo.get_by_telegram_id(user_id)
        persona_name = user_obj.persona if user_obj else 'barakush'
        
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        # Get dynamic sass
        ai_engine = context.bot_data.get("ai_engine")
        sass_footer = "_יאללה, תשלחו לי משהו, אני מתייבש פה\\!_"
        if ai_engine:
             try:
                sass = await ai_engine.get_random_sass(persona=persona_name)
                sass_footer = f"_{escape_markdown(sass)}_"
             except Exception as e:
                log.warning(f"Failed to get random sass in help command: {e}")

        help_message = persona_def.help_template.format(sass_footer=sass_footer)
        await self._safe_reply_text(
            update,
            help_message, 
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
        )
    
    @ensure_user_exists
    async def rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rules command - show user's active rules."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        user_repo = UserRepository(db)
        
        rules = await rule_repo.get_user_rules(user_id)
        user_obj = await user_repo.get_by_telegram_id(user_id)
        allow_bordering = user_obj.allow_bordering_neighborhoods if user_obj else True
        allow_roomies = user_obj.allow_roomies if user_obj else True
        
        message = ListingFormatter.format_rules_list(rules, allow_bordering, allow_roomies)
        
        button_border = "❌ השבת שכונות גובלות" if allow_bordering else "✅ הפעל שכונות גובלות"
        button_roomies = "❌ השבת דירות שותפים" if allow_roomies else "✅ הפעל דירות שותפים"
        keyboard = [
            [InlineKeyboardButton(button_border, callback_data="toggle_bordering")],
            [InlineKeyboardButton(button_roomies, callback_data="toggle_roomies")]
        ]
        
        await self._safe_reply_text(
            update,
            message, 
            parse_mode='MarkdownV2',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    @ensure_user_exists
    async def toggle_bordering(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /toggle_bordering command."""
        user_id = update.effective_user.id
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user_obj = await user_repo.get_by_telegram_id(user_id)
        if not user_obj:
            await update.message.reply_text("❌ משתמש לא נמצא")
            return
            
        new_status = not user_obj.allow_bordering_neighborhoods
        await user_repo.update_allow_bordering(user_id, new_status)
        
        # Friendly feedback
        persona_name = user_obj.persona
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        status_text = "פעיל כעת! אשלח לך גם דירות בשכונות סמוכות 😉" if new_status else "כבוי! אשלח לך אך ורק דירות בשכונות שהגדרת במפורש 🎯"
        
        msg = f"{persona_def.emoji} *חיפוש בשכונות גובלות {status_text}*"
        msg = escape_markdown(msg)
        
        rules = await rule_repo.get_user_rules(user_id)
        rules_message = ListingFormatter.format_rules_list(rules, new_status, user_obj.allow_roomies)
        
        button_border = "❌ השבת שכונות גובלות" if new_status else "✅ הפעל שכונות גובלות"
        button_roomies = "❌ השבת דירות שותפים" if user_obj.allow_roomies else "✅ הפעל דירות שותפים"
        keyboard = [
            [InlineKeyboardButton(button_border, callback_data="toggle_bordering")],
            [InlineKeyboardButton(button_roomies, callback_data="toggle_roomies")]
        ]
        
        await self._safe_reply_text(
            update,
            f"{msg}\n\n{rules_message}",
            parse_mode='MarkdownV2',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    @ensure_user_exists
    async def toggle_roomies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /toggle_roomies command."""
        user_id = update.effective_user.id
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        user_obj = await user_repo.get_by_telegram_id(user_id)
        if not user_obj:
            await update.message.reply_text("❌ משתמש לא נמצא")
            return
            
        new_status = not user_obj.allow_roomies
        await user_repo.update_allow_roomies(user_id, new_status)
        
        # Friendly feedback
        persona_name = user_obj.persona
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        status_text = "מאופשר כעת! אשלח לך גם דירות שותפים 😉" if new_status else "מנוטרל! אשלח לך אך ורק דירות שלמות (ללא שותפים) 🎯"
        
        msg = f"{persona_def.emoji} *קבלת דירות שותפים {status_text}*"
        msg = escape_markdown(msg)
        
        rules = await rule_repo.get_user_rules(user_id)
        rules_message = ListingFormatter.format_rules_list(rules, user_obj.allow_bordering_neighborhoods, new_status)
        
        button_border = "❌ השבת שכונות גובלות" if user_obj.allow_bordering_neighborhoods else "✅ הפעל שכונות גובלות"
        button_roomies = "❌ השבת דירות שותפים" if new_status else "✅ הפעל דירות שותפים"
        keyboard = [
            [InlineKeyboardButton(button_border, callback_data="toggle_bordering")],
            [InlineKeyboardButton(button_roomies, callback_data="toggle_roomies")]
        ]
        
        await self._safe_reply_text(
            update,
            f"{msg}\n\n{rules_message}",
            parse_mode='MarkdownV2',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @ensure_user_exists
    async def rejections(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rejections command - show recently rejected listings."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rejection_repo = RejectionRepository(db)
        rejections = await rejection_repo.get_user_rejections(user_id, limit=10)
        
        message = ListingFormatter.format_rejections_summary(rejections)
        await self._safe_reply_text(
            update,
            message, 
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
        )
    
    @ensure_user_exists
    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear command - delete all user rules."""
        user_id = update.effective_user.id
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        await rule_repo.delete_all_user_rules(user_id)
        
        log.info("User cleared all rules", user_id=user_id)
        
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
            
        await self._safe_reply_text(
            update,
            msg,
            parse_mode='MarkdownV2',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @ensure_user_exists
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
        await self._safe_reply_text(
            update,
            status_message, 
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
        )

    @ensure_user_exists
    async def sass(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sass command - give me some attitude."""
        user_id = update.effective_user.id
        db = await get_db()
        user_repo = UserRepository(db)
        user_obj = await user_repo.get_by_telegram_id(user_id)
        persona_name = user_obj.persona if user_obj else 'barakush'
        
        from core.personas import get_persona
        persona_def = get_persona(persona_name)
        
        ai_engine = context.bot_data.get("ai_engine")
        
        if ai_engine:
            try:
                sass = await ai_engine.get_random_sass(persona=persona_name)
                sass = escape_markdown(sass)
                await self._safe_reply_text(
                    update,
                    f"{persona_def.emoji} *{sass}*", 
                    parse_mode='MarkdownV2',
                    reply_markup=get_main_menu_keyboard()
                )
                return
            except Exception as e:
                log.error(f"Failed to generate sass: {e}")
        
        # Persona-specific fallback
        fallback = "אני עייפה מדי בשביל זה עכשיו"
        if persona_name == "yekke":
            fallback = "המערכת עסוקה כעת בסינון נתונים חשובים"
        elif persona_name == "mom":
            fallback = "אין לי כוח לשטויות שלך עכשיו, תתקשר לסבתא"
        elif persona_name == "stoner":
            fallback = "שנייה אחי, הראש שלי קצת בעננים כרגע"
            
        fallback = escape_markdown(fallback)
        await self._safe_reply_text(
            update,
            f"{persona_def.emoji} *{fallback}*", 
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
        )
        
    @ensure_user_exists
    async def persona(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /persona command - show current persona and allow switching."""
        user_id = update.effective_user.id
        
        db = await get_db()
        user_repo = UserRepository(db)
        user_obj = await user_repo.get_by_telegram_id(user_id)
        current_persona = user_obj.persona if user_obj else 'barakush'
        
        from core.personas import get_persona, PERSONAS
        persona_def = get_persona(current_persona)
        
        # Build message showing current persona
        escaped_display_name = escape_markdown(persona_def.display_name)
        msg = f"👤 *הנציג הנוכחי שלך:* {persona_def.emoji} *{escaped_display_name}*\n"
        msg += f"_{escape_markdown(persona_def.description)}_\n\n"
        msg += "בחר\\/י נציג אחר לחיפוש הדירות שלך:\n\n"
        
        keyboard = []
        
        for name, p in PERSONAS.items():
            if name != current_persona:
                escaped_p_display_name = escape_markdown(p.display_name)
                msg += f"• *{p.emoji} {escaped_p_display_name}*:\n"
                msg += f"  _{escape_markdown(p.description)}_\n\n"
                
                keyboard.append([
                    InlineKeyboardButton(f"החלף ל {p.emoji} {p.display_name}", callback_data=f"set_persona:{name}")
                ])
                
        # Send
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await self._safe_reply_text(
            update,
            msg,
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
    
    @ensure_user_exists
    async def matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /matches command - resend matches from last 24h."""
        user_id = update.effective_user.id
        
        # Immediate feedback
        await self._safe_reply_text(update, "🔎 מחפש התאמות מה-24 שעות האחרונות...")
        
        db = await get_db()
        rule_repo = RuleRepository(db)
        listing_repo = ListingRepository(db)
        
        # Get active rules
        rules = await rule_repo.get_user_rules(user_id)
        if not rules:
            await self._safe_reply_text(
                update,
                "📋 אין לך כללי חיפוש פעילים\\. השתמש בבוט כדי להגדיר מה אתה מחפש\\!",
                parse_mode='MarkdownV2',
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        # Get recent listings (last 24 hours)
        recent_listings = await listing_repo.get_recent_enrichments(hours=24)
        
        processing_service = context.bot_data.get("processing_service")
        
        if not processing_service:
            await self._safe_reply_text(
                update,
                "❌ שירות העיבוד לא זמין",
                reply_markup=get_main_menu_keyboard()
            )
            return
            
        from database.repositories import UserRepository
        user_repo = UserRepository(db)
        user = await user_repo.get_by_telegram_id(user_id)
        
        if not user:
             await self._safe_reply_text(
                 update,
                 "❌ משתמש לא נמצא",
                 reply_markup=get_main_menu_keyboard()
             )
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
            
        await self._safe_reply_text(
            update,
            summary,
            reply_markup=get_main_menu_keyboard()
        )
