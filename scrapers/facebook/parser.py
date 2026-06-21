# scrapers/facebook/parser.py
"""Handles parsing of HTML and Playwright elements to extract post details."""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from bs4 import BeautifulSoup
from config import settings
from utils.logger import Loggers
from utils.hebrew_utils import extract_price, extract_contact_info, parse_relative_date
from utils.israeli_locations import get_location_db

log = Loggers.scraper()

class FacebookPostParser:
    """Parses Facebook group posts to extract structure metadata, text, price, author, date, and URL."""
    
    def __init__(self, healer, anti_detection):
        self.healer = healer
        self.anti_detection = anti_detection
        self._author_failures = 0
        self._url_failures = 0
        self._date_failures = 0

    def clean_text(self, text: str) -> str:
        """Clean up extracted text by removing common UI artifacts and double spaces."""
        artifacts = [
            "See more", "ראה עוד", "See less", "ראה פחות",
            "Like", "Comment", "Share", "לייק", "תגובה", "שיתוף",
            "Translate", "תרגם", "Write a comment...", "כתוב תגובה...",
        ]
        clean = text
        for artifact in artifacts:
            clean = clean.replace(artifact, "")
        
        while "  " in clean:
            clean = clean.replace("  ", " ")
        
        return clean.strip()

    def extract_author(self, soup: BeautifulSoup) -> str:
        """Extract the post author name from BeautifulSoup."""
        author_elem = soup.find(['strong', 'h2', 'h3'])
        if author_elem:
            author = author_elem.get_text(strip=True)
            if author and len(author) < 50:
                return author
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            if '/user/' in href or '/profile.php' in href:
                author = link.get_text(strip=True)
                if author and len(author) < 50:
                    return author
        
        return "Unknown"

    async def expand_post(self, post_element):
        """Click ALL 'See more' buttons to fully expand truncated content."""
        see_more_selector = self.healer.get_selector("see_more")
        see_more_selectors = [s.strip() for s in see_more_selector.split(',') if s.strip()]
        
        clicked_any = False
        for selector in see_more_selectors:
            try:
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
            await asyncio.sleep(0.5)
            log.debug("Expanded 'See more' content")

    async def extract_full_text(self, post_element, soup: BeautifulSoup) -> str:
        """Extract the full post text content."""
        try:
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
                full_text = max(texts, key=len)
                return self.clean_text(full_text)
        except:
            pass
        
        raw_text = soup.get_text(separator=' ', strip=True)
        return self.clean_text(raw_text)

    async def extract_post_url_immediate(self, page, post_element, soup: BeautifulSoup) -> str:
        """Extract permalink URL immediately while element is valid."""
        post_url_selector = self.healer.get_selector("post_url")
        
        try:
            links = await post_element.query_selector_all(post_url_selector)
            for link in links:
                href = await link.get_attribute('href')
                if href:
                    self._url_failures = 0
                    if href.startswith('/'):
                        return f"https://www.facebook.com{href.split('?')[0]}"
                    return href.split('?')[0]
        except:
            pass
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            if any(p in href for p in ['/posts/', '/permalink/', 'story_fbid', 'fbid=', '/groups/']):
                if not any(x in href for x in ['/members', '/about', '/media', '/join', '/user/']):
                    self._url_failures = 0
                    if href.startswith('/'):
                        if '?' in href:
                             base = href.split('?')[0]
                             return f"https://www.facebook.com{base}"
                        return f"https://www.facebook.com{href}"
                    return href.split('?')[0] if '?' in href else href
        
        if settings.FACEBOOK_SELF_HEALING_ENABLED:
            self._url_failures += 1
            if self._url_failures >= 3:
                log.warning("Detected multiple URL extraction failures. Attempting attribute self-healing for 'post_url'...")
                healed_selector = await self.healer.heal_attribute(page, post_element, "post_url", post_url_selector)
                if healed_selector:
                    try:
                        link = await post_element.query_selector(healed_selector)
                        if link:
                            href = await link.get_attribute('href')
                            if href:
                                self._url_failures = 0
                                if href.startswith('/'):
                                    return f"https://www.facebook.com{href.split('?')[0]}"
                                return href.split('?')[0]
                    except Exception as e:
                        log.debug(f"Error extracting URL after healing: {e}")
        
        return ""

    async def extract_post_date(self, page, post_element, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract post date from timestamp element."""
        now = datetime.now()
        
        try:
            post_date_selector = self.healer.get_selector("post_date")
            timestamp_selectors = [s.strip() for s in post_date_selector.split(',') if s.strip()]
            timestamp_text = ""
            
            for selector in timestamp_selectors:
                try:
                    elements = await post_element.query_selector_all(selector)
                    for elem in elements:
                        text_options = []
                        inner_t = await elem.inner_text()
                        if inner_t:
                            text_options.append(inner_t.strip())
                        aria_l = await elem.get_attribute("aria-label")
                        if aria_l:
                            text_options.append(aria_l.strip())
                        title_attr = await elem.get_attribute("title")
                        if title_attr:
                            text_options.append(title_attr.strip())
                            
                        if not inner_t:
                            nested_abbr = await elem.query_selector("abbr")
                            if nested_abbr:
                                abbr_t = await nested_abbr.inner_text()
                                if abbr_t:
                                    text_options.append(abbr_t.strip())
                                abbr_title = await nested_abbr.get_attribute("title")
                                if abbr_title:
                                    text_options.append(abbr_title.strip())
                        
                        found_text = None
                        for text in text_options:
                            text = re.sub(r'^[\u200e\u200f\u202a-\u202e\u2066-\u2069\s]+', '', text)
                            timestamp_patterns = [
                                r'^(?:about\s+)?\d+h$',
                                r'^(?:about\s+)?\d+\s*h$',
                                r'^(?:about\s+)?\d+m$',
                                r'^(?:about\s+)?\d+\s*m$',
                                r'^(?:about\s+)?\d+d$',
                                r'^(?:about\s+)?\d+\s*d$',
                                r'^(?:about\s+)?\d+w$',
                                r'^(?:לפני\s+)?\d+\s*שעות',
                                r'^(?:לפני\s+)?\d+\s*שעה',
                                r'^(?:לפני\s+)?\d+\s*דקות',
                                r'^(?:לפני\s+)?\d+\s*דקה',
                                r'^(?:לפני\s+)?\d+\s*ימים',
                                r'^(?:לפני\s+)?\d+\s*יום',
                                r'^(?:לפני\s+)?שעה$',
                                r'^(?:לפני\s+)?יום$',
                                r'^אתמול',
                                r'^yesterday',
                                r'^just\s*now',
                                r'^עכשיו',
                                r'^(?:about\s+)?\d+\s*hrs?',
                                r'^(?:about\s+)?\d+\s*mins?',
                            ]
                            
                            text_lower = text.lower()
                            if any(re.match(p, text_lower) for p in timestamp_patterns):
                                found_text = text
                                log.debug(f"Found timestamp text: '{text}'")
                                break
                                
                            if re.match(r'^\d{1,2}[./]\d{1,2}', text) or re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ינו|פבר|מרץ|אפר|מאי|יונ|יול|אוג|ספט|אוק|נוב|דצמ)', text_lower):
                                found_text = text
                                break
                                
                        if found_text:
                            timestamp_text = found_text
                            break
                except:
                    continue
                if timestamp_text:
                    break
                    
            if not timestamp_text and settings.FACEBOOK_SELF_HEALING_ENABLED:
                self._date_failures += 1
                if self._date_failures >= 3:
                    log.warning("Detected 3 consecutive date extraction failures. Triggering self-healing for 'post_date' selector...")
                    healed_selector = await self.healer.heal_attribute(page, post_element, "post_date", post_date_selector)
                    if healed_selector:
                        try:
                            elem = await post_element.query_selector(healed_selector)
                            if elem:
                                text = await elem.inner_text()
                                timestamp_text = text.strip()
                                self._date_failures = 0
                        except Exception as e:
                            log.debug(f"Error extracting date after healing: {e}")
            else:
                self._date_failures = 0
                
            if not timestamp_text:
                return None
            
            return parse_relative_date(timestamp_text, now)
            
        except Exception as e:
            log.debug(f"Error extracting post date: {e}")
            return None

    async def find_posts(self, page) -> List:
        """Find post elements using multiple selector strategies."""
        await page.evaluate("window.scrollBy(0, 300)")
        await self.anti_detection.human_like_delay(1, 2)
        
        post_selector = self.healer.get_selector("post_container")
        post_selectors = [
            post_selector,
            'div[role="article"]',
            'div[data-pagelet^="FeedUnit"]',
            'div.x1yztbdb.x1n2onr6.xh8yej3.x1ja2u2z',
            'div[data-ad-preview="message"]',
            'div.x1lliihq',
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

    async def extract_post_data_immediate(self, page, post_element) -> Optional[dict]:
        """Extract post data immediately while element is valid."""
        try:
            await self.expand_post(post_element)
            full_text = await post_element.inner_text()
            
            # Skip sponsored posts / ads immediately
            lines = [line.strip() for line in full_text.split('\n') if line.strip()]
            for line in lines[:10]:
                if line == "ממומן" or line.lower() == "sponsored":
                    log.info("Skipping sponsored post/advertisement")
                    return None
            
            html = await post_element.inner_html()
            soup = BeautifulSoup(html, 'html.parser')
            
            text = self.clean_text(full_text)
            
            if "להחלפה" in text:
                log.debug("Skipping listing matching 'להחלפה'")
                return None
            
            searching_patterns = [
                "מחפש דירה", "מחפשת דירה", "מחפשים דירה",
                "מחפש חדר", "מחפשת חדר", "מחפשים חדר",
                "מחפש סאבלט", "מחפשת סאבלט",
                "מחפש שותף", "מחפשת שותפה", "מחפשים שותפ",
            ]
            if any(pattern in text for pattern in searching_patterns):
                log.debug("Skipping 'searching for apartment' post")
                return None
            
            promo_patterns = [
                "מובילים", "אריזה ואחסנה", "מתחם אחסנה",
                "שירותי הובלה", "הובלות", "אחסון",
                "ריהוט לבית",
            ]
            if any(pattern in text for pattern in promo_patterns):
                log.debug("Skipping promotional/admin post")
                return None
            
            if len(text.strip()) < 30:
                log.debug("Skipping empty/broken post")
                return None
            
            author = self.extract_author(soup)
            if (not author or author == "Unknown") and settings.FACEBOOK_SELF_HEALING_ENABLED:
                self._author_failures += 1
                if self._author_failures >= 3:
                    log.warning("Detected multiple author extraction failures. Attempting attribute self-healing for 'author'...")
                    post_author_selector = self.healer.get_selector("author")
                    healed_selector = await self.healer.heal_attribute(page, post_element, "author", post_author_selector)
                    if healed_selector:
                        try:
                            elem = await post_element.query_selector(healed_selector)
                            if elem:
                                author_text = await elem.inner_text()
                                if author_text.strip():
                                    author = author_text.strip()
                                    self._author_failures = 0
                        except Exception as e:
                            log.debug(f"Error extracting author after healing: {e}")
            else:
                self._author_failures = 0
            
            price = extract_price(text)
            contact_info = extract_contact_info(text)
            phone = contact_info.get('phone')
            
            location_db = get_location_db()
            location_info = location_db.normalize_location(text)
            neighborhood = location_info.get('neighborhood') or ''
            city = location_info.get('city') or ''
            
            url = await self.extract_post_url_immediate(page, post_element, soup)
            posted_at = await self.extract_post_date(page, post_element, soup)
            
            # Generate listing_id for screenshot storage, matching the scraper ID logic
            import hashlib
            id_seed = url if url and len(url) > 30 else f"facebook_{hashlib.md5(text[:200].encode()).hexdigest()}"
            listing_id = hashlib.md5(id_seed.encode()).hexdigest()
            
            # Capture screenshots using our utility functions
            from utils.screenshot_utils import save_post_screenshot, save_gallery_screenshots
            post_screenshot = await save_post_screenshot(post_element, listing_id)
            gallery_screenshots = await save_gallery_screenshots(post_element, listing_id)
            
            return {
                'text': text,
                'url': url,
                'images': [],
                'screenshots': {
                    'post_screenshot': post_screenshot,
                    'gallery_screenshots': gallery_screenshots
                },
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

    async def extract_post_data(self, page, post_element) -> Optional[dict]:
        """Extract metadata from a single post element."""
        try:
            await self.expand_post(post_element)
            
            html = await post_element.inner_html()
            soup = BeautifulSoup(html, 'html.parser')
            
            text = await self.extract_full_text(post_element, soup)
            author = self.extract_author(soup)
            price = extract_price(text)
            url = await self.extract_post_url(page, post_element, soup)
            
            return {
                'text': text,
                'url': url,
                'images': [],
                'screenshots': {},
                'price': price,
                'author': author,
            }
        except Exception as e:
            log.error(f"Extraction error: {e}")
            return None

    async def extract_post_url(self, page, post_element, soup: BeautifulSoup) -> str:
        """Extract the permalink URL for a post."""
        timestamp_selectors = [
            'a[href*="/posts/"]',
            'a[href*="/permalink/"]',
            'a[href*="story_fbid"]',
            'span.x4k7w5x a',
            'a[role="link"][tabindex="0"]',
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
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            if any(p in href for p in ['/posts/', '/permalink/', 'story_fbid']):
                if not any(x in href for x in ['/members', '/about', '/media', '/join']):
                    if href.startswith('/'):
                        return f"https://www.facebook.com{href}"
                    return href.split('?')[0] if '?' in href else href
        
        try:
            all_links = await post_element.query_selector_all('a')
            for link in all_links:
                try:
                    text = await link.inner_text()
                    href = await link.get_attribute('href')
                    if href and len(text) < 15 and ('facebook.com' in href or href.startswith('/')):
                        if '/groups/' in href and '/posts/' not in href and '/permalink/' not in href:
                            continue
                        if '/posts/' in href or '/permalink/' in href or 'story' in href:
                            if href.startswith('/'):
                                return f"https://www.facebook.com{href}"
                            return href.split('?')[0] if '?' in href else href
                except:
                    continue
        except:
            pass
        
        return ""
