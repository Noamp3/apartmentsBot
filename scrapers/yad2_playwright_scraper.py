# scrapers/yad2_playwright_scraper.py
"""Playwright-based Yad2 scraper for apartment listings.

Uses Playwright with stealth mode to avoid CAPTCHA challenges and bot detection.
This implementation provides a full browser environment that's harder to detect
than HTTP-based scraping.
"""

import asyncio
import random
import os
import json
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from scrapers.base_scraper import BaseScraper
from scrapers.anti_detection import AntiDetectionModule
from models.listing import Listing
from utils.logger import Loggers
from utils.hebrew_utils import extract_yad2_posted_date

log = Loggers.scraper()


class Yad2PlaywrightScraper(BaseScraper):
    """Scrapes apartment listings from Yad2.co.il using Playwright.
    
    Provides full browser environment with JavaScript execution and
    anti-detection measures to avoid CAPTCHA challenges.
    """
    
    BASE_URL = "https://www.yad2.co.il"
    RENT_URL = "https://www.yad2.co.il/realestate/rent"
    
    # Storage for persistent session
    STORAGE_STATE_FILE = "data/yad2_storage_state.json"
    
    # Desktop user agents (2025)
    DESKTOP_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]
    
    def __init__(
        self,
        city_id: str = None,
        min_price: int = None,
        max_price: int = None,
        min_rooms: float = None,
        max_rooms: float = None,
        max_listings: int = 50,
        max_pages: int = 3,
        anti_detection: AntiDetectionModule = None,
        storage_state_file: str = None
    ):
        self.city_id = city_id
        self.min_price = min_price
        self.max_price = max_price
        self.min_rooms = min_rooms
        self.max_rooms = max_rooms
        self.max_listings = max_listings
        self.max_pages = max_pages
        
        self.anti_detection = anti_detection or AntiDetectionModule()
        self.storage_state_file = storage_state_file or self.STORAGE_STATE_FILE
        self._browser = None
        self._context = None
        self._stealth = None
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.storage_state_file), exist_ok=True)
    
    @property
    def source_name(self) -> str:
        return "yad2"
    
    def _build_url_params(self, page: int = 1) -> Dict[str, Any]:
        """Build URL parameters for Yad2 search."""
        params = {
            "page": page,
            "topArea": 2,  # מרכז (Center region)
            "area": 1,     # אזור תל אביב יפו
        }
        
        if self.city_id:
            params["city"] = self.city_id
        
        # Price filters
        if self.min_price is not None:
            params["minPrice"] = self.min_price
        if self.max_price is not None:
            params["maxPrice"] = self.max_price
        
        # Room filters
        if self.min_rooms is not None:
            params["minRooms"] = int(self.min_rooms)
        if self.max_rooms is not None:
            params["maxRooms"] = int(self.max_rooms)
        
        return params
    
    async def scrape(self, on_listing_scraped: Optional[callable] = None) -> List[Listing]:
        """Scrape listings from Yad2 using Playwright."""
        log.debug(f"Starting Yad2 Playwright scrape. City={self.city_id}, Price={self.min_price}-{self.max_price}")
        listings = []
        
        try:
            await self._init_browser()
            
            log.info("Scraping Yad2 via Playwright (full browser)")
            listings = await self._scrape_with_browser(on_listing_scraped=on_listing_scraped)
            
        except Exception as e:
            log.error(f"[Yad2] Playwright scrape failed: {e}", exc_info=True)
        finally:
            await self._close_browser()
        
        log.info(f"Yad2 Playwright scrape complete", total_listings=len(listings))
        return listings
    
    async def _init_browser(self):
        """Initialize Playwright browser with comprehensive anti-detection."""
        try:
            from playwright.async_api import async_playwright
            from playwright_stealth import Stealth
            
            # Initialize stealth
            self._stealth = Stealth(
                navigator_languages_override=('he-IL', 'he', 'en-US', 'en'),
                init_scripts_only=False,
            )
            
            self._playwright = await async_playwright().start()
            
            # Randomized viewport
            viewports = [
                {'width': 1920, 'height': 1080},
                {'width': 1366, 'height': 768},
                {'width': 1536, 'height': 864},
                {'width': 1440, 'height': 900},
            ]
            viewport = random.choice(viewports)
            log.info(f"Using viewport: {viewport['width']}x{viewport['height']}")
            
            # Launch browser
            import platform
            is_arm = platform.machine().lower() in ['arm64', 'aarch64']
            is_linux = platform.system().lower() == 'linux'
            browser_channel = "msedge" if not (is_arm and is_linux) else None
            if browser_channel:
                log.info(f"Launching browser with channel: {browser_channel}")
            else:
                log.info("Launching standard Chromium browser (no channel specified)")

            from config import settings
            self._browser = await self._playwright.chromium.launch(
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
                    '--mute-audio',
                ]
            )
            
            # Try to load existing storage state
            storage_state = None
            if os.path.exists(self.storage_state_file):
                try:
                    storage_state = self.storage_state_file
                    log.info("Loading persisted Yad2 browser state")
                except Exception as e:
                    log.warning(f"Could not load storage state: {e}")
            
            # Create context with anti-fingerprinting
            self._context = await self._browser.new_context(
                user_agent=random.choice(self.DESKTOP_USER_AGENTS),
                viewport=viewport,
                locale='he-IL',
                timezone_id='Asia/Jerusalem',
                geolocation={'longitude': 34.7818, 'latitude': 32.0853},  # Tel Aviv
                permissions=['geolocation'],
                storage_state=storage_state,
                screen={'width': viewport['width'], 'height': viewport['height']},
                device_scale_factor=random.choice([1, 1.25, 1.5]),
                has_touch=False,
                is_mobile=False,
                color_scheme='light',
            )
            
            # Apply playwright-stealth
            await self._stealth.apply_stealth_async(self._context)
            log.info("Applied playwright-stealth to Yad2 browser context")
            
            # Add additional stealth scripts
            await self._context.add_init_script(self.anti_detection.add_stealth_scripts())
            
        except ImportError as e:
            log.error("[Yad2] Playwright or playwright-stealth not installed. Run: pip install playwright playwright-stealth && playwright install chromium")
            raise
    
    async def _close_browser(self):
        """Close browser resources."""
        if self._context:
            # Save storage state for next run
            try:
                await self._context.storage_state(path=self.storage_state_file)
                log.info(f"Saved Yad2 browser state to {self.storage_state_file}")
            except Exception as e:
                log.warning(f"Could not save storage state: {e}")
            
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
    
    async def _scrape_with_browser(self, on_listing_scraped: Optional[callable] = None) -> List[Listing]:
        """Scrape listings using browser automation."""
        listings = []
        page = await self._context.new_page()
        
        try:
            for page_num in range(1, self.max_pages + 1):
                try:
                    if page_num > 1:
                        await self.anti_detection.human_like_delay(3, 7)
                    
                    params = self._build_url_params(page_num)
                    url = self._build_full_url(params)
                    
                    log.debug(f"Navigating to Yad2 page {page_num}/{self.max_pages}", params=params)
                    
                    # Navigate to page
                    await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    await self.anti_detection.human_like_delay(3, 5)
                    
                    # Check for CAPTCHA
                    if await self._detect_captcha(page):
                        log.warning("CAPTCHA detected on Yad2! Waiting for user to solve...")
                        # Wait longer for manual CAPTCHA solving
                        await asyncio.sleep(30)
                        
                        # Check if still on CAPTCHA page
                        if await self._detect_captcha(page):
                            log.error("[Yad2] CAPTCHA still present after 30s. Stopping Yad2 scrape.")
                            break
                        else:
                            log.info("CAPTCHA appears to be solved, continuing...")
                    
                    # Random human-like behavior
                    if random.random() < 0.3:
                        await self.anti_detection.random_mouse_movement(page)
                    
                    # Wait for listings to load
                    await page.wait_for_timeout(2000)
                    
                    # Extract listings from page
                    page_listings = await self._extract_listings_from_page(page)
                    
                    if not page_listings:
                        log.debug(f"No listings found on page {page_num}")
                        break
                    
                    log.debug(f"Found {len(page_listings)} listings on page {page_num}")
                    
                    for listing in page_listings:
                        listings.append(listing)
                        if on_listing_scraped:
                            await on_listing_scraped(listing)
                        if len(listings) >= self.max_listings:
                            break
                            
                    if len(listings) >= self.max_listings:
                        log.debug(f"Reached max listings limit ({self.max_listings})")
                        break
                    
                    # Random scroll behavior
                    if random.random() < 0.4:
                        await self.anti_detection.random_scroll_behavior(page)
                
                except Exception as e:
                    log.warning(f"Error on page {page_num}: {e}")
                    break
        
        finally:
            await page.close()
        
        return listings[:self.max_listings]
    
    def _build_full_url(self, params: Dict[str, Any]) -> str:
        """Build full URL with query parameters."""
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.RENT_URL}?{param_str}"
    
    async def _detect_captcha(self, page) -> bool:
        """Detect if Cloudflare CAPTCHA or challenge page is present."""
        try:
            # Check page title
            title = await page.title()
            if 'captcha' in title.lower() or 'challenge' in title.lower():
                return True
            
            # Check for Cloudflare challenge elements
            cloudflare_selectors = [
                '#challenge-form',
                '.cf-challenge-running',
                '#cf-wrapper',
                'iframe[src*="challenges.cloudflare.com"]',
            ]
            
            for selector in cloudflare_selectors:
                element = await page.query_selector(selector)
                if element:
                    log.info(f"Detected CAPTCHA element: {selector}")
                    return True
            
            # Check page content
            content = await page.content()
            if 'cloudflare' in content.lower() and 'challenge' in content.lower():
                return True
            
            return False
            
        except Exception as e:
            log.debug(f"Error detecting CAPTCHA: {e}")
            return False
    
    async def _extract_listings_from_page(self, page) -> List[Listing]:
        """Extract listings from the current page."""
        listings = []
        
        try:
            # Get page HTML
            html = await page.content()
            
            # Extract __NEXT_DATA__ JSON (same as HTTP scraper)
            match = re.search(
                r'<script[^>]*id="__NEXT_DATA__"[^>]*>([^<]+)</script>',
                html,
                re.IGNORECASE
            )
            
            if not match:
                log.debug("No __NEXT_DATA__ found in page HTML")
                return []
            
            next_data = json.loads(match.group(1))
            
            # Navigate to listing data
            props = next_data.get("props", {})
            page_props = props.get("pageProps", {})
            dehydrated = page_props.get("dehydratedState", {})
            queries = dehydrated.get("queries", [])
            
            all_items = []
            
            # Extract listings from queries
            for query in queries:
                state = query.get("state", {})
                data = state.get("data", {})
                
                if not isinstance(data, dict):
                    continue
                
                # Yad2 stores listings in different arrays
                for key in ["private", "commercial", "feed_items", "items"]:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        valid_items = [
                            item for item in items 
                            if isinstance(item, dict) and self._is_valid_listing(item)
                        ]
                        if valid_items:
                            log.debug(f"Found {len(valid_items)} items in '{key}'")
                            all_items.extend(valid_items)
            
            # Parse items into Listing objects
            for item in all_items:
                listing = self._parse_listing_item(item)
                if listing:
                    listings.append(listing)
        
        except Exception as e:
            log.warning(f"Error extracting listings from page: {e}")
        
        return listings
    
    def _is_valid_listing(self, item: dict) -> bool:
        """Check if item is a valid rental listing."""
        # Must have token (listing ID)
        if not item.get("token"):
            return False
        
        # Skip ads/banners
        ad_type = item.get("adType", "").lower()
        if ad_type in ["banner", "promotion"]:
            return False
        
        return True
    
    def _parse_listing_item(self, item: dict) -> Optional[Listing]:
        """Parse a Yad2 listing item into our Listing model."""
        try:
            # Extract token (listing ID)
            token = item.get("token")
            if not token:
                log.debug("Skipping item: Missing token/ID")
                return None
            
            # Build URL
            url = f"{self.BASE_URL}/realestate/item/{token}"
            
            # Extract address parts
            address = item.get("address", {})
            city = address.get("city", {}).get("text", "")
            neighborhood = address.get("neighborhood", {}).get("text", "")
            street = address.get("street", {}).get("text", "")
            house_num = address.get("house", {}).get("number", "")
            floor = address.get("house", {}).get("floor")
            
            # Build location string
            location_parts = []
            if street:
                if house_num:
                    location_parts.append(f"{street} {house_num}")
                else:
                    location_parts.append(street)
            if neighborhood:
                location_parts.append(neighborhood)
            if city:
                location_parts.append(city)
            location = ", ".join(location_parts)
            
            # Extract price
            price = item.get("price")
            if isinstance(price, str):
                price = int(re.sub(r'[^\d]', '', price)) if price else None
            
            # Extract rooms
            additional = item.get("additionalDetails", {})
            rooms = additional.get("roomsCount")
            bedrooms = int(rooms) if rooms else None
            
            # Extract property type
            property_type = additional.get("property", {}).get("text", "דירה")
            
            # Extract square meters
            sqm = additional.get("squareMeter")
            parsed_size = None
            if sqm:
                try:
                    parsed_size = int(float(sqm))
                except (ValueError, TypeError):
                    pass
            
            # Extract images
            metadata = item.get("metaData", {})
            images = metadata.get("images", [])
            if not images and metadata.get("coverImage"):
                images = [metadata["coverImage"]]
            
            # Build title
            title_parts = [property_type]
            if rooms:
                title_parts.append(f"{rooms} חדרים")
            if neighborhood:
                title_parts.append(f"ב{neighborhood}")
            title = " ".join(title_parts)
            
            # Build description / raw text
            raw_parts = [title, location]
            if price:
                raw_parts.append(f'{price:,} ש"ח')
            if sqm:
                raw_parts.append(f'{sqm} מ"ר')
            if floor is not None:
                if floor == 0:
                    raw_parts.append("קומת קרקע")
                else:
                    raw_parts.append(f"קומה {floor}")
            
            # Add property condition
            property_condition_id = additional.get("propertyCondition", {}).get("id")
            condition_map = {
                1: "חדש מקבלן",
                2: "משופץ",
                3: "במצב שמור",
                4: "דרוש שיפוץ",
            }
            if property_condition_id and property_condition_id in condition_map:
                raw_parts.append(condition_map[property_condition_id])
            
            # Add ad type
            ad_type = item.get("adType", "")
            if ad_type == "private":
                raw_parts.append("פרטי")
            elif ad_type == "commercial":
                raw_parts.append("מתווך/סוכנות")
            
            # Add GPS coordinates
            coords = address.get("coords", {})
            lat = coords.get("lat")
            lon = coords.get("lon")
            if lat and lon:
                raw_parts.append(f"קואורדינטות: {lat},{lon}")
            
            # Add tags
            tags = item.get("tags", [])
            tag_names = [tag.get("name") for tag in tags if tag.get("name")]
            if tag_names:
                raw_parts.append("מאפיינים: " + ", ".join(tag_names))
            
            raw_text = "\n".join(raw_parts)
            
            # Extract date from image URLs
            posted_at = extract_yad2_posted_date(images)
            
            # Filter out old listings (older than 1 day)
            if posted_at:
                age = datetime.now() - posted_at
                if age.days >= 1:
                    log.debug(f"Skipping old listing: {title} (age: {age.days} days, posted: {posted_at})")
                    return None
            
            log.debug(f"Successfully parsed listing: {title} ({url})")
            from utils.hebrew_utils import is_sublet_text
            is_sublet = is_sublet_text(raw_text)
            
            return Listing(
                id=self.generate_listing_id(url),
                source=self.source_name,
                url=url,
                title=title[:200],
                description=raw_text,
                location=location,
                raw_text=raw_text,
                price=price,
                bedrooms=bedrooms,
                size=parsed_size,
                images=images[:5],
                posted_at=posted_at,
                scraped_at=datetime.now(),
                is_sublet=is_sublet,
            )
            
        except Exception as e:
            log.debug(f"Failed to parse listing: {e}")
            return None
    
    def parse_listing(self, raw_data: dict) -> Optional[Listing]:
        """Parse raw data to Listing (compatibility method)."""
        return self._parse_listing_item(raw_data)
