# bot/handlers/admin_command_handler.py
"""Telegram admin command handlers (dashboard, broadcast, logs, scraping, interactive FB login)."""

import asyncio
import os
import json
import platform
import html
from pathlib import Path
from datetime import datetime, timedelta, timezone
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from config import settings
from database import get_db
from database.repositories import UserRepository, RuleRepository
from utils.logger import Loggers
from utils.text_utils import escape_markdown
from bot.handlers.decorators import ensure_user_exists, admin_required
from bot.handlers.command_handler import get_main_menu_keyboard

log = Loggers.bot()


class AdminCommandHandler:
    """Handles Telegram bot commands for administrators."""

    async def get_admin_dashboard_data(self) -> tuple[str, InlineKeyboardMarkup]:
        """Fetch stats and build the admin dashboard text and keyboard."""
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
        db_path = Path("apartment_bot.db")
        if db_path.exists():
            db_size_mb = db_path.stat().st_size / (1024 * 1024)
            
        dashboard = f"""👑 <b>לוח בקרה למנהל</b> 👑

📊 <b>סטטיסטיקות כלליות:</b>
• סה\"כ משתמשים: {users_count} (פעילים: {active_users})
• סה\"כ כללי חיפוש: {rules_count}
• דירות שנסרקו (Seen): {seen_count}
• דירות מועשרות (Enriched): {enriched_count}
• דירות שנפסלו (Rejections): {rejections_count}
• גודל מסד הנתונים: {db_size_mb:.2f} MB

🤖 <b>תפריט פעולות:</b>
בחר אחת מהפעולות הבאות מתוך התפריט האינטראקטיבי:"""
        
        keyboard = [
            [
                InlineKeyboardButton("👥 רשימת משתמשים", callback_data="admin_menu_users"),
                InlineKeyboardButton("🏠 דירות אחרונות", callback_data="admin_menu_recent_listings")
            ],
            [
                InlineKeyboardButton("📋 לוג שגיאות", callback_data="admin_menu_logs"),
                InlineKeyboardButton("📢 שידור הודעה", callback_data="admin_broadcast_prompt")
            ],
            [
                InlineKeyboardButton("🔐 פייסבוק וסורק", callback_data="admin_menu_fb"),
                InlineKeyboardButton("🧹 ניקוי טבלאות", callback_data="admin_menu_clear")
            ],
            [
                InlineKeyboardButton("🧪 בדיקת Gemini AI", callback_data="admin_menu_gemini"),
                InlineKeyboardButton("🖥️ סטטוס שרת", callback_data="admin_menu_server")
            ]
        ]
        
        return dashboard, InlineKeyboardMarkup(keyboard)

    @ensure_user_exists
    @admin_required
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show the admin dashboard."""
        dashboard, reply_markup = await self.get_admin_dashboard_data()
        await update.message.reply_text(
            dashboard,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

    @ensure_user_exists
    @admin_required
    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all registered users."""
        db = await get_db()
        rule_repo = RuleRepository(db)
        
        # Get all users (active and inactive)
        rows = await db.fetch_all("SELECT * FROM users ORDER BY created_at DESC")
        
        if not rows:
            await update.message.reply_text("אין משתמשים רשומים במערכת.")
            return
            
        msg = f"👤 *משתמשים רשומים במערכת ({len(rows)}):*\n\n"
        
        for row in rows:
            row_dict = dict(row)
            telegram_id = row_dict["telegram_id"]
            username = row_dict["username"] or "אין"
            is_active = "פעיל ✅" if row_dict["is_active"] else "כבוי ❌"
            is_admin = "👑 מנהל" if row_dict.get("is_admin") else "משתמש"
            persona = row_dict.get("persona") or "barakush"
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
            from telegram.constants import MessageLimit
            if len(msg) > 3500:
                await update.message.reply_text(msg, parse_mode="Markdown")
                msg = ""
                
        if msg:
            await update.message.reply_text(msg, parse_mode="Markdown")

    @ensure_user_exists
    @admin_required
    async def admin_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show error logs from the last 24 hours."""
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
                    text=f"📢 <b>הודעת מערכת:</b>\n\n{html.escape(broadcast_text)}",
                    parse_mode="HTML"
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
        chat_id = update.effective_chat.id
        async def send_reply(text, **kwargs):
            if update.message:
                return await update.message.reply_text(text, **kwargs)
            else:
                return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)

        app_instance = context.bot_data.get("app_instance")
        
        if not app_instance:
            await send_reply("❌ לא ניתן למצוא את מופע האפליקציה ב-bot_data.")
            return
            
        await send_reply("🔄 מתחיל מחזור סריקה והתאמה ידני (זה עשוי לקחת דקה-שתיים)...")
        
        try:
            await app_instance.run_processing_cycle()
            await send_reply("✅ מחזור סריקה והתאמה ידני הושלם בהצלחה!")
        except Exception as e:
            log.error(f"Manual scrape failed: {e}", exc_info=True)
            await send_reply(f"❌ הרצת הסריקה נכשלה: {e}")

    @ensure_user_exists
    @admin_required
    async def admin_fb_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start an interactive Facebook login session via Telegram.
        
        Opens a browser on the server, auto-fills credentials, then enters
        an interactive loop where the admin can guide the browser through
        CAPTCHAs, 2FA, and other challenges via screenshot + text commands.
        """
        chat_id = update.effective_chat.id
        async def send_reply(text, **kwargs):
            if update.message:
                return await update.message.reply_text(text, **kwargs)
            else:
                return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        
        # Check if there is already an active session running
        if context.bot_data.get("fb_interactive_login", {}).get("active"):
            await send_reply("❌ יש כבר תהליך התחברות אינטראקטיבי פעיל!")
            return
        if context.bot_data.get("fb_login_waiting_for_2fa") is not None:
            await send_reply("❌ יש כבר תהליך התחברות פעיל שממתין לקוד 2FA!")
            return
            
        await send_reply(
            "🔐 *מתחיל התחברות אינטראקטיבית לפייסבוק...*\n"
            "הדפדפן מופעל כעת. אמלא פרטים אוטומטית ואז תוכל/י לנווט דרך Telegram.",
            parse_mode='Markdown'
        )
        
        # Set up interactive login state
        context.bot_data["fb_interactive_login"] = {
            "chat_id": chat_id,
            "queue": asyncio.Queue(),
            "active": True,
        }
        
        # Launch background task
        asyncio.create_task(self._run_interactive_fb_login_task(chat_id, context))

    async def _run_interactive_fb_login_task(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Interactive Facebook login via Telegram screenshots and commands."""
        HELP_TEXT = (
            "📋 *פקודות:*\n"
            "• `click [טקסט]` — לחיצה על כפתור/קישור\n"
            "• `tap [x] [y]` — לחיצה בנקודה\n"
            "• `type [טקסט]` — הקלדה בשדה\n"
            "• `enter` — Enter\n"
            "• `tab` — Tab\n"
            "• `scroll` — גלילה למטה\n"
            "• `back` — חזרה\n"
            "• `ss` — צילום מסך מחדש\n"
            "• `done` ✅ — שמירה וסיום\n"
            "• `cancel` ❌ — ביטול\n"
            "• טקסט חופשי → יוקלד"
        )
        
        email = settings.FACEBOOK_EMAIL
        password = settings.FACEBOOK_PASSWORD
        browser = None
        playwright_instance = None
        login_state = context.bot_data.get("fb_interactive_login", {})
        command_queue = login_state.get("queue")
        session_saved = False
        
        if not command_queue:
            await context.bot.send_message(chat_id=chat_id, text="❌ שגיאה פנימית: תור פקודות לא נמצא.")
            return
        
        try:
            playwright_instance = await async_playwright().start()
            
            log.info("Interactive FB login: launching browser")
            
            # Determine browser channel
            is_arm = platform.machine().lower() in ['arm64', 'aarch64']
            is_linux = platform.system().lower() == 'linux'
            browser_channel = "msedge" if not (is_arm and is_linux) else None
            
            launch_args = {
                'headless': settings.HEADLESS_MODE,
                'args': [
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--lang=he-IL',
                    '--window-size=1280,720',
                ]
            }
            if browser_channel:
                launch_args['channel'] = browser_channel
                
            try:
                browser = await playwright_instance.chromium.launch(**launch_args)
            except Exception:
                # Fallback without channel
                launch_args.pop('channel', None)
                browser = await playwright_instance.chromium.launch(**launch_args)
            
            browser_context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 720},
                locale='he-IL',
                timezone_id='Asia/Jerusalem',
            )
            
            stealth = Stealth(
                navigator_languages_override=('he-IL', 'he', 'en-US', 'en'),
                init_scripts_only=False,
            )
            await stealth.apply_stealth_async(browser_context)
            
            page = await browser_context.new_page()
            
            # Navigate to Facebook login
            await context.bot.send_message(chat_id=chat_id, text="🌐 מנווט לדף ההתחברות...")
            await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3)
            
            # Handle cookie consent
            try:
                consent = await page.query_selector(
                    'button[data-cookiebanner="accept_button"], '
                    'button:has-text("Allow all cookies"), '
                    'button:has-text("אישור הכל")'
                )
                if consent and await consent.is_visible():
                    await consent.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            
            # Auto-fill credentials if available
            if email and password:
                try:
                    email_input = await page.query_selector('input#email, input[name="email"]')
                    if email_input:
                        await email_input.fill(email)
                    
                    pass_input = await page.query_selector('input#pass, input[name="pass"], input[type="password"]')
                    if pass_input:
                        await pass_input.fill(password)
                    
                    await context.bot.send_message(chat_id=chat_id, text="🔑 פרטי התחברות מולאו אוטומטית. שולח...")
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(6)
                except Exception as e:
                    log.warning(f"Auto-fill failed: {e}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ מילוי אוטומטי נכשל: {e}\nתוכל/י למלא ידנית עם `type`."
                    )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ פרטי התחברות לא מוגדרים ב-.env. מלא/י ידנית עם `type`."
                )
            
            # Send initial screenshot with full help text
            os.makedirs("logs", exist_ok=True)
            await self._send_interactive_screenshot(page, chat_id, context, HELP_TEXT)
            
            # ══════════════════════════════════════════════════════════
            # Interactive command loop
            # ══════════════════════════════════════════════════════════
            while login_state.get("active"):
                try:
                    # Wait for next command (5 min timeout per command)
                    cmd = await asyncio.wait_for(command_queue.get(), timeout=300)
                    cmd = cmd.strip()
                    
                    if not cmd:
                        continue
                    
                    cmd_lower = cmd.lower()
                    
                    # ── done: save session and exit ──
                    if cmd_lower == "done":
                        os.makedirs("data", exist_ok=True)
                        await browser_context.storage_state(path="data/fb_storage_state.json")
                        cookies = await browser_context.cookies()
                        with open("data/fb_cookies.json", "w") as f:
                            json.dump(cookies, f)
                        session_saved = True
                        
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "🎉 *ההתחברות הושלמה!*\n"
                                "✅ Session וcookies נשמרו בהצלחה.\n"
                                "הסורק יתחבר אוטומטית במחזור הבא!"
                            ),
                            parse_mode="Markdown"
                        )
                        break
                    
                    # ── cancel: abort ──
                    elif cmd_lower == "cancel":
                        await context.bot.send_message(chat_id=chat_id, text="❌ תהליך ההתחברות בוטל.")
                        break
                    
                    # ── ss/screenshot: retake screenshot ──
                    elif cmd_lower in ("ss", "screenshot"):
                        await self._send_interactive_screenshot(page, chat_id, context, HELP_TEXT)
                        continue
                    
                    # ── reCAPTCHA tile selection: e.g. "2 5 6 9" or "tile 2 5 6 9" ──
                    elif cmd_lower.startswith("tile ") or (__import__("re").match(r"^[\d\s,]+$", cmd) and any(c.isdigit() for c in cmd)):
                        import re
                        numbers = [int(n) for n in re.findall(r'\d+', cmd)]
                        # Only treat as tile selection if all numbers are valid indices (1 to 16)
                        if numbers and all(1 <= n <= 16 for n in numbers):
                            # Find tiles inside frames
                            tiles = []
                            for frame in page.frames:
                                try:
                                    elements = await frame.query_selector_all(
                                        '.rc-imageselect-tile, .rc-imageselect-candidate, td.rc-imageselect-tile, .rc-imageselect-tile-wrapper'
                                    )
                                    if elements:
                                        tiles = elements
                                        break
                                except Exception:
                                    continue
                                    
                            if tiles:
                                clicked_indices = []
                                for num in numbers:
                                    idx = num - 1
                                    if 0 <= idx < len(tiles):
                                        try:
                                            await tiles[idx].click()
                                            clicked_indices.append(num)
                                            await asyncio.sleep(0.3)
                                        except Exception as click_err:
                                            log.warning(f"Failed to click tile {num}: {click_err}")
                                            
                                if clicked_indices:
                                    await context.bot.send_message(
                                        chat_id=chat_id, 
                                        text=f"Selected tiles: {', '.join(map(str, clicked_indices))}"
                                    )
                                    await asyncio.sleep(1.5)
                                    await self._send_interactive_screenshot(page, chat_id, context)
                                    continue
                                else:
                                    await context.bot.send_message(chat_id=chat_id, text="❌ לא הצלחתי ללחוץ על האריחים שנבחרו.")
                                    continue
                            else:
                                await context.bot.send_message(
                                    chat_id=chat_id, 
                                    text="❌ לא מצאתי אריחי תמונה של reCAPTCHA במסך. נסה להשתמש ב-tap עם קואורדינטות."
                                )
                                continue
                    
                    # ── enter ──
                    elif cmd_lower == "enter":
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(2)
                        await context.bot.send_message(chat_id=chat_id, text="⏎ Enter")
                    
                    # ── tab ──
                    elif cmd_lower == "tab":
                        await page.keyboard.press("Tab")
                        await asyncio.sleep(0.5)
                        await context.bot.send_message(chat_id=chat_id, text="⇥ Tab")
                    
                    # ── scroll ──
                    elif cmd_lower == "scroll":
                        await page.mouse.wheel(0, 400)
                        await asyncio.sleep(1)
                        await context.bot.send_message(chat_id=chat_id, text="⬇️ גלילה למטה")
                    
                    # ── back ──
                    elif cmd_lower == "back":
                        await page.go_back()
                        await asyncio.sleep(2)
                        await context.bot.send_message(chat_id=chat_id, text="⬅️ חזרה")
                    
                    # ── click [text]: click element by visible text ──
                    elif cmd_lower.startswith("click "):
                        target_text = cmd[6:].strip()
                        clicked = await self._click_element_by_text(page, target_text)
                        if clicked:
                            await asyncio.sleep(2)
                            await context.bot.send_message(chat_id=chat_id, text=f'✅ לחצתי על "{target_text}"')
                        else:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=f'❌ לא מצאתי אלמנט עם הטקסט "{target_text}"'
                            )
                    
                    # ── tap [x] [y]: click at pixel coordinates ──
                    elif cmd_lower.startswith("tap "):
                        parts = cmd.split()
                        if len(parts) >= 3:
                            try:
                                x, y = int(parts[1]), int(parts[2])
                                await page.mouse.click(x, y)
                                await asyncio.sleep(1)
                                await context.bot.send_message(chat_id=chat_id, text=f"👆 Tap ({x}, {y})")
                            except ValueError:
                                await context.bot.send_message(chat_id=chat_id, text="❌ פורמט: `tap X Y` (מספרים)")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text="❌ פורמט: `tap X Y`")
                            continue
                    
                    # ── type [text]: type text into focused element ──
                    elif cmd_lower.startswith("type "):
                        text_to_type = cmd[5:]
                        await page.keyboard.type(text_to_type, delay=50)
                        await asyncio.sleep(0.5)
                        display = text_to_type[:20] + "..." if len(text_to_type) > 20 else text_to_type
                        await context.bot.send_message(chat_id=chat_id, text=f'⌨️ הוקלד: "{display}"')
                    
                    # ── goto [url]: navigate to URL ──
                    elif cmd_lower.startswith("goto "):
                        url = cmd[5:].strip()
                        if not url.startswith("http"):
                            url = "https://" + url
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(2)
                        await context.bot.send_message(chat_id=chat_id, text=f"🌐 ניווט ל: {url[:60]}")
                    
                    # ── select [field]: focus a specific input field ──
                    elif cmd_lower.startswith("select "):
                        target = cmd[7:].strip()
                        input_elem = await page.query_selector(
                            f'input[name="{target}"], input[id="{target}"], '
                            f'input[type="{target}"], textarea[name="{target}"]'
                        )
                        if input_elem:
                            await input_elem.click()
                            await asyncio.sleep(0.3)
                            await context.bot.send_message(chat_id=chat_id, text=f"🎯 Focused: {target}")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text=f"❌ לא מצאתי שדה: {target}")
                            continue
                    
                    # ── clear: clear focused input ──
                    elif cmd_lower == "clear":
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Backspace")
                        await asyncio.sleep(0.3)
                        await context.bot.send_message(chat_id=chat_id, text="🧹 שדה נוקה")
                    
                    # ── Any other text: type it into the focused element ──
                    else:
                        await page.keyboard.type(cmd, delay=50)
                        await asyncio.sleep(0.5)
                        display = cmd[:20] + "..." if len(cmd) > 20 else cmd
                        await context.bot.send_message(chat_id=chat_id, text=f'⌨️ הוקלד: "{display}"')
                    
                    # Auto-send screenshot after each action
                    await self._send_interactive_screenshot(page, chat_id, context)
                    
                except asyncio.TimeoutError:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⏰ פג תוקף (5 דקות ללא פעילות). תהליך ההתחברות בוטל."
                    )
                    break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.error(f"Interactive login command error: {e}", exc_info=True)
                    await context.bot.send_message(chat_id=chat_id, text=f"⚠️ שגיאה בביצוע הפקודה: {e}")
                    try:
                        await self._send_interactive_screenshot(page, chat_id, context)
                    except Exception:
                        pass
        
        except Exception as e:
            log.error(f"Interactive Facebook login failed: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ שגיאה במהלך ההתחברות: {e}")
        finally:
            # Clean up state
            context.bot_data["fb_interactive_login"] = {"active": False}
            context.bot_data["fb_login_waiting_for_2fa"] = None
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_instance:
                try:
                    await playwright_instance.stop()
                except Exception:
                    pass
            log.info(f"Interactive FB login ended. Session saved: {session_saved}")

    async def _send_interactive_screenshot(self, page, chat_id, context, help_text=None):
        """Take a page screenshot and send it to the admin via Telegram."""
        screenshot_path = "logs/fb_interactive.png"
        try:
            await page.screenshot(path=screenshot_path)
            current_url = page.url
            
            # Build caption
            url_display = current_url[:80] + "..." if len(current_url) > 80 else current_url
            caption = f"📸 `{url_display}`"
            if help_text:
                caption += f"\n\n{help_text}"
            
            # Telegram caption limit is 1024 chars
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            
            with open(screenshot_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=caption,
                    parse_mode="Markdown"
                )
        except Exception as e:
            log.error(f"Failed to send interactive screenshot: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ שגיאה בצילום מסך: {e}")

    async def _click_element_by_text(self, page, target_text: str) -> bool:
        """Find and click a visible element containing the target text."""
        # Special case: reCAPTCHA auto-detection
        is_recaptcha_query = any(k in target_text.lower() for k in ["robot", "רובוט", "captcha", "recaptcha"])
        if is_recaptcha_query:
            recaptcha_selectors = [
                'span#recaptcha-anchor',
                '#recaptcha-anchor',
                '.recaptcha-checkbox-border',
                'div.recaptcha-checkbox',
                '[role="checkbox"]',
            ]
            for frame in page.frames:
                for selector in recaptcha_selectors:
                    try:
                        elem = await frame.query_selector(selector)
                        if elem and await elem.is_visible():
                            log.info(f"Auto-detected reCAPTCHA element with selector '{selector}' in frame '{frame.name}'")
                            await elem.click()
                            return True
                    except Exception:
                        continue

        # Special case: reCAPTCHA verify button auto-detection
        is_verify_query = any(k in target_text.lower() for k in ["verify", "confirm", "אימות", "הבא", "next"])
        if is_verify_query:
            verify_selectors = [
                '#recaptcha-verify-button',
                'button#recaptcha-verify-button',
                '.rc-button-default',
                'button:has-text("Verify")',
                'button:has-text("אימות")',
                'button:has-text("הבא")',
                'button:has-text("Next")',
            ]
            for frame in page.frames:
                for selector in verify_selectors:
                    try:
                        elem = await frame.query_selector(selector)
                        if elem and await elem.is_visible():
                            log.info(f"Auto-detected reCAPTCHA verify button with selector '{selector}' in frame '{frame.name}'")
                            await elem.click()
                            return True
                    except Exception:
                        continue

        # Try main page and all subframes
        for frame in page.frames:
            try:
                # Strategy 1: Playwright :has-text() selectors (most reliable)
                selectors = [
                    f'button:has-text("{target_text}")',
                    f'[role="button"]:has-text("{target_text}")',
                    f'a:has-text("{target_text}")',
                    f'input[type="submit"][value="{target_text}"]',
                    f'label:has-text("{target_text}")',
                    f'div:has-text("{target_text}")',
                    f'span:has-text("{target_text}")',
                ]
                
                for selector in selectors:
                    try:
                        elem = await frame.query_selector(selector)
                        if elem and await elem.is_visible():
                            await elem.click()
                            return True
                    except Exception:
                        continue
                
                # Strategy 2: Broader search through all interactive elements
                try:
                    interactive = await frame.query_selector_all(
                        'button, a, [role="button"], input[type="submit"], '
                        'div[tabindex], span[tabindex], div[onclick], '
                        'input[type="checkbox"], label'
                    )
                    for elem in interactive:
                        try:
                            text = await elem.inner_text()
                            if not text:
                                # Fallback to check attribute like aria-label or title
                                text = (await elem.get_attribute("aria-label") or "") + " " + (await elem.get_attribute("title") or "")
                            if target_text.lower() in text.lower().strip():
                                if await elem.is_visible():
                                    await elem.click()
                                    return True
                        except Exception:
                            continue
                except Exception:
                    pass
                
                # Strategy 3: Try with frame.get_by_text().click() for complex text matching
                try:
                    locator = frame.get_by_text(target_text, exact=False).first
                    if await locator.is_visible():
                        await locator.click()
                        return True
                except Exception:
                    pass
            except Exception as frame_err:
                log.warning(f"Error searching frame for text '{target_text}': {frame_err}")
                continue
        
        return False
