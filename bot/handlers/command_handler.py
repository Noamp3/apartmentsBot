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
        persona_name = user_obj.persona if hasattr(user_obj, 'persona') else 'barakush'
        
        # Generate dynamic welcome sass
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
        
        # Get user persona
        db_manager = await get_db()
        user_repo = UserRepository(db_manager)
        user_obj = await user_repo.get_by_telegram_id(user_id)
        persona_name = user_obj.persona if user_obj else 'barakush'
        
        # Get dynamic sass
        ai_engine = context.bot_data.get("ai_engine")
        sass_extra = ""
        if ai_engine:
             try:
                sass = await ai_engine.get_random_sass(persona=persona_name)
                sass_extra = f"\n\n_{ListingFormatter._escape_markdown(sass)}_"
             except Exception:
                pass

        await self._safe_reply_text(
            update,
            f"🗑️ כל כללי החיפוש שלך נמחקו\\.\n\nשלח הודעה חדשה כדי להתחיל מחדש\\!{sass_extra}",
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_keyboard()
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
