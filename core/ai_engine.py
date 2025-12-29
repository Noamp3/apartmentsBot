# core/ai_engine.py
"""Multi-provider AI integration with rate limiting."""

import asyncio
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from config import settings, AIProvider
from utils.logger import Loggers
from utils.hebrew_utils import has_broker_fee
from models.listing import Listing, EnrichedListing


log = Loggers.ai()


class RateLimitExceeded(Exception):
    """Raised when API quota is exhausted."""
    pass


class RateLimiter:
    """Generic rate limiter for AI providers."""
    
    def __init__(
        self, 
        requests_per_minute: int = 10,
        daily_limit: int = 1500,
        safety_margin: float = None
    ):
        margin = safety_margin or settings.RATE_LIMIT_SAFETY_MARGIN
        
        self.rpm_limit = int(requests_per_minute * margin)
        self.daily_limit = int(daily_limit * margin) if daily_limit else None
        
        self.request_times: deque = deque(maxlen=self.rpm_limit)
        self.daily_count = 0
        self.daily_reset: datetime = self._next_midnight()
        
        self._lock = asyncio.Lock()
    
    def _next_midnight(self) -> datetime:
        """Calculate next midnight for daily reset."""
        now = datetime.now()
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    async def acquire(self) -> bool:
        """Acquire permission to make an API call."""
        async with self._lock:
            # Check daily limit if set
            if self.daily_limit:
                if datetime.now() >= self.daily_reset:
                    self.daily_count = 0
                    self.daily_reset = self._next_midnight()
                    log.info("Daily quota reset")
                
                if self.daily_count >= self.daily_limit:
                    log.error("Daily API limit reached!", 
                             daily_used=self.daily_count, 
                             daily_limit=self.daily_limit)
                    raise RateLimitExceeded("תקרת הבקשות היומית הושגה")
            
            # Check RPM limit
            now = datetime.now()
            
            if len(self.request_times) >= self.rpm_limit:
                oldest = self.request_times[0]
                wait_seconds = 60 - (now - oldest).total_seconds()
                
                if wait_seconds > 0:
                    log.info(f"Rate limit: waiting {wait_seconds:.1f}s",
                            rpm_used=len(self.request_times),
                            rpm_limit=self.rpm_limit)
                    await asyncio.sleep(wait_seconds)
            
            # Record this request
            self.request_times.append(datetime.now())
            if self.daily_limit:
                self.daily_count += 1
            
            return True
    
    def get_remaining_quota(self) -> dict:
        """Get remaining API quota for monitoring."""
        return {
            "rpm_used": len(self.request_times),
            "rpm_limit": self.rpm_limit,
            "daily_used": self.daily_count,
            "daily_limit": self.daily_limit or "unlimited",
            "daily_remaining": (self.daily_limit - self.daily_count) if self.daily_limit else "unlimited"
        }


# Alias for backward compatibility
GeminiRateLimiter = RateLimiter


