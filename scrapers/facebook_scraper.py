# scrapers/facebook_scraper.py
"""Facebook groups scraper for apartment listings.

Uses playwright-stealth for anti-detection and desktop Facebook for reliable
permalink extraction. Refactored into modular components.
"""

import asyncio
import hashlib
import os
from datetime import datetime
from typing import List, Optional

from scrapers.base_scraper import BaseScraper
from scrapers.anti_detection import AntiDetectionModule
from scrapers.self_healing import SelfHealingManager
from scrapers.facebook.session import FacebookSessionManager
from scrapers.facebook.parser import FacebookPostParser
from models.listing import Listing
from utils.logger import Loggers
from utils.hebrew_utils import extract_price, extract_bedrooms, extract_contact_info, parse_relative_date
from utils.israeli_locations import get_location_db
import random

from bs4 import BeautifulSoup
from config import settings

log = Loggers.scraper()

class FacebookLoginRequiredException(Exception):
    """Raised when Facebook requires login but authentication fails or is not available."""
    pass


class FacebookScraper(BaseScraper):
    """Scrapes apartment listings from Facebook groups.
    
    Uses desktop Facebook for more reliable permalink extraction.
    Implements playwright-stealth for advanced anti-detection.
    """
    
    BASE_URL = "https://www.facebook.com"
    LOGIN_URL = "https://www.facebook.com/login"
    COOKIES_FILE = "data/fb_cookies.json"
    STORAGE_STATE_FILE = "data/fb_storage_state.json"
    DESKTOP_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]
    
    def __init__(
        self, 
        group_urls: List[str],
        anti_detection: AntiDetectionModule = None,
        is_seen_callback: callable = None,
        cookies_file: str = None,
        storage_state_file: str = None,
        ai_engine = None
    ):
        self.group_urls = group_urls
        self.anti_detection = anti_detection or AntiDetectionModule()
        self.is_seen_callback = is_seen_callback
        self.cookies_file = cookies_file or self.COOKIES_FILE
        self.storage_state_file = storage_state_file or self.STORAGE_STATE_FILE
        
        # Initialize Self-Healing Manager
        self.healer = SelfHealingManager(ai_engine=ai_engine, source="facebook")
        
        # Initialize Session Manager
        self.session_manager = FacebookSessionManager(
            cookies_file=self.cookies_file,
            storage_state_file=self.storage_state_file,
            anti_detection=self.anti_detection,
            bot=None
        )
        
        # Initialize Parser Helper
        self.parser = FacebookPostParser(
            healer=self.healer,
            anti_detection=self.anti_detection
        )
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.cookies_file), exist_ok=True)

    @property
    def source_name(self) -> str:
        return "facebook"

    # Properties to maintain backward compatibility with direct calls or patches in tests
    @property
    def _browser(self):
        return self.session_manager.browser

    @property
    def _context(self):
        return self.session_manager.context

    @property
    def _stealth(self):
        return self.session_manager.stealth

    @property
    def _is_logged_in(self):
        return self.session_manager.is_logged_in

    @property
    def bot(self):
        return self.session_manager.bot

    @bot.setter
    def bot(self, value):
        self.session_manager.bot = value

    # Delegating methods for backward compatibility
    def _get_desktop_user_agent(self) -> str:
        return self.session_manager.get_desktop_user_agent()

    def _convert_to_desktop_url(self, url: str) -> str:
        if "m.facebook.com" in url:
            return url.replace("m.facebook.com", "www.facebook.com")
        if "www.facebook.com" not in url and "facebook.com" in url:
            return url.replace("facebook.com", "www.facebook.com")
        return url

    async def _init_browser(self):
        await self.session_manager.init_browser()

    async def _login_to_facebook(self, page) -> bool:
        return await self.session_manager.login_to_facebook(page)

    async def _handle_cookie_consent(self, page):
        await self.session_manager.handle_cookie_consent(page)

    async def _handle_checkpoints(self, page):
        await self.session_manager.handle_checkpoints(page)

    async def _save_session(self, page):
        await self.session_manager.save_session(page)

    async def _save_debug_info(self, page, prefix: str):
        await self.session_manager.save_debug_info(page, prefix)

    async def _notify_login_required(self):
        await self.session_manager.notify_login_required()

    async def _close_browser(self):
        await self.session_manager.close_browser()

    # Parser delegation
    def _clean_text(self, text: str) -> str:
        return self.parser.clean_text(text)

    def _extract_author(self, soup: BeautifulSoup) -> str:
        return self.parser.extract_author(soup)

    async def _expand_post(self, post_element):
        await self.parser.expand_post(post_element)

    async def _extract_full_text(self, post_element, soup: BeautifulSoup) -> str:
        return await self.parser.extract_full_text(post_element, soup)

    async def _extract_post_url_immediate(self, page, post_element, soup: BeautifulSoup) -> str:
        return await self.parser.extract_post_url_immediate(page, post_element, soup)

    async def _extract_post_date(self, page, post_element, soup: BeautifulSoup) -> Optional[datetime]:
        return await self.parser.extract_post_date(page, post_element, soup)

    async def _find_posts(self, page) -> List:
        return await self.parser.find_posts(page)

    async def _extract_post_data_immediate(self, page, post_element) -> Optional[dict]:
        return await self.parser.extract_post_data_immediate(page, post_element)

    async def _extract_post_data(self, page, post_element) -> Optional[dict]:
        return await self.parser.extract_post_data(page, post_element)

    async def _extract_post_url(self, page, post_element, soup: BeautifulSoup) -> str:
        return await self.parser.extract_post_url(page, post_element, soup)

    # Core scraping loop orchestration
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
                    
                except FacebookLoginRequiredException as le:
                    log.error(f"Aborting scraping cycle: Facebook login is required but failed. {le}")
                    break
                except Exception as e:
                    log.error(f"Failed to scrape group", url=group_url, error=str(e))
                    import traceback
                    traceback.print_exc()
                    continue
        
        finally:
            await self._close_browser()
        
        log.info(f"Facebook scrape complete", total_listings=len(listings))
        return listings

    async def _scrape_group(self, group_url: str) -> List[Listing]:
        """Scrape a single Facebook group."""
        listings = []
        page = await self._context.new_page()
        
        # Use desktop URL
        desktop_url = self._convert_to_desktop_url(group_url)
        
        try:
            # === SESSION WARMING (more natural behavior) ===
            if random.random() < 0.3:  # 30% chance
                log.info("Session warming: visiting Facebook homepage first")
                await page.goto("https://www.facebook.com", wait_until='domcontentloaded', timeout=30000)
                await self.anti_detection.human_like_delay(2, 4)
                await self.anti_detection.random_mouse_movement(page)
                await asyncio.sleep(random.uniform(1, 3))
            
            await asyncio.sleep(random.uniform(0.5, 2))
            
            log.info(f"Navigating to group: {desktop_url}")
            await page.goto(desktop_url, wait_until='domcontentloaded', timeout=60000)
            await self.anti_detection.human_like_delay(3, 5)
            
            # Check if login required
            current_url = page.url
            page_content = await page.content()
            
            if 'login' in current_url or 'checkpoint' in current_url or ('Log In' in page_content and 'Create new account' in page_content):
                log.info("Login required for Facebook group access")
                logged_in = await self._login_to_facebook(page)
                if logged_in:
                    await page.goto(desktop_url, wait_until='domcontentloaded', timeout=60000)
                    await self.anti_detection.human_like_delay(3, 5)
                else:
                    log.error("Cannot access Facebook group without login")
                    await self._notify_login_required()
                    raise FacebookLoginRequiredException("Facebook login is required and failed or was not completed.")
            
            await self._dismiss_overlays(page)
            
            # Detect auto-redirect and correct course
            current_url = page.url
            if "/groups/" in current_url and ("/members" in current_url or "/about" in current_url):
                tab_name = "/members" if "/members" in current_url else "/about"
                discussion_url = current_url.split(tab_name)[0] + "/"
                log.info(f"Detected auto-redirect to {tab_name} tab. Correcting course to base group URL: {discussion_url}")
                await page.goto(discussion_url, wait_until='domcontentloaded', timeout=60000)
                await self.anti_detection.human_like_delay(3, 5)
                await self._dismiss_overlays(page)
            
            post_data_list = await self._scroll_and_collect_posts(page, scroll_count=10)
            
            if not post_data_list:
                log.warning("No posts found in Facebook group", url=group_url)
                await self._save_debug_info(page, "no_posts")
                return []
            
            log.info(f"Found {len(post_data_list)} posts")
            
            for i, raw_data in enumerate(post_data_list):
                try:
                    listing = self.parse_listing(raw_data)
                    if listing:
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
            await self._save_debug_info(page, "scrape_failed")
        
        finally:
            await page.close()
        
        return listings

    async def _dismiss_overlays(self, page):
        """Dismiss any overlays, popups, or dialogs blocking the page."""
        log.info("Dismissing any overlays...")
        
        dismiss_selectors = [
            'div[role="dialog"] div[aria-label="Close"]',
            'div[role="dialog"] div[aria-label="סגור"]',
            'div[role="dialog"] button[aria-label="Close"]',
            'div[role="dialog"] i.x1b0d499',
            'div[role="dialog"] div[role="button"]:has-text("Not now")',
            'div[role="dialog"] div[role="button"]:has-text("לא עכשיו")',
            'div[role="dialog"] button:has-text("Not Now")',
            'div[role="dialog"] button:has-text("לא עכשיו")',
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
        
        try:
            await page.focus('body')
            await self.anti_detection.human_like_delay(0.5, 1)
            log.info("Focused page body to ensure keyboard controls work")
        except:
            pass
        
        try:
            await page.keyboard.press("Escape")
            await self.anti_detection.human_like_delay(0.5, 1)
        except:
            pass

    async def _scroll_and_collect_posts(self, page, scroll_count: int = 10) -> List[dict]:
        """Scroll and collect post DATA immediately as they load."""
        all_post_data = []
        seen_post_ids = set()
        
        post_selector = self.healer.get_selector("post_container")
        checked_count = 0
        already_seen_in_db_count = 0
        
        for i in range(scroll_count):
            try:
                found = await self._find_posts(page)
                for post in found:
                    try:
                        box = await post.bounding_box()
                        if not box or box['height'] < 100:
                            continue
                        
                        text_preview = await post.inner_text()
                        post_id = hash(text_preview[:300] if len(text_preview) > 300 else text_preview)
                        
                        if post_id not in seen_post_ids:
                            seen_post_ids.add(post_id)
                            
                            raw_data = await self._extract_post_data_immediate(page, post)
                            if raw_data:
                                all_post_data.append(raw_data)
                                log.debug(f"Extracted post: {raw_data.get('text', '')[:50]}...")
                                
                                if self.is_seen_callback and checked_count < 10:
                                    checked_count += 1
                                    listing_id = self._generate_id_from_raw(raw_data)
                                    
                                    is_in_db = await self.is_seen_callback(listing_id)
                                    if is_in_db:
                                        already_seen_in_db_count += 1
                                    
                                    if checked_count == 10 and already_seen_in_db_count == 10:
                                        log.info("Terminating search in group early: first 10 posts are already seen in database")
                                        return all_post_data

                    except Exception as e:
                        log.debug(f"Error extracting post: {e}")
                        continue
            except Exception as e:
                log.debug(f"Error finding posts: {e}")
            
            log.info(f"Scroll {i+1}/{scroll_count}: collected {len(all_post_data)} unique posts so far")
            
            scroll_distance = random.randint(600, 1200)
            await page.mouse.wheel(0, scroll_distance)
            
            base_delay = random.uniform(2, 5)
            if random.random() < 0.2:
                base_delay += random.uniform(2, 4)
                log.debug("Taking a longer pause to simulate reading...")
            await asyncio.sleep(base_delay)
            
            if random.random() < 0.15:
                scroll_back = random.randint(100, 300)
                await page.mouse.wheel(0, -scroll_back)
                await asyncio.sleep(random.uniform(0.5, 1.5))
                log.debug("Scrolled back up slightly")
            
            if random.random() < 0.4:
                await self.anti_detection.random_mouse_movement(page)
            
            if random.random() < 0.1:
                x = random.randint(1000, 1200)
                y = random.randint(100, 400)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.5, 1.2))
                log.debug("Looked at sidebar")
            
            if random.random() < 0.05:
                await page.keyboard.press("Escape")
                await asyncio.sleep(random.uniform(0.2, 0.5))
            
            if random.random() < 0.08:
                await page.keyboard.press("PageDown")
                await asyncio.sleep(random.uniform(0.5, 1))
        
        if not all_post_data and settings.FACEBOOK_SELF_HEALING_ENABLED:
            log.warning("No posts collected. Attempting self-healing for post container selector...")
            healed_selector = await self.healer.heal_post_container(page, post_selector)
            if healed_selector:
                log.info(f"Self-healing succeeded! Retrying post collection using healed selector: '{healed_selector}'")
                post_selector = healed_selector
                try:
                    found = await page.query_selector_all(post_selector)
                    for post in found:
                        try:
                            box = await post.bounding_box()
                            if not box or box['height'] < 100:
                                continue
                            
                            text_preview = await post.inner_text()
                            post_id = hash(text_preview[:300] if len(text_preview) > 300 else text_preview)
                            
                            if post_id not in seen_post_ids:
                                seen_post_ids.add(post_id)
                                raw_data = await self._extract_post_data_immediate(page, post)
                                if raw_data:
                                    all_post_data.append(raw_data)
                        except Exception as e:
                            log.debug(f"Error during retry extraction: {e}")
                except Exception as e:
                    log.error(f"Error during self-healed retry scan: {e}")
        
        log.info(f"Total unique posts collected: {len(all_post_data)}")
        return all_post_data

    async def _slow_scroll(self, page, steps: int = 5, distance: int = 500):
        """Scroll the page slowly to trigger lazy loading."""
        log.debug(f"Slow scrolling {steps} times by {distance}px")
        for i in range(steps):
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await self.anti_detection.human_like_delay(1.5, 3.0)
            if i % 2 == 0:
                await self.anti_detection.random_mouse_movement(page)

    def parse_listing(self, raw_data: dict) -> Listing:
        """Convert raw post data to a Listing object."""
        text = raw_data.get('text', '') or ''
        url = raw_data.get('url', '')
        author = raw_data.get('author', 'Unknown')
        
        listing_id = self._generate_id_from_raw(raw_data)
        
        price = raw_data.get('price') or extract_price(text)
        bedrooms = extract_bedrooms(text)
        
        neighborhood = raw_data.get('neighborhood', '')
        city = raw_data.get('city', '')
        location = f"{neighborhood}, {city}".strip(", ") if neighborhood or city else self._extract_location(text)
        
        phone = raw_data.get('phone', '')
        
        first_line = text.split('\n')[0][:50].strip() or "דירה להשכרה"
        title = f"{author}: {first_line}" if author != "Unknown" else first_line
        
        posted_at = raw_data.get('posted_at')
        if not posted_at and text:
            posted_at = self._extract_date_from_text(text)
        if not posted_at:
            posted_at = datetime.now()
            log.debug(f"No date found for post, using current time as fallback")
        
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
            author=author,
            images=raw_data.get('images', []),
            screenshots=raw_data.get('screenshots', {}),
            posted_at=posted_at,
            scraped_at=datetime.now(),
        )

    def _extract_date_from_text(self, text: str) -> Optional[datetime]:
        """Extract date from text when element-based extraction fails."""
        return parse_relative_date(text)

    def _generate_id_from_raw(self, raw_data: dict) -> str:
        """Generate a unique ID for a listing based on raw data."""
        url = raw_data.get('url', '')
        text = raw_data.get('text', '') or ''
        id_seed = url if url and len(url) > 30 else f"{self.source_name}_{hashlib.md5(text[:200].encode()).hexdigest()}"
        return self.generate_listing_id(id_seed)

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
