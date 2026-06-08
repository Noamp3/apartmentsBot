# scrapers/yad2_scraper.py
"""Yad2 scraper for apartment listings using direct HTTP requests.

This implementation uses best practices for scraping Next.js sites:
1. Fetches HTML page and extracts __NEXT_DATA__ JSON (server-rendered data)
2. Parses the structured listing data from React Query dehydrated state
3. Uses httpx with HTTP/2 for efficient requests
4. Implements anti-detection measures (realistic headers, delays)
"""

import asyncio
import random
import json
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import httpx

from scrapers.base_scraper import BaseScraper
from scrapers.anti_detection import AntiDetectionModule
from models.listing import Listing
from utils.logger import Loggers
from utils.hebrew_utils import extract_yad2_posted_date

log = Loggers.scraper()


class Yad2Scraper(BaseScraper):
    """Scrapes apartment listings from Yad2.co.il.
    
    Uses direct HTTP requests to fetch Next.js pages and extracts
    listing data from the __NEXT_DATA__ script tag.
    """
    
    BASE_URL = "https://www.yad2.co.il"
    RENT_URL = "https://www.yad2.co.il/realestate/rent"
    
    # Anti-detection settings
    MIN_DELAY_BETWEEN_PAGES = 2.0
    MAX_DELAY_BETWEEN_PAGES = 5.0
    
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
        min_delay: float = None,
        max_delay: float = None
    ):
        self.city_id = city_id
        self.min_price = min_price
        self.max_price = max_price
        self.min_rooms = min_rooms
        self.max_rooms = max_rooms
        self.max_listings = max_listings
        self.max_pages = max_pages
        
        self.anti_detection = anti_detection or AntiDetectionModule()
        self.min_delay = min_delay or self.MIN_DELAY_BETWEEN_PAGES
        self.max_delay = max_delay or self.MAX_DELAY_BETWEEN_PAGES
    
    @property
    def source_name(self) -> str:
        return "yad2"
    
    async def _random_delay(self, min_sec: float = None, max_sec: float = None):
        """Apply a random delay to mimic human behavior."""
        min_sec = min_sec or self.min_delay
        max_sec = max_sec or self.max_delay
        delay = random.uniform(min_sec, max_sec)
        log.debug(f"Anti-detection: waiting {delay:.1f}s before next request")
        await asyncio.sleep(delay)
    
    def _build_params(self, page: int = 1) -> Dict[str, Any]:
        """Build query parameters for Yad2.
        
        Uses the parameter format that Yad2 expects to avoid redirects:
        - topArea, area for location hierarchy
        - minPrice/maxPrice instead of price=-X
        - minRooms/maxRooms instead of rooms=X-Y
        """
        params = {
            "page": page,
            "topArea": 2,  # מרכז (Center region)
            "area": 1,     # אזור תל אביב יפו
        }
        
        if self.city_id:
            params["city"] = self.city_id
        
        # Price filters - use minPrice/maxPrice format
        if self.min_price is not None:
            params["minPrice"] = self.min_price
        if self.max_price is not None:
            params["maxPrice"] = self.max_price
        
        # Room filters - use minRooms/maxRooms format
        if self.min_rooms is not None:
            params["minRooms"] = int(self.min_rooms)
        if self.max_rooms is not None:
            params["maxRooms"] = int(self.max_rooms)
        
        return params
    
    async def scrape(self) -> List[Listing]:
        """Scrape listings from Yad2."""
        log.debug(f"Starting Yad2 scrape. City={self.city_id}, Price={self.min_price}-{self.max_price}")
        listings = []
        
        try:
            log.info("Scraping Yad2 via HTTP (Next.js __NEXT_DATA__)")
            listings = await self._scrape_html_pages()
        except Exception as e:
            log.error(f"Yad2 scrape failed: {e}", exc_info=True)
        
        log.info(f"Yad2 scrape complete", total_listings=len(listings))
        return listings
    
    async def _scrape_html_pages(self) -> List[Listing]:
        """Scrape by fetching HTML pages and extracting __NEXT_DATA__."""
        listings = []
        
        headers = self.anti_detection.get_browser_headers()
        headers.update({
            "Referer": "https://www.yad2.co.il/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        })
        
        # Try HTTP/2 first, fall back to HTTP/1.1 if h2 not installed
        try:
            import h2  # noqa: F401
            use_http2 = True
        except ImportError:
            use_http2 = False
            log.debug("HTTP/2 not available, using HTTP/1.1 (install httpx[http2] for HTTP/2)")
        
        async with httpx.AsyncClient(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
            http2=use_http2,
        ) as client:
            for page in range(1, self.max_pages + 1):
                try:
                    if page > 1:
                        await self._random_delay()
                    
                    params = self._build_params(page)
                    log.debug(f"Fetching Yad2 page {page}/{self.max_pages}", params=params)
                    
                    response = await client.get(self.RENT_URL, params=params)
                    
                    # Check for CAPTCHA/challenge page
                    if self._detect_captcha(response.text, response.status_code):
                        log.error("CAPTCHA detected on Yad2! Consider using YAD2_USE_PLAYWRIGHT=True in config.")
                        break
                    
                    if response.status_code != 200:
                        log.warning(f"Yad2 returned status {response.status_code}")
                        break
                    
                    # Extract listings from __NEXT_DATA__
                    page_listings = self._extract_listings_from_html(response.text)
                    
                    if not page_listings:
                        log.debug(f"No listings found on page {page}")
                        break
                    
                    log.debug(f"Found {len(page_listings)} listings on page {page}")
                    
                    for item in page_listings:
                        listing = self._parse_listing_item(item)
                        if listing:
                            listings.append(listing)
                            if len(listings) >= self.max_listings:
                                break
                    
                    if len(listings) >= self.max_listings:
                        log.debug(f"Reached max listings limit ({self.max_listings})")
                        break
                        
                except httpx.HTTPError as e:
                    log.warning(f"HTTP error on page {page}: {e}")
                    await self._random_delay(5.0, 10.0)
                    break
        
        return listings[:self.max_listings]
    
    def _extract_listings_from_html(self, html: str) -> List[dict]:
        """Extract listing data from __NEXT_DATA__ script tag."""
        try:
            # Find __NEXT_DATA__ JSON
            match = re.search(
                r'<script[^>]*id="__NEXT_DATA__"[^>]*>([^<]+)</script>',
                html,
                re.IGNORECASE
            )
            
            if not match:
                log.debug("No __NEXT_DATA__ found in HTML")
                return []
            
            next_data = json.loads(match.group(1))
            
            # Navigate: props -> pageProps -> dehydratedState -> queries
            props = next_data.get("props", {})
            page_props = props.get("pageProps", {})
            dehydrated = page_props.get("dehydratedState", {})
            queries = dehydrated.get("queries", [])
            
            all_listings = []
            
            # Look for feed data in queries
            for query in queries:
                state = query.get("state", {})
                data = state.get("data", {})
                
                if not isinstance(data, dict):
                    continue
                
                # Yad2 stores listings in 'private' and 'commercial' arrays
                for key in ["private", "commercial", "feed_items", "items"]:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        valid_items = [
                            item for item in items 
                            if isinstance(item, dict) and self._is_valid_listing(item)
                        ]
                        if valid_items:
                            log.debug(f"Found {len(valid_items)} items in '{key}'")
                            all_listings.extend(valid_items)
            
            return all_listings
                
        except json.JSONDecodeError as e:
            log.warning(f"JSON decode error in __NEXT_DATA__: {e}")
        except Exception as e:
            log.warning(f"Error extracting listings: {e}")
        
        return []
    
    def _detect_captcha(self, html: str, status_code: int) -> bool:
        """Detect if Cloudflare CAPTCHA or challenge page is present.
        
        Returns:
            True if CAPTCHA/challenge is detected, False otherwise
        """
        # Check for Cloudflare challenge indicators
        captcha_indicators = [
            'cloudflare',
            'challenge-form',
            'cf-challenge',
            'just a moment',
            'checking your browser',
            'enable javascript',
        ]
        
        html_lower = html.lower()
        
        # Check for common CAPTCHA indicators
        for indicator in captcha_indicators:
            if indicator in html_lower:
                log.warning(f"CAPTCHA indicator found: '{indicator}'")
                return True
        
        # Check for non-200 status that might indicate blocking
        if status_code in [403, 429, 503]:
            log.warning(f"Suspicious status code: {status_code}")
            return True
        
        # Check if the response is suspiciously small (challenge pages are usually small)
        if len(html) < 5000:
            log.debug("Response HTML is suspiciously small, might be a challenge page")
            # Don't return True just for this, as it could be a legitimate empty page
        
        return False
    
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
            
            # Build description / raw text for AI processing
            # Include ALL available data since detail pages are bot-protected
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
            
            # Add property condition if available
            property_condition_id = additional.get("propertyCondition", {}).get("id")
            condition_map = {
                1: "חדש מקבלן",
                2: "משופץ",
                3: "במצב שמור",
                4: "דרוש שיפוץ",
            }
            if property_condition_id and property_condition_id in condition_map:
                raw_parts.append(condition_map[property_condition_id])
            
            # Add ad type (private vs commercial/agency)
            ad_type = item.get("adType", "")
            if ad_type == "private":
                raw_parts.append("פרטי")
            elif ad_type == "commercial":
                raw_parts.append("מתווך/סוכנות")
            
            # Add GPS coordinates if available (useful for distance calculations)
            coords = address.get("coords", {})
            lat = coords.get("lat")
            lon = coords.get("lon")
            if lat and lon:
                raw_parts.append(f"קואורדינטות: {lat},{lon}")
            
            # Add ALL tags (features like ממ"ד, parking, AC, etc.)
            tags = item.get("tags", [])
            tag_names = [tag.get("name") for tag in tags if tag.get("name")]
            if tag_names:
                raw_parts.append("מאפיינים: " + ", ".join(tag_names))
            
            raw_text = "\n".join(raw_parts)
            
            # Try to extract date from image URLs
            # URL format: https://img.yad2.co.il/Pic/YYYYMM/DD/...
            posted_at = extract_yad2_posted_date(images)
            
            # Filter out old listings (older than 1 day)
            if posted_at:
                age = datetime.now() - posted_at
                if age.days >= 1:
                    log.debug(f"Skipping old listing: {title} (age: {age.days} days, posted: {posted_at})")
                    return None
            
            log.debug(f"Successfully parsed listing: {title} ({url})")
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
                images=images[:5],
                posted_at=posted_at,  # Set the extracted date
                scraped_at=datetime.now(),
            )
            
        except Exception as e:
            log.debug(f"Failed to parse listing: {e}")
            return None
    
    def parse_listing(self, raw_data: dict) -> Optional[Listing]:
        """Parse raw data to Listing (compatibility method)."""
        return self._parse_listing_item(raw_data)