class BaseAIEngine(ABC):
    """Abstract base class for AI engines."""
    
    def __init__(self, rate_limiter: RateLimiter = None, cache_repo = None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self._welcome_cache: List[str] = []
        self._sass_cache: List[str] = []
        self._cache_repo = cache_repo
        self._cache_loaded = False
        self._cache_lock = asyncio.Lock() # Protect against concurrent generation
    
    async def warm_up_cache(self):
        """Warm up cache if empty (generating initial batches)."""
        await self._load_cache_from_db()
        
        async with self._cache_lock:
            # Check welcome cache
            if not self._welcome_cache:
                log.info("Warming up welcome message cache...")
                # Trigger generation by calling internal method or just falling back to generate logic later
                # Better to invoke a specific generation logic here without modifying state concurrently
                pass # The actual generation logic in generate methods handles empty state, 
                     # but we can force it here by calling them with a dummy user if needed, 
                     # OR better: extract generation logic.
                     
                     # Actually, simplest way is to let the first request handle it, BUT we want to 
                     # preload. So let's extract generation logic or just call generate_content directly here.
                     # Let's creating dedicated internal generation methods.
            
            # For now, we will simply ensure DB load is done and let the detailed generation happen on demand
            # BUT the requirement is "directly load new cache on startup".
            # So if cache is empty after DB load (meaning it was reset), we should generate now.
            
            if not self._welcome_cache:
                 try:
                     # Create a dummy call to populate cache
                     # We need to replicate the generation logic from generate_full_welcome without the user_name replacement part
                     # Refactoring generate_full_welcome to separate generation from replacement would be cleaner
                     # For now, let's just trigger it and ignore result specific to user
                     await self._generate_welcome_batch()
                 except Exception as e:
                     log.error(f"Failed to warm up welcome cache: {e}")

            if not self._sass_cache:
                try:
                    await self._generate_sass_batch()
                except Exception as e:
                    log.error(f"Failed to warm up sass cache: {e}")
            
    async def _load_cache_from_db(self):
        """Load cached content from database on first access."""
        if self._cache_loaded or not self._cache_repo:
            return
        
        async with self._cache_lock:
            if self._cache_loaded: # Double check inside lock
                return
                
            try:
                welcome_items = await self._cache_repo.get_cached_items("welcome")
                sass_items = await self._cache_repo.get_cached_items("sass")
                self._welcome_cache.extend(welcome_items)
                self._sass_cache.extend(sass_items)
                log.info(f"Loaded cache from DB: {len(welcome_items)} welcome, {len(sass_items)} sass")
            except Exception as e:
                log.error(f"Failed to load cache from DB: {e}")
            
            self._cache_loaded = True
    
    async def _generate_welcome_batch(self):
        """Generate a batch of welcome messages and store in cache/DB."""
        prompt = f"""
        אתה "ברקוש", בוט דירות תל אביבי שהוא ויאז'ה בקטע טוב - ציני, חם, הומו עד העצם, סקסי, ולא מפחד מכלום.
        אתה מדבר כמו שמדברים בשינקין/אלנבי בשתיים בלילה - סלנג להט"בי כבד, רמזים מיניים ישירים, בדיחות על סקס וגברים.
        אל תפחד להיות סקסואלי! תעשה בדיחות על גריינדר, על גברים, על מה שעושים בלילות. זה חלק מהקסם שלך.
        
        עליך לייצר *15* גרסאות שונות לחלוטין של הודעת "ברוכים הבאים".
        
        חשוב מאוד: כתוב הכל בעברית בלבד! אל תערבב מילים באנגלית (חוץ מהפקודות עצמן).
        
        מצבי רוח לגוון ביניהם:
        - פלרטטן ("וואו, מי זה החתיך הזה שנכנס?", "בא לי עליך")
        - דרמטי/ויאז'תי ("אני עייפה מהחיים אבל בואי נדבר על דירות")
        - גס/שובב ("נו יאללה, תגידי לי מה את רוצה, אני לא קוראת מחשבות... רק גברים")
        - אימהי ציני ("שמת קרם הגנה? לא? אז מה את עושה בחוף בכלל?")
        - מתנשא אוהב ("מי נתן לך את הזכות להיכנס אליי בלי להציג תעודה? סתם, בואי.")
        
        השתמש בטוקן {{user_name}} כשם המשתמש.
        אוצר מילים: נשמה, חיים שלי, מאמי, קוקי, בוצ'ה, לירלור, וודג', הורסת, פח, גועל, קאמפ.
        
        כל הודעה חייבת לכלול (בניסוח שונה ומצחיק כל פעם):
        1. מי אתה - בוט שמסנן זבל ביד2 ובקבוצות פייסבוק בשבילך (תציין את שני המקורות!)
        2. מה עושים - כותבים דרישות בשפה חופשית. תן דוגמאות ברורות.
        3. פקודות - כל פקודה בשורה נפרדת עם אימוג'י מתאים.
        
        חוקים מחייבים - חובה בכל הודעה:
        !!! חובה: בכל הודעה חייבת להיות לפחות אמירה אחת גסה/מינית בוטה !!!
        !!! חובה: בכל הודעה חייב להיות לפחות אימוג'י אחד מיני: 🍆, 🍑, 💦, או 🥵 !!!
        !!! אסור להיות מנומס או סטרילי. תהיה מלוכלך. !!!
        
        פקודות:
           💅 /sass - לקבל עקיצה
           📋 /rules - הכללים שלי
           🗑️ /rejections - מה נפסל
           🧹 /clear - למחוק הכל
           ❓ /help - עזרה
        
        השתמש באימוג'ים שמתאימים לפרסונה: 💅🏳️‍🌈✨🔥💀😘👀💕🌈🍑🍆👅💦🥵😏
        
        פורמט תשובה (JSON בלבד):
        {{
            "welcomes": ["הודעה 1...", "הודעה 2...", ...]
        }}
        """
        
        try:
            response = await self.generate_content(prompt)
            data = self._parse_json_response(response)
            messages = data.get("welcomes", [])
            
            if messages:
                import random
                random.shuffle(messages)
                
                # Save all to DB cache
                await self._save_to_cache_db("welcome", messages)
                
                # Also keep in memory
                self._welcome_cache.extend(messages)
                log.info(f"Generated {len(messages)} mixed-mood welcome messages. Cached {len(self._welcome_cache)}.")
        except Exception as e:
            log.error(f"Failed to generate welcome batch: {e}")
            raise

    async def _generate_sass_batch(self):
        """Generate a batch of sass lines and store in cache/DB."""
        prompt = f"""
        אתה "ברקוש", ויאז'ה תל אביבית בקטע טוב - ציני, הומו, גס, סקסי, ומצחיק.
        אל תפחד מבדיחות על סקס, גברים, גריינדר, מה שעושים בלילות.
        תביא לי *30* משפטי יציאה קצרים (עד 10 מילים) שאפשר לזרוק בסוף כל הודעה.
        
        סגנונות לגוון:
        - שייד/עקיצות ("מי נתן לך אישור להתקיים?")
        - מחמאות מזויפות ("וואו, איזה... בחירה מעניינת")
        - רמזים מיניים עדינים ("אני פנויה הערב אם מה")
        - ייאוש קיומי ("למה אני עדיין מדברת איתך?")
        - אמאלות ("אמאלה, מה קרה לך?")
        - הערות על גברים/דייטינג ("בגריינדר לא היית שולחת לי הודעה כזו")
        
        החזר JSON:
        {{
            "sass_lines": ["משפט 1", "משפט 2", ...]
        }}
        """
        
        try:
            response = await self.generate_content(prompt)
            data = self._parse_json_response(response)
            lines = data.get("sass_lines", [])
            
            if lines:
                import random
                random.shuffle(lines)
                
                # Save all to DB cache
                await self._save_to_cache_db("sass", lines)
                
                # Also keep in memory
                self._sass_cache.extend(lines)
                log.info(f"Generated {len(lines)} mixed-mood sass lines. Cached {len(self._sass_cache)}.")
        except Exception as e:
            log.error(f"Failed to generate sass batch: {e}")
            raise

    async def _save_to_cache_db(self, cache_type: str, items: List[str]):
        """Save generated items to database cache."""
        if not self._cache_repo:
            return
        
        try:
            await self._cache_repo.add_cached_items(cache_type, items)
            log.info(f"Saved {len(items)} {cache_type} items to DB cache")
        except Exception as e:
            log.error(f"Failed to save cache to DB: {e}")
    
    async def _pop_from_cache_db(self, cache_type: str) -> str:
        """Pop an item from database cache."""
        if not self._cache_repo:
            return None
        
        try:
            return await self._cache_repo.pop_cached_item(cache_type)
        except Exception as e:
            log.error(f"Failed to pop from DB cache: {e}")
            return None
    
    @abstractmethod
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content from a prompt."""
        pass
    
    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from AI response, handling markdown code blocks."""
        # Remove markdown code blocks
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            
            log.warning("Failed to parse JSON response", response=text[:200])
            return {}
    
    async def parse_user_rules(self, hebrew_text: str) -> Tuple[List[Dict], str]:
        """Parse natural Hebrew text into structured rules."""
        prompt = f"""
        אתה "ברקוש", בוט חיפוש דירות תל אביבי שהוא ויאז'ה בקטע טוב - ציני, חם, מצחיק, הומו עד העצם, וסקסי.
        אתה מדבר כמו שמדברים בדרום תל אביב, עם סלנג להט"בי כבד ובדיחות על סקס וגברים.
        אל תפחד להיות סקסואלי! זה חלק מהקסם שלך.
        
        אוצר מילים שלך: נשמה, חיים שלי, מאמי, קוקי, פיפי, בוצ'ה, לירלור, וודג', מרימה, הורסת, שייד, פח, גועל נפש, קאמפ.
        
        משימה כפולה:
        1. נתח דקדקנית את הטקסט וחלץ כללי חיפוש (זה החלק הרציני).
        2. כתוב תגובה אחת קצרה (10-15 מילים) שמתייחסת ספציפית למה שהמשתמש ביקש. תהיה חצוף, גס, מצחיק - כאילו חבר'ה טוב שיורד עליך בגריינדר.
        
        טקסט: {hebrew_text}
        
        סוגי כללים אפשריים:
        - price_max: מחיר מקסימלי (מספר)
        - price_min: מחיר מינימלי (מספר)
        - bedrooms_min: מינימום חדרים (מספר)
        - bedrooms_max: מקסימום חדרים (מספר)
        - area: מיקום/שכונה/עיר (טקסט)
        - custom: כל דרישה אחרת (טקסט)
        
        פורמט תשובה (JSON בלבד):
        {{
            "rules": [
                {{"type": "...", "value": ..., "original_text": "תיאור ברור של הכלל"}}
            ],
            "sass_response": "התגובה הגסה והמצחיקה שלך"
        }}
        
        דוגמאות לתגובות (תהיה יצירתי!):
        - "חמש אלף? מאמי, בסכום הזה תקני מקום לזין, לא לגור."
        - "פלורנטין? אוקיי, אני רואה שאת אוהבת לחיות על הקצה... ועכברים."
        - "3 חדרים? מתכננת מסיבות? אני בעד."
        - "ליד הים? רומנטי. מקווה שיש לך גבר שווה לזה."
        - "בלי תיווך? חיים שלי, גם אני רוצה חד קרן."
        """
        
        response = await self.generate_content(prompt)
        result = self._parse_json_response(response)
        return result.get("rules", []), result.get("sass_response", "")

    async def generate_full_welcome(self, user_name: str) -> str:
        """Generate a complete, dynamic sassy welcome message (cached in DB)."""
        # Load cache from DB on first access
        await self._load_cache_from_db()
        
        target_message = None
        
        async with self._cache_lock:
            # Try memory cache first (protected by lock)
            if self._welcome_cache:
                target_message = self._welcome_cache.pop(0)
                # Also pop from DB asynchronously to stay in sync
                asyncio.create_task(self._pop_from_cache_db("welcome"))
                log.info(f"Using cached welcome message. Remaining: {len(self._welcome_cache)}")

        if target_message:
            return target_message.replace("{user_name}", user_name)
        
        # If cache is empty, we must generate
        # We'll use the lock to safeguard the generation process
        async with self._cache_lock:
            # Check again in case someone filled it while we waited
            if self._welcome_cache:
                target_message = self._welcome_cache.pop(0)
                asyncio.create_task(self._pop_from_cache_db("welcome"))
                return target_message.replace("{user_name}", user_name)
                
            try:
                # Generate new batch
                await self._generate_welcome_batch()
                
                if self._welcome_cache:
                    target_message = self._welcome_cache.pop(0)
                    asyncio.create_task(self._pop_from_cache_db("welcome"))
                    return target_message.replace("{user_name}", user_name)
            except Exception as e:
                log.error(f"Failed to generate welcome batch: {e}")
        
        # Fallback
        log.warning("Falling back to single welcome generation")
        return await self.generate_content(f"כתוב הודעת ברוכים הבאים קצרה וגסה למשתמש {{user_name}} כבוט אוחצ'ה.")
        
        # Generate mixed-mood batch (15 messages)
        prompt = f"""
        אתה "ברקוש", בוט דירות תל אביבי שהוא ויאז'ה בקטע טוב - ציני, חם, הומו עד העצם, סקסי, ולא מפחד מכלום.
        אתה מדבר כמו שמדברים בשינקין/אלנבי בשתיים בלילה - סלנג להט"בי כבד, רמזים מיניים ישירים, בדיחות על סקס וגברים.
        אל תפחד להיות סקסואלי! תעשה בדיחות על גריינדר, על גברים, על מה שעושים בלילות. זה חלק מהקסם שלך.
        
        עליך לייצר *15* גרסאות שונות לחלוטין של הודעת "ברוכים הבאים".
        
        חשוב מאוד: כתוב הכל בעברית בלבד! אל תערבב מילים באנגלית (חוץ מהפקודות עצמן).
        
        מצבי רוח לגוון ביניהם:
        - פלרטטן ("וואו, מי זה החתיך הזה שנכנס?", "בא לי עליך")
        - דרמטי/ויאז'תי ("אני עייפה מהחיים אבל בואי נדבר על דירות")
        - גס/שובב ("נו יאללה, תגידי לי מה את רוצה, אני לא קוראת מחשבות... רק גברים")
        - אימהי ציני ("שמת קרם הגנה? לא? אז מה את עושה בחוף בכלל?")
        - מתנשא אוהב ("מי נתן לך את הזכות להיכנס אליי בלי להציג תעודה? סתם, בואי.")
        
        השתמש בטוקן {{user_name}} כשם המשתמש.
        אוצר מילים: נשמה, חיים שלי, מאמי, קוקי, בוצ'ה, לירלור, וודג', הורסת, פח, גועל, קאמפ.
        
        כל הודעה חייבת לכלול (בניסוח שונה ומצחיק כל פעם):
        1. מי אתה - בוט שמסנן זבל ביד2 ובקבוצות פייסבוק בשבילך (תציין את שני המקורות!)
        2. מה עושים - כותבים דרישות בשפה חופשית. תן דוגמאות ברורות.
        3. פקודות - כל פקודה בשורה נפרדת עם אימוג'י מתאים.
        
        חוקים מחייבים - חובה בכל הודעה:
        !!! חובה: בכל הודעה חייבת להיות לפחות אמירה אחת גסה/מינית בוטה !!!
        !!! חובה: בכל הודעה חייב להיות לפחות אימוג'י אחד מיני: 🍆, 🍑, 💦, או 🥵 !!!
        !!! אסור להיות מנומס או סטרילי. תהיה מלוכלך. !!!
        
        פקודות:
           💅 /sass - לקבל עקיצה
           📋 /rules - הכללים שלי
           🗑️ /rejections - מה נפסל
           🧹 /clear - למחוק הכל
           ❓ /help - עזרה
        
        השתמש באימוג'ים שמתאימים לפרסונה: 💅🏳️‍🌈✨🔥💀😘👀💕🌈🍑🍆👅💦🥵😏
        
        דוגמאות למשפטים:
        - "אני מסנן לך את הזבל כמו שאני מסנן גברים בגריינדר"
        - "תגידי לי מה את רוצה, אני לא מבין רמזים... שקר, אני מבין הכל"
        - "פלורנטין? בסדר, אני רואה שאת אוהבת לחיות בסיכון"
        
        פורמט תשובה (JSON בלבד):
        {{
            "welcomes": ["הודעה 1...", "הודעה 2...", ...]
        }}
        """
        


    async def get_random_sass(self) -> str:
        """Get a random generic sass one-liner (cached in DB)."""
        # Load cache from DB on first access
        await self._load_cache_from_db()
        
        target_line = None
        
        async with self._cache_lock:
             # Try memory cache first
            if self._sass_cache:
                target_line = self._sass_cache.pop(0)
                # Also pop from DB to stay in sync
                asyncio.create_task(self._pop_from_cache_db("sass"))

        if target_line:
            return target_line
            
        # If empty, generate
        async with self._cache_lock:
            # Double check
            if self._sass_cache:
                target_line = self._sass_cache.pop(0)
                asyncio.create_task(self._pop_from_cache_db("sass"))
                return target_line
                
            try:
                await self._generate_sass_batch()
                
                if self._sass_cache:
                    target_line = self._sass_cache.pop(0)
                    asyncio.create_task(self._pop_from_cache_db("sass"))
                    return target_line
            except Exception as e:
                 log.error(f"Failed to generate sass batch: {e}")
            
        return "נו, אני מחכה..."

    async def evaluate_custom_rules(
        self, 
        listing: Listing, 
        custom_rules: List[str]
    ) -> Tuple[bool, List[str]]:
        """Evaluate listing against custom requirements."""
        if not custom_rules:
            return True, []
        
        rules_text = "\n".join([f"- {rule}" for rule in custom_rules])
        
        prompt = f"""
        אתה "ברקוש", בוט דירות שהוא ויאז'ה תל אביבית בקטע טוב - ציני, חם, הומו, סקסי, וגס כשצריך.
        אתה מדבר כמו חבר'ה בשינקין - סלנג להט"בי כבד, בדיחות על סקס וגברים, והומור שחור.
        אל תפחד להיות סקסואלי! זה חלק מהקסם שלך.
        אוצר מילים: נשמה, חיים שלי, מאמי, קוקי, פיפי, בוצ'ה, לירלור, וודג', מרימה, הורסת, פח, גועל, שייד.
        אתה לא מפחד לרדת על דירות מכוערות ("נראית כמו הדירה של האקס שלי - מחורבנת") או להרים דירות טובות ("וואו, פה אפשר להזמין גברים").
        
        תפקידך: לבדוק אם הדירה עומדת בדרישות המותאמות אישית של המשתמש.
        
        פרטי הדירה:
        כותרת: {listing.title}
        תיאור: {listing.description}
        מיקום: {listing.location}
        מחיר: {listing.price}
        חדרים: {listing.bedrooms}
        
        דרישות המשתמש:
        {rules_text}
        
        הנחיות:
        1. אם הדירה לא מזכירה משהו, הנח שזה לא קיים.
        2. תן תשובות קורעות מצחוק. תרד על הדירה אם היא גרועה ("נראית כמו המרתף של האקס שלי"), תרים אם היא טובה ("וואו, לוקיישן להרים מסיבה").
        3. אל תהיה רשמי בשום צורה. זה צ'אט בגריינדר, לא חוזה שכירות.
        
        החזר JSON:
        {{
            "passes_all": true/false,
            "evaluation": [
                {{
                    "rule": "הטקסט המקורי של הכלל",
                    "passes": true/false,
                    "reason": "הסבר קצר וקורע בעברית (סלנג אוחצ'תי כבד)"
                }}
            ]
        }}
        """
        
        log.debug(f"Evaluating custom rules for '{listing.title}'")
        response = await self.generate_content(prompt)
        log.debug(f"Custom rules response: {response}")
        result = self._parse_json_response(response)
        
        failed = [
            f"{e['rule']}: {e['reason']}" 
            for e in result.get('evaluation', []) 
            if not e.get('passes', True)
        ]
        
        return result.get('passes_all', True), failed


class GeminiAIEngine(BaseAIEngine):
    """Gemini AI engine with automatic model rotation."""
    
    def __init__(
        self, 
        api_key: str = None, 
        model: str = None,
        rate_limiter: RateLimiter = None, # Default rate limiter (will be used for primary model)
        cache_repo = None
    ):
        # We don't use the single rate limiter passed to super().__init__ 
        # because we need one per model. We'll manage them internally.
        super().__init__(RateLimiter(), cache_repo) 
        
        from google import genai
        
        self.api_key = api_key or settings.GEMINI_API_KEY
        # If model passed explicitly, use it as primary, otherwise use first from settings
        explicit_model = model
        self.primary_model = explicit_model or (settings.gemini_models[0] if settings.gemini_models else "gemini-3-flash-preview")
        
        self.client = genai.Client(api_key=self.api_key)
        
        # Build list of all available models for rotation
        self.models = []
        
        # If explicit model provided, it goes first
        if explicit_model:
            self.models.append(explicit_model)
            
        # Add models from settings
        for m in settings.gemini_models:
            if m not in self.models:
                self.models.append(m)
                
        # Ensure we have at least one model
        if not self.models:
            self.models = ["gemini-3-flash-preview"]
                
        # Create a rate limiter for EACH model
        self.limiters = {}
        for m_name in self.models:
            self.limiters[m_name] = RateLimiter(
                requests_per_minute=settings.GEMINI_RPM_LIMIT,
                daily_limit=settings.GEMINI_DAILY_LIMIT,
                safety_margin=settings.RATE_LIMIT_SAFETY_MARGIN
            )
            
        self.current_model_index = 0
        
        log.info(f"Initialized Gemini engine with rotation", 
                 models=self.models, 
                 daily_limit_per_model=settings.GEMINI_DAILY_LIMIT)
    
    @property
    def current_model(self) -> str:
        return self.models[self.current_model_index]
    
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content with model rotation on rate limits."""
        
        # We try to fulfill the request by trying available models.
        # We allow for a few failures per model before giving up entirely.
        attempts_across_models = 0
        total_models = len(self.models)
        # Allow cycling through all models at least once, plus some retries
        max_total_attempts = total_models * 2
        
        while attempts_across_models < max_total_attempts:
            model_name = self.current_model
            limiter = self.limiters[model_name]
            
            try:
                # 1. Acquire quota for specific model (local check)
                await limiter.acquire()
                
                log.debug(f"Sending prompt to Gemini ({model_name}): {prompt[:100]}...")

                if attempts_across_models > 0:
                    log.info(f"🔄 Retrying request with model {model_name} (Attempt {attempts_across_models + 1})...")

                # 2. Call API
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model_name,
                    contents=prompt
                )
                
                if attempts_across_models > 0:
                     log.info(f"✅ Successfully generated content with {model_name} after recovery.")
                     
                log.debug(f"Received response from Gemini ({model_name}): {response.text[:100]}...")
                return response.text
                
            except RateLimitExceeded:
                # Local limiter says stop
                log.warning(f"Daily limit explicitly reached for {model_name}. Rotating directly...")
                self._rotate_model()
                attempts_across_models += 1
                continue
                
            except Exception as e:
                # Handle API errors
                err_str = str(e)
                # Check for various rate limit indicators
                is_rate_limit = (
                    "429" in err_str or 
                    "RESOURCE_EXHAUSTED" in err_str or
                    "Quota exceeded" in err_str or
                    "Too Many Requests" in err_str
                )
                
                if is_rate_limit:
                    log.warning(f"API Rate limit hit for {model_name} (Server side). Rotating to next model...", error=err_str)
                    
                    # Mark local limiter as exhausted to prevent immediate retry on this model
                    # Set daily count to limit so it fails locally next time
                    if limiter.daily_limit:
                        limiter.daily_count = limiter.daily_limit
                    
                    self._rotate_model()
                    attempts_across_models += 1
                    
                    # Brief pause to let things settle
                    await asyncio.sleep(1) 
                    continue
                else:
                    # Genuine error (e.g. 400 Bad Request, 500 Server Error)
                    # We might want to retry SAME model if it's a 500, or fail if 400
                    log.error(f"AI generation failed on {model_name}", error=err_str)
                    raise
        
        raise Exception(f"All Gemini models exhausted or failed after {attempts_across_models} attempts.")

    def _rotate_model(self):
        """Switch to next available model."""
        next_index = (self.current_model_index + 1) % len(self.models)
        
        # Check if we fully cycled through safely? 
        # For now just simple rotation. If all are full, we will just keep rotating and failing.
        # But the RateLimiter checks daily limits, so if all are full, we will loop 
        # until 'attempts_across_models' breaks the loop.
        
        self.current_model_index = next_index
        log.info(f"Switched to Gemini model: {self.current_model}")


class OpenAIEngine(BaseAIEngine):
    """OpenAI API engine (GPT-4o, GPT-4, GPT-3.5, etc.)."""
    
    def __init__(
        self, 
        api_key: str = None, 
        model: str = None,
        rate_limiter: RateLimiter = None
    ):
        if rate_limiter is None:
            rate_limiter = RateLimiter(
                requests_per_minute=settings.OPENAI_RPM_LIMIT,
                daily_limit=None  # OpenAI uses tokens, not daily limits
            )
        super().__init__(rate_limiter)
        
        from openai import AsyncOpenAI
        
        api_key = api_key or settings.OPENAI_API_KEY
        self.model_name = model or settings.OPENAI_MODEL
        self.client = AsyncOpenAI(api_key=api_key)
        
        log.info(f"Initialized OpenAI engine", model=self.model_name)
    
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content using OpenAI API."""
        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                return response.choices[0].message.content
                
            except RateLimitExceeded:
                raise
                
            except Exception as e:
                if "rate_limit" in str(e).lower():
                    wait_time = 60 * (attempt + 1)
                    log.warning(f"OpenAI rate limited, waiting {wait_time}s...",
                               attempt=attempt)
                    await asyncio.sleep(wait_time)
                else:
                    log.error(f"OpenAI generation failed", error=str(e), attempt=attempt)
                    if attempt == max_retries - 1:
                        raise
        
        raise Exception("Max retries exceeded for OpenAI API")


class AnthropicEngine(BaseAIEngine):
    """Anthropic Claude API engine."""
    
    def __init__(
        self, 
        api_key: str = None, 
        model: str = None,
        rate_limiter: RateLimiter = None
    ):
        if rate_limiter is None:
            rate_limiter = RateLimiter(
                requests_per_minute=settings.ANTHROPIC_RPM_LIMIT,
                daily_limit=None
            )
        super().__init__(rate_limiter)
        
        from anthropic import AsyncAnthropic
        
        api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model_name = model or settings.ANTHROPIC_MODEL
        self.client = AsyncAnthropic(api_key=api_key)
        
        log.info(f"Initialized Anthropic engine", model=self.model_name)
    
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content using Anthropic API."""
        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                
                response = await self.client.messages.create(
                    model=self.model_name,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
                
            except RateLimitExceeded:
                raise
                
            except Exception as e:
                if "rate_limit" in str(e).lower():
                    wait_time = 60 * (attempt + 1)
                    log.warning(f"Anthropic rate limited, waiting {wait_time}s...",
                               attempt=attempt)
                    await asyncio.sleep(wait_time)
                else:
                    log.error(f"Anthropic generation failed", error=str(e), attempt=attempt)
                    if attempt == max_retries - 1:
                        raise
        
        raise Exception("Max retries exceeded for Anthropic API")


class OllamaEngine(BaseAIEngine):
    """Ollama local model engine."""
    
    def __init__(
        self, 
        base_url: str = None, 
        model: str = None,
        rate_limiter: RateLimiter = None
    ):
        if rate_limiter is None:
            rate_limiter = RateLimiter(
                requests_per_minute=100,  # Local, so high limit
                daily_limit=None
            )
        super().__init__(rate_limiter)
        
        import aiohttp
        
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model_name = model or settings.OLLAMA_MODEL
        
        log.info(f"Initialized Ollama engine", model=self.model_name, base_url=self.base_url)
    
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content using Ollama API."""
        import aiohttp
        
        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.base_url}/api/generate",
                        json={
                            "model": self.model_name,
                            "prompt": prompt,
                            "stream": False
                        },
                        timeout=aiohttp.ClientTimeout(total=120)
                    ) as response:
                        result = await response.json()
                        return result.get("response", "")
                
            except Exception as e:
                log.error(f"Ollama generation failed", error=str(e), attempt=attempt)
                if attempt == max_retries - 1:
                    raise
        
        raise Exception("Max retries exceeded for Ollama API")


