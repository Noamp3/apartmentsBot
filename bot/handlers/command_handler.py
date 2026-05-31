# bot/handlers/command_handler.py
"""Telegram command handlers (/start, /help, /rules, etc.)."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository, RejectionRepository, ListingRepository
from bot.formatters.listing_formatter import ListingFormatter
from core.matcher import ZeroAIUserMatcher
from utils.logger import Loggers
from bot.handlers.decorators import ensure_user_exists, admin_required

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
        """Send message safely, handling Markdown errors gracefully."""
        from telegram.error import BadRequest
        try:
            await update.message.reply_text(text, parse_mode=parse_mode, **kwargs)
        except BadRequest as e:
            if "can't parse entities" in str(e).lower():
                log.exception(f"Markdown parsing failed in CommandHandler for message: {text[:200]}... Falling back to plain text.")
                # Fallback to plain text
                fallback_text = text.replace("_", "").replace("*", "").replace("\\", "").replace("[", "").replace("]", "").replace("(", "").replace(")", "") + "\n\n(שגיאת עיצוב)"
                try:
                    await update.message.reply_text(fallback_text, parse_mode=None, **kwargs)
                except Exception as e2:
                    log.error(f"Failed to send fallback message: {e2}")
            else:
                log.error(f"Telegram API error sending message in CommandHandler: {e}")
                raise e
        except Exception as e:
            log.error(f"Unexpected error sending message in CommandHandler: {e}")

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
            msg = f"היי *{ListingFormatter._escape_markdown(user.first_name or 'נשמה')}*\\! 🏠 ברוכים הבאים לבוט הדירות שלכם\\!\nאני אסרוק עבורכם את יד2 וקבוצות פייסבוק כל כמה דקות ואשלח לכם רק את הדירות שמתאימות לכם בול\\.\n\nלפני שנתחיל, מי הנציג שאתה רוצה שילווה אותך בחיפוש?"
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
                welcome_message = ListingFormatter._escape_markdown(welcome_message) 
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
                sass_footer = f"_{ListingFormatter._escape_markdown(sass)}_"
             except Exception:
                pass

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
        rules = await rule_repo.get_user_rules(user_id)
        
        message = ListingFormatter.format_rules_list(rules)
        await self._safe_reply_text(
            update,
            message, 
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
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
                sass = ListingFormatter._escape_markdown(sass)
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
            
        fallback = ListingFormatter._escape_markdown(fallback)
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
        escaped_display_name = ListingFormatter._escape_markdown(persona_def.display_name)
        msg = f"👤 *הנציג הנוכחי שלך:* {persona_def.emoji} *{escaped_display_name}*\n"
        msg += f"_{ListingFormatter._escape_markdown(persona_def.description)}_\n\n"
        msg += "בחר\\/י נציג אחר לחיפוש הדירות שלך:\n\n"
        
        keyboard = []
        
        for name, p in PERSONAS.items():
            if name != current_persona:
                escaped_p_display_name = ListingFormatter._escape_markdown(p.display_name)
                msg += f"• *{p.emoji} {escaped_p_display_name}*:\n"
                msg += f"  _{ListingFormatter._escape_markdown(p.description)}_\n\n"
                
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
        chat_id = update.effective_chat.id
        
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

    @ensure_user_exists
    @admin_required
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show the admin dashboard."""
        db = await get_db()
        
        # Count stats
        users_count = (await db.fetch_one("SELECT COUNT(*) as count FROM users"))["count"]
        active_users = (await db.fetch_one("SELECT COUNT(*) as count FROM users WHERE is_active = 1"))["count"]
        rules_count = (await db.fetch_one("SELECT COUNT(*) as count FROM search_rules"))["count"]
        seen_count = (await db.fetch_one("SELECT COUNT(*) as count FROM seen_listings"))["count"]
        enriched_count = (await db.fetch_one("SELECT COUNT(*) as count FROM enriched_listings"))["count"]
        rejections_count = (await db.fetch_one("SELECT COUNT(*) as count FROM rejection_logs"))["count"]
        
        # Get DB file size
        db_size_mb = 0.0
        from pathlib import Path
        db_path = Path("apartment_bot.db")
        if db_path.exists():
            db_size_mb = db_path.stat().st_size / (1024 * 1024)
            
        dashboard = f"""👑 *לוח בקרה למנהל* 👑

📊 *סטטיסטיקות כלליות:*
• סה\"כ משתמשים: {users_count} (פעילים: {active_users})
• סה\"כ כללי חיפוש: {rules_count}
• דירות שנסרקו (Seen): {seen_count}
• דירות מועשרות (Enriched): {enriched_count}
• דירות שנפסלו (Rejections): {rejections_count}
• גודל מסד הנתונים: {db_size_mb:.2f} MB

🤖 *פעולות ניהול:*
• לצפייה במשתמשים: /admin_users
• לצפייה בלוג שגיאות: /admin_logs
• שידור הודעה לכולם: /admin_broadcast [הודעה]
• הרצת סורק ידנית: /admin_scrape
• מחיקת/איפוס טבלאות: לחץ על הכפתורים למטה

⚠️ *שים לב: מחיקת טבלאות היא פעולה בלתי הפיכה!*"""
        
        # Keyboard for dropping tables
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
            ]
        ]
        
        await update.message.reply_text(
            dashboard,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    @ensure_user_exists
    @admin_required
    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all registered users."""
        db = await get_db()
        rule_repo = RuleRepository(db)
        from datetime import datetime
        
        # Get all users (active and inactive)
        rows = await db.fetch_all("SELECT * FROM users ORDER BY created_at DESC")
        
        if not rows:
            await update.message.reply_text("אין משתמשים רשומים במערכת.")
            return
            
        msg = f"👤 *משתמשים רשומים במערכת ({len(rows)}):*\n\n"
        
        for row in rows:
            telegram_id = row["telegram_id"]
            username = row["username"] or "אין"
            is_active = "פעיל ✅" if row["is_active"] else "כבוי ❌"
            is_admin = "👑 מנהל" if row.get("is_admin") else "משתמש"
            persona = row.get("persona") or "barakush"
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
                
            msg += f"• *{telegram_id}* | @{username} | {is_admin}\n"
            msg += f"  נציג: `{persona}` | סטטוס: {is_active} | כללים: {rules_count}\n"
            msg += f"  הצטרף ב: {date_str}\n\n"
            
            # Handle long messages in Telegram (max 4096 chars)
            if len(msg) > 3500:
                await update.message.reply_text(msg, parse_mode="Markdown")
                msg = ""
                
        if msg:
            await update.message.reply_text(msg, parse_mode="Markdown")

    @ensure_user_exists
    @admin_required
    async def admin_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show error logs from the last 24 hours."""
        import json
        from pathlib import Path
        from datetime import datetime, timedelta, timezone
        
        errors_path = Path("logs/errors.log")
        if not errors_path.exists():
            await update.message.reply_text("❌ לא נמצא קובץ לוג שגיאות.")
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
            await update.message.reply_text(f"❌ שגיאה בקריאת קובץ הלוג: {e}")
            return
            
        if not recent_errors:
            await update.message.reply_text("✅ אין שגיאות לוג ב-24 השעות האחרונות!")
            return
            
        # Format a summary of errors
        summary = f"📋 *סיכום שגיאות ב-24 השעות האחרונות:*\n"
        summary += f"סה\"כ שגיאות: {len(recent_errors)}\n\n"
        
        summary += "*סוגי שגיאות נפוצים:*\n"
        sorted_counts = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        for msg, count in sorted_counts:
            short_msg = msg[:60] + "..." if len(msg) > 60 else msg
            summary += f"• `{short_msg}`: {count} פעמים\n"
            
        summary += "\n*5 השגיאות האחרונות במלואן:* (מצורף גם קובץ מפורט)"
        
        await update.message.reply_text(summary, parse_mode="Markdown")
        
        # Format and send the 5 most recent detailed errors
        for i, entry in enumerate(reversed(recent_errors[-5:])):
            err_msg = f"🔍 *שגיאה {i+1}* ({entry.get('timestamp')}):\n"
            err_msg += f"רכיב: `{entry.get('logger')}` | פונקציה: `{entry.get('function')}:{entry.get('line')}`\n"
            err_msg += f"הודעה: `{entry.get('message')}`\n"
            if entry.get("exception"):
                tb = entry.get("exception")
                if len(tb) > 2000:
                    tb = tb[-2000:]
                err_msg += f"קוד שגיאה:\n```\n{tb}\n```"
            
            try:
                await update.message.reply_text(err_msg, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(f"שגיאה {i+1}:\n{json.dumps(entry, indent=2)}")
                
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
                
            from io import BytesIO
            bio = BytesIO(log_content.encode("utf-8"))
            bio.name = f"errors_last_24h_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=bio,
                caption="📄 קובץ שגיאות מלא ל-24 השעות האחרונות"
            )
        except Exception as e:
            log.error(f"Failed to send logs file: {e}")

    @ensure_user_exists
    @admin_required
    async def admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast a message to all registered users."""
        if not context.args:
            await update.message.reply_text("❌ נא לספק הודעה לשידור. שימוש: `/admin_broadcast [ההודעה שלך]`")
            return
            
        broadcast_text = " ".join(context.args)
        
        db = await get_db()
        user_repo = UserRepository(db)
        import asyncio
        
        # Get all active users
        users = await user_repo.get_all_active()
        
        if not users:
            await update.message.reply_text("אין משתמשים פעילים במערכת לשידור.")
            return
            
        await update.message.reply_text(f"📢 מתחיל שידור הודעה ל-{len(users)} משתמשים...")
        
        sent_count = 0
        failed_count = 0
        
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user.chat_id,
                    text=f"📢 *הודעת מערכת:*\n\n{broadcast_text}",
                    parse_mode="Markdown"
                )
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                log.error(f"Failed to send broadcast to user {user.telegram_id}: {e}")
                failed_count += 1
                
        await update.message.reply_text(f"✅ השידור הושלם!\n• נשלח בהצלחה: {sent_count}\n• נכשל: {failed_count}")

    @ensure_user_exists
    @admin_required
    async def admin_scrape(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger a scraping cycle."""
        app_instance = context.bot_data.get("app_instance")
        
        if not app_instance:
            await update.message.reply_text("❌ לא ניתן למצוא את מופע האפליקציה ב-bot_data.")
            return
            
        await update.message.reply_text("🔄 מתחיל מחזור סריקה והתאמה ידני (זה עשוי לקחת דקה-שתיים)...")
        
        try:
            await app_instance.run_processing_cycle()
            await update.message.reply_text("✅ מחזור סריקה והתאמה ידני הושלם בהצלחה!")
        except Exception as e:
            log.error(f"Manual scrape failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ הרצת הסריקה נכשלה: {e}")

    @ensure_user_exists
    @admin_required
    async def admin_fb_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger a Facebook login flow to authenticate session and capture 2FA code."""
        import asyncio
        
        chat_id = update.effective_chat.id
        
        # Check if there is already an active session running
        if context.bot_data.get("fb_login_waiting_for_2fa") is not None:
            await update.message.reply_text("❌ יש כבר תהליך התחברות פעיל שממתין לקוד 2FA!")
            return
            
        await update.message.reply_text("🔐 *מתחיל תהליך התחברות לפייסבוק...*\nהדפדפן מופעל כעת. אנא המתן...")
        
        # Launch background task for Facebook login
        asyncio.create_task(self._run_facebook_login_task(chat_id, context))

    async def _run_facebook_login_task(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Background task that runs the Playwright Facebook login and interacts with Telegram for 2FA."""
        import asyncio
        import os
        import json
        import random
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
        from config import settings
        
        email = settings.FACEBOOK_EMAIL
        password = settings.FACEBOOK_PASSWORD
        
        if not email or not password:
            await context.bot.send_message(chat_id=chat_id, text="❌ שגיאה: FACEBOOK_EMAIL ו-FACEBOOK_PASSWORD אינם מוגדרים ב-.env!")
            return
            
        browser = None
        playwright = None
        
        try:
            playwright = await async_playwright().start()
            
            # Launch browser in headed mode (will run in Xvfb on remote)
            log.info("Telegram-triggered Facebook login starting browser...")
            browser = await playwright.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--lang=he-IL',
                ]
            )
            
            browser_context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale='he-IL',
                timezone_id='Asia/Jerusalem',
            )
            
            stealth = Stealth(
                navigator_languages_override=('he-IL', 'he', 'en-US', 'en'),
                init_scripts_only=False,
            )
            await stealth.apply_stealth_async(browser_context)
            
            page = await browser_context.new_page()
            
            await context.bot.send_message(chat_id=chat_id, text="🌐 מנווט לדף ההתחברות של פייסבוק...")
            await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3)
            
            # Handle cookie consent
            try:
                consent = await page.query_selector('button[data-cookiebanner="accept_button"], button:has-text("Allow all cookies"), button:has-text("אישור הכל")')
                if consent and await consent.is_visible():
                    await consent.click()
                    await asyncio.sleep(1)
            except:
                pass
                
            email_input = await page.query_selector('input#email, input[name="email"]')
            if email_input:
                await email_input.fill(email)
                
            pass_input = await page.query_selector('input#pass, input[name="pass"], input[type="password"]')
            if pass_input:
                await pass_input.fill(password)
                
            await context.bot.send_message(chat_id=chat_id, text="🔑 מגיש פרטי התחברות...")
            await page.keyboard.press("Enter")
            await asyncio.sleep(6)
            
            current_url = page.url
            log.info(f"URL after login submit: {current_url}")
            
            # Check for 2FA
            two_factor_selectors = [
                'input#approvals_code',
                'input[name="approvals_code"]',
                'input[type="text"]',
            ]
            
            has_2fa = False
            two_fa_input = None
            for selector in two_factor_selectors:
                two_fa_input = await page.query_selector(selector)
                if two_fa_input and await two_fa_input.is_visible():
                    has_2fa = True
                    break
                    
            if has_2fa or "two_step_verification" in current_url or "checkpoint" in current_url:
                os.makedirs("logs", exist_ok=True)
                await page.screenshot(path="logs/2fa_prompt.png")
                
                # Send screenshot to admin chat
                with open("logs/2fa_prompt.png", "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_file,
                        caption="⚠️ נדרש אימות דו-שלבי (2FA)!\nאנא השב להודעה זו (או הקלד כאן בשיחה) את קוד האימות שקיבלת (למשל: 123456):"
                    )
                
                # Set up the Future for the 2FA code
                context.bot_data["fb_login_waiting_for_2fa"] = chat_id
                context.bot_data["fb_login_future"] = asyncio.Future()
                
                try:
                    # Wait for 2FA code from the admin (timeout 2 minutes)
                    code = await asyncio.wait_for(context.bot_data["fb_login_future"], timeout=120.0)
                except asyncio.TimeoutError:
                    context.bot_data["fb_login_waiting_for_2fa"] = None
                    await context.bot.send_message(chat_id=chat_id, text="❌ פג תוקף הזמן להזנת הקוד (2 דקות). תהליך ההתחברות בוטל.")
                    await browser.close()
                    return
                
                # Fill in the code
                if not two_fa_input:
                    for selector in two_factor_selectors:
                        two_fa_input = await page.query_selector(selector)
                        if two_fa_input:
                            break
                
                if two_fa_input:
                    await two_fa_input.fill(code)
                    await asyncio.sleep(1)
                    await context.bot.send_message(chat_id=chat_id, text="🚀 קוד 2FA נשלח לפייסבוק...")
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(6)
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ שגיאה: לא נמצאה תיבת הזנת הקוד בדף. בודק מחדש.")
                    await browser.close()
                    return
            
            # Handle "Trust browser" checkpoint
            try:
                trust_btn = await page.query_selector('button#checkpointSubmitButton, button[type="submit"]')
                if trust_btn and await trust_btn.is_visible():
                    log.info("Handling 'Trust Browser' checkpoint in Telegram task...")
                    await trust_btn.click()
                    await asyncio.sleep(5)
            except Exception as e:
                log.warning(f"Checkpoint click exception: {e}")
                
            current_url = page.url
            log.info(f"Final URL: {current_url}")
            
            # Save session
            os.makedirs("data", exist_ok=True)
            await browser_context.storage_state(path="data/fb_storage_state.json")
            cookies = await browser_context.cookies()
            with open("data/fb_cookies.json", "w") as f:
                json.dump(cookies, f)
                
            await context.bot.send_message(
                chat_id=chat_id,
                text="🎉 **ההתחברות לפייסבוק הושלמה בהצלחה!**\nהקוקיז ומצב הדפדפן נשמרו.\nהסורק יתחבר אוטומטית במחזור הבא!"
            )
            
        except Exception as e:
            log.error(f"Telegram-triggered Facebook login failed: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ שגיאה במהלך ההתחברות: {e}")
        finally:
            context.bot_data["fb_login_waiting_for_2fa"] = None
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
