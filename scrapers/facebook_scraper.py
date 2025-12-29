# scrapers/facebook_scraper.py
"""Facebook groups scraper for apartment listings.

Uses playwright-stealth for anti-detection and desktop Facebook for reliable
permalink extraction.
"""

import asyncio
import hashlib
import os
import json
from datetime import datetime
from typing import List, Optional

from scrapers.base_scraper import BaseScraper
from scrapers.anti_detection import AntiDetectionModule
from models.listing import Listing
from utils.logger import Loggers
from utils.hebrew_utils import extract_price, extract_bedrooms, extract_contact_info
from utils.israeli_locations import get_location_db
import random

from bs4 import BeautifulSoup

log = Loggers.scraper()


class FacebookScraper(BaseScraper):
    """Scrapes apartment listings from Facebook groups.
    
    Uses desktop Facebook for more reliable permalink extraction.
    Implements playwright-stealth for advanced anti-detection.
    
    IMPORTANT: Uses persistent cookies to avoid login on every run.
    First run requires login, subsequent runs reuse session.
    """
    
    # Use desktop Facebook for better permalink extraction
    BASE_URL = "https://www.facebook.com"
    LOGIN_URL = "https://www.facebook.com/login"
    
    COOKIES_FILE = "data/fb_cookies.json"
    STORAGE_STATE_FILE = "data/fb_storage_state.json"
    
    # Desktop user agents (2025)
    DESKTOP_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]
    
    def __init__(
        self, 
        group_urls: List[str],
        anti_detection: AntiDetectionModule = None,
        cookies_file: str = None,
        storage_state_file: str = None
    ):
        self.group_urls = group_urls
        self.anti_detection = anti_detection or AntiDetectionModule()
        self.cookies_file = cookies_file or self.COOKIES_FILE
        self.storage_state_file = storage_state_file or self.STORAGE_STATE_FILE
        self._browser = None
        self._context = None
        self._stealth = None
        self._is_logged_in = False
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.cookies_file), exist_ok=True)
    
    @property
    def source_name(self) -> str:
        return "facebook"
    
    async def scrape(self) -> List[Listing]:
        """Scrape all configured Facebook groups."""
        if not self.group_urls:
            log.warning("No Facebook group URLs configured")
            return []
        
        listings = []
        
        try:
            await self._init_browser()
            
            for group_url in self.group_urls:
                try:
                    log.info(f"Scraping Facebook group", url=group_url)
                    group_listings = await self._scrape_group(group_url)
                    listings.extend(group_listings)
                    
                    # Delay between groups
                    await self.anti_detection.human_like_delay(5, 10)
                    
                except Exception as e:
                    log.error(f"Failed to scrape group", url=group_url, error=str(e))
                    import traceback
                    traceback.print_exc()
                    continue
        
        finally:
            await self._close_browser()
        
        log.info(f"Facebook scrape complete", total_listings=len(listings))
        return listings
    
    async def _init_browser(self):
        """Initialize Playwright browser with comprehensive anti-detection settings."""
        try:
            from playwright.async_api import async_playwright
            from playwright_stealth import Stealth
            
            # Initialize stealth with custom settings
            self._stealth = Stealth(
                navigator_languages_override=('he-IL', 'he', 'en-US', 'en'),
                init_scripts_only=False,  # Apply all evasions
            )
            
            self._playwright = await async_playwright().start()
            
            # === RANDOMIZED VIEWPORT SIZES (looks more human) ===
            viewports = [
                {'width': 1920, 'height': 1080},
                {'width': 1366, 'height': 768},
                {'width': 1536, 'height': 864},
                {'width': 1440, 'height': 900},
                {'width': 1280, 'height': 800},
                {'width': 1600, 'height': 900},
            ]
            viewport = random.choice(viewports)
            log.info(f"Using randomized viewport: {viewport['width']}x{viewport['height']}")
            
            # Launch browser - non-headless mode is less detectable
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                channel="msedge",  # Edge is less suspicious than Chrome
                slow_mo=random.randint(30, 70),  # Randomize slow_mo too
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
                    # Additional anti-detection args
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
            
            # Try to load existing storage state
            storage_state = None
            if os.path.exists(self.storage_state_file):
                try:
                    storage_state = self.storage_state_file
                    log.info("Loading persisted browser state")
                except Exception as e:
                    log.warning(f"Could not load storage state: {e}")
            
            # === ENHANCED CONTEXT WITH ANTI-FINGERPRINTING ===
            self._context = await self._browser.new_context(
                user_agent=self._get_desktop_user_agent(),
                viewport=viewport,
                locale='he-IL',
                timezone_id='Asia/Jerusalem',  # Israeli timezone
                geolocation={'longitude': 34.7818, 'latitude': 32.0853},  # Tel Aviv
                permissions=['geolocation'],
                storage_state=storage_state,
                # Realistic screen parameters
                screen={'width': viewport['width'], 'height': viewport['height']},
                device_scale_factor=random.choice([1, 1.25, 1.5]),  # Random DPI
                has_touch=False,
                is_mobile=False,
                color_scheme='light',
            )
            
            # Apply playwright-stealth to the context
            await self._stealth.apply_stealth_async(self._context)
            log.info("Applied playwright-stealth to browser context")
            
            # === ADDITIONAL ANTI-DETECTION SCRIPTS ===
            await self._context.add_init_script(self.anti_detection.add_stealth_scripts())
            
            # Inject additional fingerprint protection
            await self._context.add_init_script("""
                // Randomize canvas fingerprint slightly
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
                
                // Disable WebRTC leak
                Object.defineProperty(navigator, 'mediaDevices', {
                    get: () => undefined
                });
                
                // Randomize audio fingerprint
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
            
            # Load cookies as fallback
            if not storage_state and os.path.exists(self.cookies_file):
                try:
                    with open(self.cookies_file, 'r') as f:
                        cookies = json.load(f)
                    await self._context.add_cookies(cookies)
                    log.info("Loaded Facebook cookies from file")
                except Exception as e:
                    log.warning(f"Could not load cookies: {e}")
            
        except ImportError as e:
            log.error("Playwright or playwright-stealth not installed. Run: pip install playwright playwright-stealth && playwright install chromium")
            raise
    
    def _get_desktop_user_agent(self) -> str:
        """Get a random desktop user agent."""
        import random
        return random.choice(self.DESKTOP_USER_AGENTS)
    
    def _convert_to_desktop_url(self, url: str) -> str:
        """Convert mobile Facebook URL to desktop version."""
        if "m.facebook.com" in url:
            return url.replace("m.facebook.com", "www.facebook.com")
        if "www.facebook.com" not in url and "facebook.com" in url:
            return url.replace("facebook.com", "www.facebook.com")
        return url
    
    async def _login_to_facebook(self, page):
        """Login to Facebook with credentials from config."""
        from config import settings
        
        if not settings.FACEBOOK_EMAIL or not settings.FACEBOOK_PASSWORD:
            log.warning("Facebook credentials not configured. Set FACEBOOK_EMAIL and FACEBOOK_PASSWORD in .env")
            return False
        
        try:
            log.info("Logging into Facebook...")
            
            await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
            await self.anti_detection.human_like_delay(2, 3)
            
            # Check for and handle any cookie consent dialogs
            await self._handle_cookie_consent(page)
            
            # Fill email
            email_input = await page.query_selector('input#email, input[name="email"]')
            if email_input:
                log.info("Found email input")
                await self.anti_detection.human_like_typing(email_input, settings.FACEBOOK_EMAIL)
                await self.anti_detection.human_like_delay(1, 2)
            else:
                log.warning("Could not find email input")
            
            # Fill password
            password_input = await page.query_selector('input#pass, input[name="pass"], input[type="password"]')
            if password_input:
                log.info("Found password input")
                await self.anti_detection.human_like_typing(password_input, settings.FACEBOOK_PASSWORD)
                await self.anti_detection.human_like_delay(1, 2)
            else:
                log.warning("Could not find password input")
            
            # Click login button
            login_btn = await page.query_selector('button[name="login"], button[type="submit"], button[data-testid="royal_login_button"]')
            if login_btn:
                log.info("Clicking login button")
                await login_btn.click()
            else:
                # Try pressing Enter as fallback
                await page.keyboard.press("Enter")
            
            # Wait for navigation
            await page.wait_for_timeout(5000)
            
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except:
                pass
            
            # Handle post-login checkpoints
            await self._handle_checkpoints(page)
            
            # Check login success
            current_url = page.url
            log.info(f"URL after login: {current_url}")
            
            if 'login' not in current_url or 'facebook.com/?' in current_url or '/home' in current_url:
                log.info("Facebook login successful")
                self._is_logged_in = True
                
                # Save session state
                await self._save_session(page)
                return True
            else:
                log.warning("Facebook login may have failed")
                await self._save_debug_info(page, "login_failed")
                return False
                
        except Exception as e:
            log.error(f"Facebook login failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _handle_cookie_consent(self, page):
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
    
    async def _handle_checkpoints(self, page):
        """Handle various Facebook checkpoint screens."""
        checkpoint_handlers = [
            # "Save login info" dialog
            ('button:has-text("Not Now")', "Save login - Not Now"),
            ('button:has-text("לא עכשיו")', "Save login - Hebrew"),
            # "Turn on notifications" dialog  
            ('button[aria-label="Close"]', "Close button"),
            ('div[aria-label="Close"]', "Close div"),
            # Continue/OK buttons
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
    
    async def _save_session(self, page):
        """Save session state for future runs."""
        try:
            await self._context.storage_state(path=self.storage_state_file)
            log.info(f"Saved browser state to {self.storage_state_file}")
        except Exception as e:
            log.warning(f"Could not save storage state: {e}")
        
        try:
            cookies = await self._context.cookies()
            with open(self.cookies_file, 'w') as f:
                json.dump(cookies, f)
            log.info(f"Saved cookies to {self.cookies_file}")
        except Exception as e:
            log.warning(f"Could not save cookies: {e}")
    
    async def _save_debug_info(self, page, prefix: str):
        """Save debug screenshot and HTML."""
        os.makedirs("logs", exist_ok=True)
        try:
            await page.screenshot(path=f"logs/debug_{prefix}.png")
            with open(f"logs/debug_{prefix}.html", "w", encoding="utf-8") as f:
                f.write(await page.content())
            log.info(f"Saved debug info with prefix: {prefix}")
        except Exception as e:
            log.warning(f"Could not save debug info: {e}")
    
    async def _close_browser(self):
        """Close browser resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
    
    async def _scrape_group(self, group_url: str) -> List[Listing]:
        """Scrape a single Facebook group."""
        listings = []
        page = await self._context.new_page()
        
        # Use desktop URL
        desktop_url = self._convert_to_desktop_url(group_url)
        
        try:
            # === SESSION WARMING (more natural behavior) ===
            # Occasionally visit homepage first (like a real user would)
            if random.random() < 0.3:  # 30% chance
                log.info("Session warming: visiting Facebook homepage first")
                await page.goto("https://www.facebook.com", wait_until='domcontentloaded', timeout=30000)
                await self.anti_detection.human_like_delay(2, 4)
                
                # Random mouse movement on homepage
                await self.anti_detection.random_mouse_movement(page)
                await asyncio.sleep(random.uniform(1, 3))
            
            # Random initial delay before navigating to group
            await asyncio.sleep(random.uniform(0.5, 2))
            
            log.info(f"Navigating to group: {desktop_url}")
            await page.goto(desktop_url, wait_until='domcontentloaded', timeout=60000)
            await self.anti_detection.human_like_delay(3, 5)
            
            # Check if login required
            current_url = page.url
            page_content = await page.content()
            
            if 'login' in current_url or ('Log In' in page_content and 'Create new account' in page_content):
                log.info("Login required for Facebook group access")
                logged_in = await self._login_to_facebook(page)
                if logged_in:
                    await page.goto(desktop_url, wait_until='domcontentloaded', timeout=60000)
                    await self.anti_detection.human_like_delay(3, 5)
                else:
                    log.error("Cannot access Facebook group without login")
                    return []
            
            # Dismiss any overlays/popups that might be blocking
            await self._dismiss_overlays(page)
            
            # Scroll and collect post data immediately
            post_data_list = await self._scroll_and_collect_posts(page, scroll_count=10)
            
            if not post_data_list:
                log.warning("No posts found in Facebook group", url=group_url)
                await self._save_debug_info(page, "no_posts")
                return []
            
            log.info(f"Found {len(post_data_list)} posts")
            
            # Convert raw data to Listing objects
            for i, raw_data in enumerate(post_data_list):
                try:
                    listing = self.parse_listing(raw_data)
                    if listing:
                        # Filter out old listings (older than 1 day)
                        if listing.posted_at:
                            age = datetime.now() - listing.posted_at
                            if age.days >= 1:
                                log.debug(f"Skipping old listing: {listing.title[:40]}... (age: {age.days} days, posted: {listing.posted_at})")
                                continue
                                
                        log.debug(f"Parsed Facebook listing #{i+1}: {listing.title[:40]}...")
                        listings.append(listing)
                    else:
                        log.debug(f"Skipped invalid post {i}")
                except Exception as e:
                    log.debug(f"Error processing post {i}: {e}")
                    continue
        
        except Exception as e:
            log.error(f"Group scraping failed", url=group_url, error=str(e))
            import traceback
            traceback.print_exc()
            await self._save_debug_info(page, "scrape_failed")
        
        finally:
            await page.close()
        
        return listings
    
    async def _dismiss_overlays(self, page):
        """Dismiss any overlays, popups, or dialogs blocking the page."""
        log.info("Dismissing any overlays...")
        
        # Common close/dismiss selectors for Facebook popups
        dismiss_selectors = [
            'div[aria-label="Close"]',
            'div[aria-label="סגור"]',
            'button[aria-label="Close"]',
            'i.x1b0d499',  # Close X icon
            'div[role="button"]:has-text("Not now")',
            'div[role="button"]:has-text("לא עכשיו")',
            'button:has-text("Not Now")',
            'button:has-text("לא עכשיו")',
            'div[role="button"]:has-text("Decline optional cookies")',
            'button[data-cookiebanner="accept_button"]',
            'button:has-text("Allow all cookies")',
        ]
        
        for selector in dismiss_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    log.info(f"Clicking dismiss button: {selector}")
                    await btn.click()
                    await self.anti_detection.human_like_delay(1, 2)
            except:
                continue
        
        # Click in the middle of the page to ensure focus and dismiss any overlay
        try:
            await page.mouse.click(640, 400)
            await self.anti_detection.human_like_delay(0.5, 1)
            log.info("Clicked on page to focus")
        except:
            pass
        
        # Press Escape to close any dialogs
        try:
            await page.keyboard.press("Escape")
            await self.anti_detection.human_like_delay(0.5, 1)
        except:
            pass
    
    async def _scroll_and_collect_posts(self, page, scroll_count: int = 10) -> List[dict]:
        """Scroll and collect post DATA immediately as they load.
        
        Returns list of raw data dicts (not element handles) to avoid stale references.
        """
        all_post_data = []
        seen_post_ids = set()
        
        # 2025 Facebook group post selectors (desktop)
        post_selector = 'div[role="article"]'
        
        for i in range(scroll_count):
            # Collect current posts and extract data immediately
            try:
                found = await page.query_selector_all(post_selector)
                for post in found:
                    try:
                        # Get bounding box to ensure it's a real post
                        box = await post.bounding_box()
                        if not box or box['height'] < 100:
                            continue
                        
                        # Get text preview for deduplication
                        text_preview = await post.inner_text()
                        post_id = hash(text_preview[:300] if len(text_preview) > 300 else text_preview)
                        
                        if post_id not in seen_post_ids:
                            seen_post_ids.add(post_id)
                            
                            # Extract data IMMEDIATELY while element is valid
                            raw_data = await self._extract_post_data_immediate(page, post)
                            if raw_data:
                                all_post_data.append(raw_data)
                                log.debug(f"Extracted post: {raw_data.get('text', '')[:50]}...")
                    except Exception as e:
                        log.debug(f"Error extracting post: {e}")
                        continue
            except Exception as e:
                log.debug(f"Error finding posts: {e}")
            
            log.info(f"Scroll {i+1}/{scroll_count}: collected {len(all_post_data)} unique posts so far")
            
            # === ENHANCED ANTI-DETECTION SCROLLING ===
            
            # Random scroll distance (not always the same)
            scroll_distance = random.randint(600, 1200)
            await page.mouse.wheel(0, scroll_distance)
            
            # Variable delay between scrolls (2-5 seconds, sometimes longer)
            base_delay = random.uniform(2, 5)
            if random.random() < 0.2:  # 20% chance of longer pause (like reading)
                base_delay += random.uniform(2, 4)
                log.debug("Taking a longer pause to simulate reading...")
            await asyncio.sleep(base_delay)
            
            # Occasional scroll back up (humans do this)
            if random.random() < 0.15:  # 15% chance
                scroll_back = random.randint(100, 300)
                await page.mouse.wheel(0, -scroll_back)
                await asyncio.sleep(random.uniform(0.5, 1.5))
                log.debug("Scrolled back up slightly")
            
            # Random mouse movements (more frequent)
            if random.random() < 0.4:  # 40% chance per scroll
                await self.anti_detection.random_mouse_movement(page)
            
            # Occasional hover over sidebar/header (simulates looking around)
            if random.random() < 0.1:  # 10% chance
                # Move to sidebar area (right side of page)
                x = random.randint(1000, 1200)
                y = random.randint(100, 400)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.5, 1.2))
                log.debug("Looked at sidebar")
            
            # Rare keyboard interaction (pressing Escape to close any popup)
            if random.random() < 0.05:  # 5% chance
                await page.keyboard.press("Escape")
                await asyncio.sleep(random.uniform(0.2, 0.5))
            
            # Very rare: scroll using Page Down instead of mouse wheel
            if random.random() < 0.08:  # 8% chance
                await page.keyboard.press("PageDown")
                await asyncio.sleep(random.uniform(0.5, 1))
        
        log.info(f"Total unique posts collected: {len(all_post_data)}")
        return all_post_data
    
    async def _extract_post_data_immediate(self, page, post_element) -> Optional[dict]:
        """Extract post data immediately while element is valid."""
        try:
            # Click "See more" to expand full text
            await self._expand_post(post_element)
            
            # Get full text from the element
            full_text = await post_element.inner_text()
            
            # Get innerHTML for parsing
            html = await post_element.inner_html()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Clean the text
            text = self._clean_text(full_text)
            
            # Extract author
            author = self._extract_author(soup)
            
            # Extract price
            price = extract_price(text)
            
            # Extract phone number
            contact_info = extract_contact_info(text)
            phone = contact_info.get('phone')
            
            # Extract neighborhood using location database
            location_db = get_location_db()
            location_info = location_db.normalize_location(text)
            neighborhood = location_info.get('neighborhood') or ''
            city = location_info.get('city') or ''
            
            # Extract URL
            url = await self._extract_post_url_immediate(post_element, soup)
            
            # Extract post date/time
            posted_at = await self._extract_post_date(post_element, soup)
            
            return {
                'text': text,
                'url': url,
                'images': [],
                'price': price,
                'author': author,
                'phone': phone,
                'neighborhood': neighborhood,
                'city': city,
                'posted_at': posted_at,
            }
        except Exception as e:
            log.debug(f"Immediate extraction error: {e}")
            return None
    
    async def _extract_post_url_immediate(self, post_element, soup: BeautifulSoup) -> str:
        """Extract permalink URL immediately while element is valid."""
        # Strategy 1: Find links from element
        try:
            links = await post_element.query_selector_all('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]')
            for link in links:
                href = await link.get_attribute('href')
                if href:
                    if href.startswith('/'):
                        return f"https://www.facebook.com{href.split('?')[0]}"
                    return href.split('?')[0]
        except:
            pass
        
        # Strategy 2: Parse from BeautifulSoup  
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            # Improved matching for various Facebook post formats
            if any(p in href for p in ['/posts/', '/permalink/', 'story_fbid', 'fbid=', '/groups/']):
                if not any(x in href for x in ['/members', '/about', '/media', '/join', '/user/']):
                    if href.startswith('/'):
                        # Handle relative URLs correctly
                        if '?' in href:
                             base = href.split('?')[0]
                             return f"https://www.facebook.com{base}"
                        return f"https://www.facebook.com{href}"
                    return href.split('?')[0] if '?' in href else href
        
        return ""
    
    async def _extract_post_date(self, post_element, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract post date from timestamp element.
        
        Facebook shows timestamps like:
        - "2h", "3h" (hours ago)
        - "2 שעות", "3 שעות" (Hebrew hours)
        - "Yesterday", "אתמול" (yesterday)
        - "Just now", "עכשיו" (just now)
        - "Dec 28", "28 בדצמ'" (date format)
        """
        from datetime import timedelta
        import re
        
        now = datetime.now()
        
        try:
            # Look for timestamp links (they usually contain the time)
            timestamp_selectors = [
                'a[role="link"] span',
                'span[id^="jsc"]',
                'abbr',
            ]
            
            timestamp_text = ""
            
            # Try to get timestamp from playwright element
            for selector in timestamp_selectors:
                try:
                    elements = await post_element.query_selector_all(selector)
                    for elem in elements:
                        text = await elem.inner_text()
                        text = text.strip()
                        # Look for time-like patterns
                        if any(pattern in text.lower() for pattern in ['h', 'm', 's', 'd', 'ago', 'שעות', 'דקות', 'שניות', 'ימים', 'אתמול', 'yesterday', 'just now', 'עכשיו']):
                            timestamp_text = text
                            break
                        # Or date patterns
                        if re.match(r'^\d{1,2}[./]\d{1,2}', text) or re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ינו|פבר|מרץ|אפר|מאי|יונ|יול|אוג|ספט|אוק|נוב|דצמ)', text.lower()):
                            timestamp_text = text
                            break
                except:
                    continue
                if timestamp_text:
                    break
            
            if not timestamp_text:
                return None
            
            timestamp_text = timestamp_text.lower().strip()
            
            # Parse relative times
            # Hours ago
            hours_match = re.search(r'(\d+)\s*(?:h|שעות|שעה)', timestamp_text)
            if hours_match:
                hours = int(hours_match.group(1))
                return now - timedelta(hours=hours)
            
            # Minutes ago
            mins_match = re.search(r'(\d+)\s*(?:m|דקות|דקה)', timestamp_text)
            if mins_match:
                mins = int(mins_match.group(1))
                return now - timedelta(minutes=mins)
            
            # Days ago
            days_match = re.search(r'(\d+)\s*(?:d|ימים|יום)', timestamp_text)
            if days_match:
                days = int(days_match.group(1))
                return now - timedelta(days=days)
            
            # Yesterday
            if 'yesterday' in timestamp_text or 'אתמול' in timestamp_text:
                return now - timedelta(days=1)
            
            # Just now
            if 'just now' in timestamp_text or 'עכשיו' in timestamp_text or 'now' in timestamp_text:
                return now
            
            # Weeks ago
            weeks_match = re.search(r'(\d+)\s*(?:w|שבועות|שבוע)', timestamp_text)
            if weeks_match:
                weeks = int(weeks_match.group(1))
                return now - timedelta(weeks=weeks)
            
            # If nothing matched, return None (we'll use current time in parse_listing)
            return None
            
        except Exception as e:
            log.debug(f"Error extracting post date: {e}")
            return None
    
    async def _find_posts(self, page) -> List:
        """Find post elements using multiple selector strategies."""
        await page.evaluate("window.scrollBy(0, 300)")
        await self.anti_detection.human_like_delay(1, 2)
        
        # 2025 Facebook group post selectors (desktop)
        post_selectors = [
            'div[role="article"]',  # Main post container
            'div[data-pagelet^="FeedUnit"]',  # Feed unit container  
            'div.x1yztbdb.x1n2onr6.xh8yej3.x1ja2u2z',  # Modern FB post class
            'div[data-ad-preview="message"]',  # Post with message
            'div.x1lliihq',  # Alternative post container
        ]
        
        for selector in post_selectors:
            try:
                found = await page.query_selector_all(selector)
                if found and len(found) > 0:
                    valid_posts = []
                    for post in found:
                        try:
                            box = await post.bounding_box()
                            if box and box['height'] > 100:
                                valid_posts.append(post)
                        except:
                            valid_posts.append(post)
                    
                    if valid_posts:
                        log.info(f"Found {len(valid_posts)} valid posts using selector: {selector}")
                        return valid_posts
            except Exception as e:
                log.debug(f"Selector {selector} failed: {e}")
                continue
        
        return []
    
    async def _extract_post_data(self, page, post_element) -> Optional[dict]:
        """Extract metadata from a single post element."""
        try:
            # 1. Click "See more" to expand full text
            await self._expand_post(post_element)
            
            # 2. Get innerHTML and parse
            html = await post_element.inner_html()
            soup = BeautifulSoup(html, 'html.parser')
            
            # 3. Extract full text (NO filtering - capture all posts)
            text = await self._extract_full_text(post_element, soup)
            # Keep everything, even if text is empty or short
            
            # 4. Extract author
            author = self._extract_author(soup)
            
            # 5. Extract price
            price = extract_price(text)
            
            # 6. Extract post URL (permalink)
            url = await self._extract_post_url(page, post_element, soup)
            
            return {
                'text': text,
                'url': url,
                'images': [],
                'price': price,
                'author': author,
            }
        
        except Exception as e:
            log.error(f"Extraction error: {e}")
            return None
    
    async def _expand_post(self, post_element):
        """Click ALL 'See more' buttons to fully expand truncated content."""
        see_more_selectors = [
            'div[role="button"]:has-text("See more")',
            'div[role="button"]:has-text("ראה עוד")',
            'div[role="button"]:has-text("עוד")',
            'span:has-text("See more")',
            'span:has-text("ראה עוד")',
            'span:has-text("… עוד")',
            'span:has-text("...עוד")',
            'div.x1i10hfl:has-text("See more")',
            'div.x1i10hfl:has-text("עוד")',
        ]
        
        clicked_any = False
        for selector in see_more_selectors:
            try:
                # Find ALL matching buttons and click them
                buttons = await post_element.query_selector_all(selector)
                for btn in buttons:
                    try:
                        if await btn.is_visible():
                            await btn.click()
                            clicked_any = True
                            await asyncio.sleep(0.3)
                    except:
                        continue
            except:
                continue
        
        if clicked_any:
            await asyncio.sleep(0.5)  # Wait for expansion
            log.debug("Expanded 'See more' content")
    
    async def _extract_full_text(self, post_element, soup: BeautifulSoup) -> str:
        """Extract the full post text content."""
        # Try to get text from Playwright element first (after expansion)
        try:
            # Find the main text container
            text_containers = await post_element.query_selector_all('div[data-ad-preview="message"], div[dir="auto"]')
            
            texts = []
            for container in text_containers:
                try:
                    text = await container.inner_text()
                    if text and len(text) > 20:
                        texts.append(text.strip())
                except:
                    continue
            
            if texts:
                # Get the longest text (likely the main content)
                full_text = max(texts, key=len)
                return self._clean_text(full_text)
        except:
            pass
        
        # Fallback to BeautifulSoup
        raw_text = soup.get_text(separator=' ', strip=True)
        return self._clean_text(raw_text)
    
    def _clean_text(self, text: str) -> str:
        """Clean up extracted text."""
        # Remove common UI artifacts
        artifacts = [
            "See more", "ראה עוד", "See less", "ראה פחות",
            "Like", "Comment", "Share", "לייק", "תגובה", "שיתוף",
            "Translate", "תרגם", "Write a comment...", "כתוב תגובה...",
        ]
        
        clean = text
        for artifact in artifacts:
            clean = clean.replace(artifact, "")
        
        # Clean up whitespace
        while "  " in clean:
            clean = clean.replace("  ", " ")
        
        return clean.strip()
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract the post author name."""
        # Look for author in strong/heading elements
        author_elem = soup.find(['strong', 'h2', 'h3'])
        if author_elem:
            author = author_elem.get_text(strip=True)
            if author and len(author) < 50:
                return author
        
        # Look for links that might be author
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            if '/user/' in href or '/profile.php' in href:
                author = link.get_text(strip=True)
                if author and len(author) < 50:
                    return author
        
        return "Unknown"
    
    async def _extract_post_url(self, page, post_element, soup: BeautifulSoup) -> str:
        """Extract the permalink URL for a post."""
        
        # Strategy 1: Find timestamp links (they link to permalinks)
        timestamp_selectors = [
            'a[href*="/posts/"]',
            'a[href*="/permalink/"]',
            'a[href*="story_fbid"]',
            'span.x4k7w5x a',  # Timestamp container
            'a[role="link"][tabindex="0"]',  # Generic links
        ]
        
        for selector in timestamp_selectors:
            try:
                links = await post_element.query_selector_all(selector)
                for link in links:
                    href = await link.get_attribute('href')
                    if href and any(p in href for p in ['/posts/', '/permalink/', 'story_fbid']):
                        if href.startswith('/'):
                            return f"https://www.facebook.com{href}"
                        return href.split('?')[0] if '?' in href else href
            except:
                continue
        
        # Strategy 2: Parse from BeautifulSoup
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            if any(p in href for p in ['/posts/', '/permalink/', 'story_fbid']):
                if not any(x in href for x in ['/members', '/about', '/media', '/join']):
                    if href.startswith('/'):
                        return f"https://www.facebook.com{href}"
                    return href.split('?')[0] if '?' in href else href
        
        # Strategy 3: Look for "more options" or timestamp area
        try:
            # Find any link that could be a timestamp (short text like "2h", "Yesterday")
            all_links = await post_element.query_selector_all('a')
            for link in all_links:
                try:
                    text = await link.inner_text()
                    href = await link.get_attribute('href')
                    # Timestamp-like short text
                    if href and len(text) < 15 and ('facebook.com' in href or href.startswith('/')):
                        if '/groups/' in href and '/posts/' not in href and '/permalink/' not in href:
                            continue  # Skip group links
                        if '/posts/' in href or '/permalink/' in href or 'story' in href:
                            if href.startswith('/'):
                                return f"https://www.facebook.com{href}"
                            return href.split('?')[0] if '?' in href else href
                except:
                    continue
        except:
            pass
        
        return ""
    
    async def _slow_scroll(self, page, steps: int = 5, distance: int = 500):
        """Scroll the page slowly to trigger lazy loading."""
        log.debug(f"Slow scrolling {steps} times by {distance}px")
        for i in range(steps):
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await self.anti_detection.human_like_delay(1.5, 3.0)
            
            # Occasional mouse movement
            if i % 2 == 0:
                await self.anti_detection.random_mouse_movement(page)
    
    def parse_listing(self, raw_data: dict) -> Optional[Listing]:
        """Convert raw post data to a Listing object - NO FILTERING."""
        text = raw_data.get('text', '') or ''
        url = raw_data.get('url', '')
        author = raw_data.get('author', 'Unknown')
        
        # NO FILTERING - capture all posts
        
        # Generate unique ID
        id_seed = url if url and len(url) > 30 else f"{self.source_name}_{hashlib.md5(text[:200].encode()).hexdigest()}"
        listing_id = self.generate_listing_id(id_seed)
        
        # Extract structured data - use pre-extracted values from raw_data
        price = raw_data.get('price') or extract_price(text)
        bedrooms = extract_bedrooms(text)
        
        # Use neighborhood/city from location database (pre-extracted)
        neighborhood = raw_data.get('neighborhood', '')
        city = raw_data.get('city', '')
        location = f"{neighborhood}, {city}".strip(", ") if neighborhood or city else self._extract_location(text)
        
        # Phone number
        phone = raw_data.get('phone', '')
        
        # Generate title
        first_line = text.split('\n')[0][:50].strip() or "דירה להשכרה"
        title = f"{author}: {first_line}" if author != "Unknown" else first_line
        
        # Post date
        posted_at = raw_data.get('posted_at')
        
        log.debug(f"Parsed: ID={listing_id[:8]}, URL={'[OK]' if url else '[MISSING]'}, Price={price}, Phone={phone}, Location={location}, Posted={posted_at}")
        
        return Listing(
            id=listing_id,
            source=self.source_name,
            url=url or "",
            title=title,
            description=text,
            location=location,
            raw_text=text,
            price=price,
            bedrooms=bedrooms,
            phone=phone,
            images=raw_data.get('images', []),
            posted_at=posted_at,
            scraped_at=datetime.now(),
        )
    
    def _extract_location(self, text: str) -> str:
        """Try to extract location from text."""
        location_patterns = [
            ('בתל אביב', 'תל אביב'),
            ('תל-אביב', 'תל אביב'),
            ('תל אביב', 'תל אביב'),
            ('בירושלים', 'ירושלים'),
            ('ירושלים', 'ירושלים'),
            ('בחיפה', 'חיפה'),
            ('חיפה', 'חיפה'),
            ('ברמת גן', 'רמת גן'),
            ('רמת גן', 'רמת גן'),
            ('בגבעתיים', 'גבעתיים'),
            ('גבעתיים', 'גבעתיים'),
            ('בהרצליה', 'הרצליה'),
            ('הרצליה', 'הרצליה'),
            ('בראשון', 'ראשון לציון'),
            ('ראשון לציון', 'ראשון לציון'),
            ('בפתח תקווה', 'פתח תקווה'),
            ('פתח תקווה', 'פתח תקווה'),
            ('בנתניה', 'נתניה'),
            ('נתניה', 'נתניה'),
            ('בבאר שבע', 'באר שבע'),
            ('באר שבע', 'באר שבע'),
        ]
        
        for pattern, location in location_patterns:
            if pattern in text:
                return location
        
        return ""