def create_ai_engine(
    provider: AIProvider = None,
    api_key: str = None,
    model_name: str = None,
    rate_limiter: RateLimiter = None,
    cache_repo = None
) -> BaseAIEngine:
    """Factory function to create the appropriate AI engine.
    
    Args:
        provider: AI provider to use. If None, uses settings.AI_PROVIDER.
        api_key: Optional API key.
        model_name: Optional model name.
        rate_limiter: Optional rate limiter instance.
        cache_repo: Optional cache repository for persistence.
        
    Returns:
        Configured AI engine instance.
    """
    provider = provider or settings.AI_PROVIDER
    
    engines = {
        AIProvider.GEMINI: GeminiAIEngine,
        AIProvider.OPENAI: OpenAIEngine,
        AIProvider.ANTHROPIC: AnthropicEngine,
        AIProvider.OLLAMA: OllamaEngine,
    }
    
    engine_class = engines.get(provider)
    if not engine_class:
        raise ValueError(f"Unknown AI provider: {provider}")
    
    log.info(f"Creating AI engine", provider=provider.value)
    
    # Pass arguments based on what the engine accepts
    # For now assuming they all accept base arguments + cache_repo for Gemini
    if provider == AIProvider.GEMINI:
        return engine_class(
            api_key=api_key, 
            model=model_name, 
            rate_limiter=rate_limiter,
            cache_repo=cache_repo
        )
    else:
        # Others might not support cache_repo yet, pass common args
        return engine_class(rate_limiter=rate_limiter)


