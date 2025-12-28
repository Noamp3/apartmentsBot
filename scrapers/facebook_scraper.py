# scrapers/facebook_scraper.py
"""Facebook groups scraper for apartment listings."""

import hashlib
from datetime import datetime
from typing import List, Optional

from scrapers.base_scraper import BaseScraper
from scrapers.anti_detection import AntiDetectionModule
from models.listing import Listing
from utils.logger import Loggers
from utils.hebrew_utils import extract_price, extract_bedrooms

log = Loggers.scraper()


class FacebookScraper(BaseScraper):
    """Scrapes apartment listings from Facebook groups.
    
    Uses m.facebook.com (mobile version) for simpler HTML and better stealth.
    
    IMPORTANT: Uses persistent cookies to avoid login on every run.
    First run requires login, subsequent runs reuse session.
    """
    
    # Use mobile Facebook for simpler scraping
    BASE_URL = "https://m.facebook.com"
    LOGIN_URL = "https://m.facebook.com/login"
    
    COOKIES_FILE = "data/fb_cookies.json"
    STORAGE_STATE_FILE = "data/fb_storage_state.json"
    
    # Mobile user agents for better stealth
    MOBILE_USER_AGENTS = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
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
        self._is_logged_in = False
        
        # Ensure data directory exists
        import os
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
                    continue
        
        finally:
            await self._close_browser()
        
        log.info(f"Facebook scrape complete", total_listings=len(listings))
        return listings
    
    async def _init_browser(self):
        """Initialize Playwright browser with stealth settings and persistent state."""
        try:
            from playwright.async_api import async_playwright
            import os
            
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )
            
            # Try to load existing storage state (includes cookies + localStorage)
            storage_state = None
            if os.path.exists(self.storage_state_file):
                try:
                    storage_state = self.storage_state_file
                    log.info("Loading persisted browser state")
                except Exception as e:
                    log.warning(f"Could not load storage state: {e}")
            
            self._context = await self._browser.new_context(
                user_agent=self._get_mobile_user_agent(),
                viewport={'width': 390, 'height': 844},  # iPhone 14 size
                locale='he-IL',
                is_mobile=True,
                has_touch=True,
                storage_state=storage_state,  # Restore full session
            )
            
            # Fallback: Load cookies if storage state didn't exist
            if not storage_state and os.path.exists(self.cookies_file):
                try:
                    import json
                    with open(self.cookies_file, 'r') as f:
                        cookies = json.load(f)
                    await self._context.add_cookies(cookies)
                    log.info("Loaded Facebook cookies from file")
                except Exception as e:
                    log.warning(f"Could not load cookies: {e}")
            
            # Inject stealth scripts
            await self._context.add_init_script(self.anti_detection.add_stealth_scripts())
            
        except ImportError:
            log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            raise
    
    def _get_mobile_user_agent(self) -> str:
        """Get a random mobile user agent."""
        import random
        return random.choice(self.MOBILE_USER_AGENTS)
    
    def _convert_to_mobile_url(self, url: str) -> str:
        """Convert desktop Facebook URL to mobile version."""
        return url.replace("www.facebook.com", "m.facebook.com").replace("facebook.com", "m.facebook.com")
    
    async def _login_to_facebook(self, page):
        """Login to Facebook with credentials from config (mobile version)."""
        from config import settings
        
        if not settings.FACEBOOK_EMAIL or not settings.FACEBOOK_PASSWORD:
            log.warning("Facebook credentials not configured. Set FACEBOOK_EMAIL and FACEBOOK_PASSWORD in .env")
            return False
        
        try:
            log.info("Logging into mobile Facebook...")
            await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
            await self.anti_detection.human_like_delay(1, 2)
            
            # Mobile Facebook selectors (simpler than desktop)
            # Fill email - mobile uses name="email"
            email_input = await page.query_selector('input[name="email"]')
            if not email_input:
                email_input = await page.query_selector('#m_login_email')
            if email_input:
                await email_input.fill(settings.FACEBOOK_EMAIL)
                await self.anti_detection.human_like_delay(0.5, 1)
            
            # Fill password - mobile uses name="pass"
            password_input = await page.query_selector('input[name="pass"]')
            if not password_input:
                password_input = await page.query_selector('#m_login_password')
            if password_input:
                await password_input.fill(settings.FACEBOOK_PASSWORD)
                await self.anti_detection.human_like_delay(0.5, 1)
            
            # Click login button
            login_button = await page.query_selector('button[name="login"]')
            if login_button:
                await login_button.click()
                await self.anti_detection.human_like_delay(3, 5)
            
            # Wait for navigation
            await page.wait_for_load_state('networkidle', timeout=30000)
            
            # Check if login was successful
            current_url = page.url
            if 'login' not in current_url and 'checkpoint' not in current_url:
                log.info("Facebook login successful")
                self._is_logged_in = True
                
                # Save FULL storage state (cookies + localStorage + sessionStorage)
                # This is the key to avoiding repeated logins
                try:
                    await self._context.storage_state(path=self.storage_state_file)
                    log.info(f"Saved browser state to {self.storage_state_file}")
                except Exception as e:
                    log.warning(f"Could not save storage state: {e}")
                
                # Also save cookies as backup
                try:
                    cookies = await self._context.cookies()
                    import json
                    with open(self.cookies_file, 'w') as f:
                        json.dump(cookies, f)
                except Exception:
                    pass
                
                return True
            else:
                log.warning("Facebook login may have failed or requires verification")
                return False
                
        except Exception as e:
            log.error(f"Facebook login failed: {e}")
            return False
    
    async def _close_browser(self):
        """Close browser resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
    
    async def _scrape_group(self, group_url: str) -> List[Listing]:
        """Scrape a single Facebook group (mobile version)."""
        listings = []
        page = await self._context.new_page()
        
        # Convert to mobile URL
        mobile_url = self._convert_to_mobile_url(group_url)
        
        try:
            await page.goto(mobile_url, wait_until='networkidle', timeout=60000)
            await self.anti_detection.human_like_delay(2, 4)
            
            # Check if we need to login (redirected to login page)
            current_url = page.url
            if 'login' in current_url or 'checkpoint' in current_url:
                log.info("Login required for Facebook group access")
                logged_in = await self._login_to_facebook(page)
                if logged_in:
                    # Navigate back to group
                    await page.goto(mobile_url, wait_until='networkidle', timeout=60000)
                    await self.anti_detection.human_like_delay(2, 4)
                else:
                    log.error("Cannot access Facebook group without login")
                    return []
            
            # Scroll to load more posts (mobile-style scrolling)
            await self.anti_detection.random_scroll_behavior(page)
            await self.anti_detection.random_scroll_behavior(page)
            
            # Mobile Facebook post selectors (simpler than desktop)
            post_selectors = [
                'article',  # Mobile uses article tags
                'div[data-ft]',  # Data-ft attribute on posts
                'div.story_body_container',
                'div[role="article"]',
            ]
            
            posts = []
            for selector in post_selectors:
                try:
                    found = await page.query_selector_all(selector)
                    if found:
                        posts = found
                        break
                except Exception:
                    continue
            
            if not posts:
                log.warning("No posts found in Facebook group", url=group_url)
                return []
            
            log.info(f"Found {len(posts)} posts")
            
            for i, post in enumerate(posts[:20]):  # Limit to prevent rate limiting
                try:
                    raw_data = await self._extract_post_data(post)
                    if raw_data:
                        listing = self.parse_listing(raw_data)
                        if listing:
                            log.debug(f"Parsed Facebook listing: {listing.title} ({listing.price} ILS)")
                            listings.append(listing)
                        else:
                            log.debug(f"Skipped invalid post {i}")
                    else:
                        log.debug(f"Failed to extract info from post {i}")
                except Exception as e:
                    log.debug(f"Error processing post {i}: {e}")
                    continue
        
        except Exception as e:
            log.error(f"Group scraping failed", url=group_url, error=str(e))
        
        finally:
            await page.close()
        
        return listings
    
    async def _extract_post_data(self, post_element) -> Optional[dict]:
        """Extract data from a single Facebook post element."""
        try:
            # Get text content
            text = await post_element.inner_text()
            if not text or len(text) < 20:
                return None
            
            # Check if it looks like an apartment listing
            apartment_keywords = ['דירה', 'חדרים', 'שכירות', 'להשכרה', 'חדר', 'דירת']
            if not any(kw in text for kw in apartment_keywords):
                return None
            
            # Try to get URL
            url = ""
            try:
                link = await post_element.query_selector('a[href*="/groups/"]')
                if link:
                    url = await link.get_attribute('href')
            except Exception:
                pass
            
            # Get any images
            images = []
            try:
                img_elements = await post_element.query_selector_all('img')
                for img in img_elements[:5]:
                    src = await img.get_attribute('src')
                    if src and 'scontent' in src:
                        images.append(src)
            except Exception:
                pass
            
            return {
                'text': text,
                'url': url,
                'images': images,
            }
        
        except Exception:
            return None
    
    def parse_listing(self, raw_data: dict) -> Optional[Listing]:
        """Convert raw post data to a Listing object."""
        text = raw_data.get('text', '')
        url = raw_data.get('url', '')
        
        if not text:
            return None
        
        # Generate ID
        listing_id = self.generate_listing_id(url or text[:100])
        
        # Extract structured data
        price = extract_price(text)
        bedrooms = extract_bedrooms(text)
        
        # Try to extract location from text
        location = self._extract_location(text)
        
        # Generate a title from first line or summary
        title = text.split('\n')[0][:100] if text else "דירה להשכרה"
        
        log.debug(f"Extracted attributes: Price={price}, Rooms={bedrooms}, Loc={location}")
        
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
            images=raw_data.get('images', []),
            scraped_at=datetime.now(),
        )
    
    def _extract_location(self, text: str) -> str:
        """Try to extract location from text."""
        # Common location indicators
        location_patterns = [
            ('בתל אביב', 'תל אביב'),
            ('תל-אביב', 'תל אביב'),
            ('בירושלים', 'ירושלים'),
            ('בחיפה', 'חיפה'),
            ('ברמת גן', 'רמת גן'),
            ('בגבעתיים', 'גבעתיים'),
            ('בהרצליה', 'הרצליה'),
        ]
        
        text_lower = text.lower()
        for pattern, location in location_patterns:
            if pattern in text_lower or pattern.replace('ב', '') in text_lower:
                return location
        
        return ""
