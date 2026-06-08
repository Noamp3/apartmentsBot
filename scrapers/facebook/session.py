# scrapers/facebook/session.py
"""Handles Playwright browser contexts, login state, and cookies for Facebook scraping."""

import asyncio
import os
import json
import random
import platform
from typing import Optional, List, Dict
from config import settings
from utils.logger import Loggers

log = Loggers.scraper()

class FacebookSessionManager:
    """Manages browser creation, storage states, cookie login, and checkpoints."""
    
    BASE_URL = "https://www.facebook.com"
    LOGIN_URL = "https://www.facebook.com/login"
    
    def __init__(
        self,
        cookies_file: str,
        storage_state_file: str,
        anti_detection,
        bot=None
    ):
        self.cookies_file = cookies_file
        self.storage_state_file = storage_state_file
        self.anti_detection = anti_detection
        self.bot = bot
        
        self.playwright = None
        self.browser = None
        self.context = None
        self.stealth = None
        self.is_logged_in = False
        self._last_login_notify = 0

    def get_desktop_user_agent(self) -> str:
        """Get a stable desktop user agent to maintain session cookie validity."""
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        
    async def init_browser(self):
        """Initialize Playwright browser with anti-detection settings."""
        try:
            from playwright.async_api import async_playwright
            from playwright_stealth import Stealth
            
            self.stealth = Stealth(
                navigator_languages_override=('he-IL', 'he', 'en-US', 'en'),
                init_scripts_only=False,
            )
            
            self.playwright = await async_playwright().start()
            
            viewports = [
                {'width': 1920, 'height': 1080},
                {'width': 1600, 'height': 900},
                {'width': 1536, 'height': 864},
                {'width': 1440, 'height': 900},
            ]
            viewport = random.choice(viewports)
            log.info(f"Using randomized viewport: {viewport['width']}x{viewport['height']}")
            
            is_arm = platform.machine().lower() in ['arm64', 'aarch64']
            is_linux = platform.system().lower() == 'linux'
            browser_channel = "msedge" if not (is_arm and is_linux) else None
            
            if browser_channel:
                log.info(f"Launching browser with channel: {browser_channel}")
            else:
                log.info("Launching standard Chromium browser (no channel specified)")

            self.browser = await self.playwright.chromium.launch(
                headless=settings.HEADLESS_MODE,
                channel=browser_channel,
                slow_mo=random.randint(30, 70),
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--disable-infobars',
                    f'--window-size={viewport["width"]},{viewport["height"]}',
                    '--disable-features=Translate',
                    '--lang=he-IL',
                    '--disable-extensions',
                    '--disable-component-extensions-with-background-pages',
                    '--disable-default-apps',
                    '--mute-audio',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-hang-monitor',
                    '--metrics-recording-only',
                    '--disable-sync',
                    '--disable-domain-reliability',
                ]
            )
            
            storage_state = None
            if os.path.exists(self.storage_state_file):
                try:
                    storage_state = self.storage_state_file
                    log.info("Loading persisted browser state")
                except Exception as e:
                    log.warning(f"Could not load storage state: {e}")
            
            self.context = await self.browser.new_context(
                user_agent=self.get_desktop_user_agent(),
                viewport=viewport,
                locale='he-IL',
                timezone_id='Asia/Jerusalem',
                geolocation={'longitude': 34.7818, 'latitude': 32.0853},
                permissions=['geolocation'],
                storage_state=storage_state,
                screen={'width': viewport['width'], 'height': viewport['height']},
                device_scale_factor=1.0,
                has_touch=False,
                is_mobile=False,
                color_scheme='light',
            )
            
            await self.stealth.apply_stealth_async(self.context)
            log.info("Applied playwright-stealth to browser context")
            
            await self.context.add_init_script(self.anti_detection.add_stealth_scripts())
            
            # Inject additional fingerprint protection
            await self.context.add_init_script("""
                const originalGetContext = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type, attributes) {
                    const context = originalGetContext.apply(this, arguments);
                    if (type === '2d' && context) {
                        const originalFillText = context.fillText;
                        context.fillText = function() {
                            arguments[1] += Math.random() * 0.001;
                            return originalFillText.apply(this, arguments);
                        };
                    }
                    return context;
                };
                
                Object.defineProperty(navigator, 'mediaDevices', {
                    get: () => undefined
                });
                
                const origAudioContext = window.AudioContext || window.webkitAudioContext;
                if (origAudioContext) {
                    window.AudioContext = function() {
                        const ctx = new origAudioContext();
                        const orig = ctx.createOscillator;
                        ctx.createOscillator = function() {
                            const osc = orig.apply(ctx, arguments);
                            osc.frequency.value += Math.random() * 0.0001;
                            return osc;
                        };
                        return ctx;
                    };
                }
            """)
            
            if not storage_state and os.path.exists(self.cookies_file):
                try:
                    with open(self.cookies_file, 'r') as f:
                        cookies = json.load(f)
                    await self.context.add_cookies(cookies)
                    log.info("Loaded Facebook cookies from file")
                except Exception as e:
                    log.warning(f"Could not load cookies: {e}")
            
        except ImportError:
            log.error("Playwright or playwright-stealth not installed.")
            raise

    async def login_to_facebook(self, page) -> bool:
        """Login to Facebook with credentials from config."""
        if not settings.FACEBOOK_EMAIL or not settings.FACEBOOK_PASSWORD:
            log.warning("Facebook credentials not configured. Set FACEBOOK_EMAIL and FACEBOOK_PASSWORD in .env")
            return False
        
        try:
            log.info("Logging into Facebook...")
            
            admin_chat_id = None
            if self.bot:
                try:
                    from database import get_db
                    db = await get_db()
                    admin_row = await db.fetch_one("SELECT chat_id FROM users WHERE is_admin = 1")
                    if admin_row:
                        admin_chat_id = admin_row["chat_id"]
                        await self.bot.send_message(
                            chat_id=admin_chat_id, 
                            text="🔐 *זיהיתי שפייסבוק דורש התחברות!*\nמתחיל כעת התחברות אוטומטית מהשרת (Playwright)..."
                        )
                except Exception as alert_err:
                    log.error(f"Failed to alert admin about login start: {alert_err}")
            
            await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
            await self.anti_detection.human_like_delay(2, 3)
            
            await self.handle_cookie_consent(page)
            
            email_input = await page.query_selector('input#email, input[name="email"]')
            if email_input:
                log.info("Found email input")
                await self.anti_detection.human_like_typing(email_input, settings.FACEBOOK_EMAIL)
                await self.anti_detection.human_like_delay(1, 2)
            
            password_input = await page.query_selector('input#pass, input[name="pass"], input[type="password"]')
            if password_input:
                log.info("Found password input")
                await self.anti_detection.human_like_typing(password_input, settings.FACEBOOK_PASSWORD)
                await self.anti_detection.human_like_delay(1, 2)
            
            login_btn = await page.query_selector('button[name="login"], button[type="submit"], button[data-testid="royal_login_button"]')
            if login_btn:
                log.info("Clicking login button")
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")
            
            await page.wait_for_timeout(5000)
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except:
                pass
            
            two_factor_selectors = [
                'input#approvals_code',
                'input[name="approvals_code"]',
                'input[type="text"]',
                'input[name="code"]',
            ]
            
            import time
            log.info("Polling for up to 30 seconds for checkpoint start button or 2FA approvals input...")
            start_time = time.time()
            two_fa_input = None
            click_count = 0
            
            start_selectors = [
                '#checkpointSubmitButton',
                'button#checkpointSubmitButton',
                'button[type="submit"]',
                '[role="button"]:has-text("התחל")',
                '[role="button"]:has-text("המשך")',
                '[role="button"]:has-text("שליחת קוד")',
                '[role="button"]:has-text("שלח קוד")',
                '[role="button"]:has-text("הבא")',
                '[role="button"]:has-text("אישור")',
                '[role="button"]:has-text("Continue")',
                '[role="button"]:has-text("Get Started")',
                '[role="button"]:has-text("Send Code")',
                '[role="button"]:has-text("Next")',
                'button:has-text("התחל")',
                'button:has-text("המשך")',
                'button:has-text("שליחת קוד")',
                'button:has-text("שלח קוד")',
                'button:has-text("הבא")',
                'button:has-text("אישור")',
                'button:has-text("Continue")',
                'button:has-text("Get Started")',
                'button:has-text("Send Code")',
                'button:has-text("Next")',
                'a:has-text("התחל")',
                'a:has-text("המשך")',
                'a:has-text("הבא")',
            ]
            
            while time.time() - start_time < 30 and click_count < 5:
                for selector in two_factor_selectors:
                    try:
                        elem = await page.query_selector(selector)
                        if elem and await elem.is_visible():
                            two_fa_input = elem
                            break
                    except Exception:
                        pass
                
                if two_fa_input:
                    log.info("Approvals code input is now visible!")
                    break
                
                button_clicked = False
                for frame in page.frames:
                    try:
                        elements = await frame.query_selector_all('button, [role="button"], a, input[type="submit"]')
                        for elem in elements:
                            try:
                                if await elem.is_visible():
                                    text_content = await elem.inner_text()
                                    text_content = text_content.strip()
                                    if any(t in text_content for t in ["התחל", "המשך", "שליחת קוד", "שלח קוד", "הבא", "אישור", "Start", "Continue", "Get Started", "Send Code", "Next", "Submit"]):
                                        log.info(f"Found and clicking button inside iframe: '{text_content}'")
                                        await elem.click()
                                        button_clicked = True
                                        click_count += 1
                                        await page.wait_for_timeout(5000)
                                        break
                            except Exception:
                                pass
                        if button_clicked:
                            break
                    except Exception:
                        pass
                        
                if button_clicked:
                    continue
                
                for selector in start_selectors:
                    try:
                        btn = await page.query_selector(selector)
                        if btn and await btn.is_visible():
                            btn_text = await btn.inner_text()
                            log.info(f"Found and clicking button on main page: '{btn_text.strip()}' (selector: {selector})")
                            await btn.click()
                            button_clicked = True
                            click_count += 1
                            await page.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass
                        
                if button_clicked:
                    continue
                
                await page.wait_for_timeout(1500)
            
            two_fa_input = None
            for selector in two_factor_selectors:
                two_fa_input = await page.query_selector(selector)
                if two_fa_input and await two_fa_input.is_visible():
                    break
                    
            has_2fa = (two_fa_input is not None)
            current_url = page.url
            if has_2fa or "two_step_verification" in current_url or "checkpoint" in current_url:
                log.warning("2FA Verification prompt detected during background login!")
                
                if admin_chat_id and self.bot:
                    try:
                        os.makedirs("logs", exist_ok=True)
                        await page.screenshot(path="logs/2fa_prompt.png")
                        
                        with open("logs/2fa_prompt.png", "rb") as f:
                            await self.bot.application.bot.send_photo(
                                chat_id=admin_chat_id,
                                photo=f,
                                caption="⚠️ **נדרש אימות דו-שלבי (2FA) לפייסבוק!**\nהזן את קוד האימות שקיבלת כתגובה להודעה זו (הקלד רק את הקוד, למשל: 123456):"
                            )
                            
                        bot_data = self.bot.application.bot_data
                        bot_data["fb_login_waiting_for_2fa"] = admin_chat_id
                        bot_data["fb_login_future"] = asyncio.Future()
                        
                        try:
                            code = await asyncio.wait_for(bot_data["fb_login_future"], timeout=120.0)
                            
                            if not two_fa_input:
                                for selector in two_factor_selectors:
                                    two_fa_input = await page.query_selector(selector)
                                    if two_fa_input:
                                        break
                                        
                            if two_fa_input:
                                await two_fa_input.fill(code)
                                await asyncio.sleep(1)
                                await self.bot.send_message(chat_id=admin_chat_id, text="🚀 קוד 2FA נשלח לפייסבוק...")
                                await page.keyboard.press("Enter")
                                await asyncio.sleep(6)
                            else:
                                await self.bot.send_message(chat_id=admin_chat_id, text="❌ שגיאה: לא נמצאה תיבת קלט לקוד 2FA.")
                        except asyncio.TimeoutError:
                            bot_data["fb_login_waiting_for_2fa"] = None
                            await self.bot.send_message(chat_id=admin_chat_id, text="❌ פג תוקף הזמן להזנת הקוד (2 דקות). סריקת פייסבוק בבוט מבוטלת.")
                            return False
                    except Exception as telegram_err:
                        log.error(f"Failed to handle interactive 2FA prompt: {telegram_err}")

            await self.handle_checkpoints(page)
            
            current_url = page.url
            log.info(f"URL after login: {current_url}")
            
            if 'login' not in current_url or 'facebook.com/?' in current_url or '/home' in current_url:
                log.info("Facebook login successful")
                self.is_logged_in = True
                
                await self.save_session(page)
                
                if admin_chat_id and self.bot:
                    await self.bot.send_message(chat_id=admin_chat_id, text="🎉 **ההתחברות לפייסבוק בוצעה בהצלחה!**\nהקוקיז ומצב הדפדפן נשמרו. ממשיך בסריקה...")
                
                return True
            else:
                log.warning("Facebook login may have failed")
                await self.save_debug_info(page, "login_failed")
                return False
                
        except Exception as e:
            log.error(f"Facebook login failed: {e}")
            return False

    async def handle_cookie_consent(self, page):
        """Handle cookie consent dialogs."""
        consent_selectors = [
            'button[data-cookiebanner="accept_button"]',
            'button[title="Allow all cookies"]',
            'button:has-text("Allow all cookies")',
            'button:has-text("Accept All")',
            'button:has-text("אישור הכל")',
        ]
        
        for selector in consent_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    log.info("Handling cookie consent dialog")
                    await btn.click()
                    await self.anti_detection.human_like_delay(1, 2)
                    break
            except:
                continue

    async def handle_checkpoints(self, page):
        """Handle various Facebook checkpoint screens."""
        checkpoint_handlers = [
            ('button:has-text("Not Now")', "Save login - Not Now"),
            ('button:has-text("לא עכשיו")', "Save login - Hebrew"),
            ('button[aria-label="Close"]', "Close button"),
            ('div[aria-label="Close"]', "Close div"),
            ('button:has-text("Continue")', "Continue"),
            ('button:has-text("המשך")', "Continue Hebrew"),
            ('button:has-text("OK")', "OK"),
        ]
        
        for selector, description in checkpoint_handlers:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    log.info(f"Handling checkpoint: {description}")
                    await btn.click()
                    await self.anti_detection.human_like_delay(1, 2)
            except:
                continue

    async def save_session(self, page):
        """Save session state for future runs."""
        try:
            await self.context.storage_state(path=self.storage_state_file)
            log.info(f"Saved browser state to {self.storage_state_file}")
        except Exception as e:
            log.warning(f"Could not save storage state: {e}")
        
        try:
            cookies = await self.context.cookies()
            with open(self.cookies_file, 'w') as f:
                json.dump(cookies, f)
            log.info(f"Saved cookies to {self.cookies_file}")
        except Exception as e:
            log.warning(f"Could not save cookies: {e}")

    async def save_debug_info(self, page, prefix: str):
        """Save debug screenshot and HTML."""
        os.makedirs("logs", exist_ok=True)
        try:
            await page.screenshot(path=f"logs/debug_{prefix}.png")
            with open(f"logs/debug_{prefix}.html", "w", encoding="utf-8") as f:
                f.write(await page.content())
            log.info(f"Saved debug info with prefix: {prefix}")
        except Exception as e:
            log.warning(f"Could not save debug info: {e}")

    async def notify_login_required(self):
        """Notify admin via Telegram that interactive login is needed."""
        import time
        now = time.time()
        if now - self._last_login_notify < 3600:
            return
        self._last_login_notify = now
        
        if not self.bot:
            return
        
        try:
            from database import get_db
            db = await get_db()
            admin_row = await db.fetch_one("SELECT chat_id FROM users WHERE is_admin = 1")
            if admin_row:
                await self.bot.application.bot.send_message(
                    chat_id=admin_row["chat_id"],
                    text=(
                        "🔐 *נדרשת התחברות ידנית לפייסבוק!*\n\n"
                        "ההתחברות האוטומטית נכשלה (ייתכן CAPTCHA או session שפג תוקף).\n"
                        "השתמש/י בפקודה /admin_fb_login להתחברות אינטראקטיבית מ-Telegram."
                    ),
                    parse_mode="Markdown"
                )
                log.info("Notified admin about Facebook login requirement")
        except Exception as e:
            log.error(f"Failed to notify admin about login requirement: {e}")

    async def close_browser(self):
        """Close browser resources."""
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