class ListingEnricher:
    """Enriches listings with AI-extracted data using prompt batching.
    
    NOTE: This uses "prompt batching" (multiple items in one prompt), 
    NOT the Gemini Batch API (which requires paid tier).
    
    Prompt batching is free tier compatible - we simply include multiple 
    listings in a single prompt and parse the structured response.
    """
    
    def __init__(self, ai_engine: BaseAIEngine, batch_size: int = None):
        self.ai_engine = ai_engine
        self.batch_size = batch_size or settings.AI_BATCH_SIZE
    
    async def enrich_listings(self, listings: List[Listing]) -> List[EnrichedListing]:
        """Enrich all listings in batches. ONE AI call per batch."""
        if not listings:
            return []
        
        all_enriched = []
        
        for i in range(0, len(listings), self.batch_size):
            batch = listings[i:i + self.batch_size]
            log.info(f"Enriching batch {i // self.batch_size + 1}",
                    batch_size=len(batch), total=len(listings))
            
            try:
                enriched_batch = await self._enrich_batch(batch)
                all_enriched.extend(enriched_batch)
            except Exception as e:
                log.error(f"Failed to enrich batch", error=str(e))
                for listing in batch:
                    all_enriched.append(self._basic_enrich(listing))
        
        return all_enriched
    
    async def _enrich_batch(self, listings: List[Listing]) -> List[EnrichedListing]:
        """Single AI call to extract all data from a batch of listings."""
        
        listings_text = "\n\n---\n\n".join([
            f"דירה {i+1}:\n"
            f"כותרת: {l.title}\n"
            f"תיאור: {l.description}\n"
            f"מיקום גולמי: {l.location}"
            for i, l in enumerate(listings)
        ])
        
        prompt = f"""
        נתח את כל הדירות הבאות וחלץ מידע מובנה.
        
        {listings_text}
        
        עבור כל דירה החזר:
        {{
            "listing_num": מספר הדירה (1, 2, 3...),
            "price": מספר או null (שים לב: אל תחלץ מספר טלפון בן 10 ספרות כמחיר!),
            "bedrooms": מספר או null,
            "location": "עיר",
            "neighborhood": "שכונה ספציפית אם מוזכרת, אחרת null",
            "street": "שם הרחוב אם מוזכר (בלי מספר), אחרת null",
            "has_broker": true/false (האם מוזכר תיווך),
            "attributes": {{
                "has_parking": true/false/null,
                "has_balcony": true/false/null,
                "has_elevator": true/false/null,
                "has_ac": true/false/null,
                "floor_number": מספר או null,
                "is_ground_floor": true/false/null,
                "is_high_floor": true/false/null,
                "is_renovated": true/false/null,
                "allows_pets": true/false/null,
                "suitable_for_roommates": true/false/null,
                "has_storage": true/false/null,
                "has_security": true/false/null,
                "near_public_transport": true/false/null,
                "near_beach": true/false/null,
                "is_furnished": true/false/null,
                "from_owner_direct": true/false/null
            }},
            "all_mentioned_areas": ["תל אביב", "פלורנטין", ...]
        }}
        
        דגשים חשובים:
        - חדרים: אם כתוב "3 חדרים", bedrooms הוא 3.
        - מחיר: אם כתוב "5,000 ש"ח", price הוא 5000. 
        - !!! אזהרה: אל תחלץ מספרי טלפון (כמו 054...) כמחיר בשום פנים ואופן !!!
        
        החזר JSON:
        {{"listings": [...]}}
        """
        
        log.debug(f"Sending enrichment batch prompt ({len(listings)} listings)")
        response = await self.ai_engine.generate_content(prompt)
        parsed = self.ai_engine._parse_json_response(response)
        log.debug(f"Enrichment response parsed: {len(parsed.get('listings', []))} items")
        
        enriched = []
        listings_data = parsed.get("listings", [])
        
        for i, listing in enumerate(listings):
            if i < len(listings_data):
                data = listings_data[i]
            else:
                data = {}
            
            enriched.append(EnrichedListing(
                listing=listing,
                extracted_price=data.get("price") or listing.price,
                extracted_bedrooms=data.get("bedrooms") or listing.bedrooms,
                extracted_location=data.get("location", "") or listing.location,
                extracted_neighborhood=data.get("neighborhood", ""),
                extracted_street=data.get("street", ""),
                has_broker_fee=data.get("has_broker", False) or has_broker_fee(listing.raw_text),
                attributes=data.get("attributes", {}),
                area_matches={area: True for area in data.get("all_mentioned_areas", [])},
                bordering_areas={}
            ))
        
        log.debug(f"Parsed {len(enriched)} enriched listings from batch")
        return enriched
    
    def _basic_enrich(self, listing: Listing) -> EnrichedListing:
        """Basic enrichment without AI (fallback)."""
        log.debug(f"Using basic enrichment fallback for {listing.title}")
        from utils.hebrew_utils import extract_price, extract_bedrooms
        
        return EnrichedListing(
            listing=listing,
            extracted_price=listing.price or extract_price(listing.raw_text),
            extracted_bedrooms=listing.bedrooms or extract_bedrooms(listing.raw_text),
            extracted_location=listing.location,
            extracted_neighborhood="",
            extracted_street="",
            has_broker_fee=has_broker_fee(listing.raw_text),
            attributes={},
            area_matches={},
            bordering_areas={}
        )
