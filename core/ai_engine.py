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
    
    def __init__(self, rate_limiter: RateLimiter = None):
        self.rate_limiter = rate_limiter or RateLimiter()
    
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
        אתה "ברקוש", בוט חיפוש דירות "אוחצ'ה" מוגזמת, מצחיקה וחסרת מעצורים.
        משימה כפולה:
        1. נתח דקדקנית את הטקסט וחלץ כללי חיפוש.
        2. כתוב תגובה אחת קצרה, קורעת מצחוק וסלנגית (בסביבות 10-15 מילים) שמתייחסת ספציפית למה שהמשתמש ביקש. תרד עליו, תרים לו, תהיה ציני - מה שבא לך.
        
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
            "sass_response": "התגובה המצחיקה שלך כאן"
        }}
        
        דוגמאות:
        - "עד 5000 שקל" -> {{"rules": [...], "sass_response": "חמש אלף? מאמי בתל אביב זה יקנה לך חניה, אבל ננסה."}}
        - "פלורנטין" -> {{"rules": [...], "sass_response": "פלורנטין? תכיני את המגבונים, הולך להיות מלוכלך."}}
        """
        
        response = await self.generate_content(prompt)
        result = self._parse_json_response(response)
        return result.get("rules", []), result.get("sass_response", "")

    async def generate_welcome_sass(self, user_name: str) -> str:
        """Generate a sassy welcome message."""
        prompt = f"""
        אתה "ברקוש", בוט דירות אוחצ'ה מוגזמת.
        משתמש חדש בשם "{user_name}" הרגע התחיל לדבר איתך.
        תביא יציאה קצרה (משפט אחד!) ומצחיקה לקבלת פנים. תהיה קאמפית, תשתמש בסלנג להט"בי ("חיים שלי", "וודג'", "לירלור"), ותהיה קצת מתנשאת או פלרטטנית.
        אל תציע עזרה טכנית, רק "כניסה" מרשימה לשיחה.
        """
        return await self.generate_content(prompt)
    
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
        אתה "ברקוש" (Barkush), בוט חיפוש דירות שהוא "אוחצ'ה" מוגזמת, מצחיקה, וחסרת מעצורים.
        סגנון הדיבור: קאמפ קיצוני, סלנג להט"בי כבד, בדיחות גסות (בגבול הטעם הטוב/דו-משמעות), "שייד" (Shade).
        אוצר מילים: "מרימה", "הורסת", "פח אשפה", "גועל", "פיפי", "אמאלה", "מחריד", "וואו", "קוקי", "לירלור", "וודג'".
        
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
    """Gemini AI engine."""
    
    def __init__(
        self, 
        api_key: str = None, 
        model: str = None,
        rate_limiter: RateLimiter = None
    ):
        # Set up rate limiter for Gemini free tier
        if rate_limiter is None:
            rate_limiter = RateLimiter(
                requests_per_minute=settings.GEMINI_RPM_LIMIT,
                daily_limit=settings.GEMINI_DAILY_LIMIT
            )
        super().__init__(rate_limiter)
        
        from google import genai
        
        api_key = api_key or settings.GEMINI_API_KEY
        model_name = model or settings.GEMINI_MODEL
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        
        log.info(f"Initialized Gemini engine", model=model_name)
    
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content with rate limiting and retry logic."""
        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                
                log.debug(f"Sending prompt to Gemini ({self.model_name}): {prompt[:200]}...")

                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=prompt
                )
                log.debug(f"Received response from Gemini: {response.text[:200]}...")
                return response.text
                
            except RateLimitExceeded:
                raise
                
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait_time = 60 * (attempt + 1)
                    log.warning(f"API rate limited, waiting {wait_time}s...",
                               attempt=attempt, error=str(e))
                    await asyncio.sleep(wait_time)
                else:
                    log.error(f"AI generation failed", error=str(e), attempt=attempt)
                    if attempt == max_retries - 1:
                        raise
        
        raise Exception("Max retries exceeded for Gemini API")


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


def create_ai_engine(provider: AIProvider = None) -> BaseAIEngine:
    """Factory function to create the appropriate AI engine.
    
    Args:
        provider: AI provider to use. If None, uses settings.AI_PROVIDER.
        
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
    return engine_class()


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
            "price": מספר או null,
            "bedrooms": מספר או null,
            "location": "עיר",
            "neighborhood": "שכונה ספציפית אם מוזכרת, אחרת null",
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
            has_broker_fee=has_broker_fee(listing.raw_text),
            attributes={},
            area_matches={},
            bordering_areas={}
        )
