# core/ai_engine.py
"""Multi-provider AI integration with rate limiting."""

import asyncio
import json
import re
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from config import settings, AIProvider
from utils.logger import Loggers
from utils.hebrew_utils import has_broker_fee
from models.listing import Listing, EnrichedListing
from core.personas import get_persona, PERSONAS


log = Loggers.ai()


class RateLimitExceeded(Exception):
    """Raised when API quota is exhausted."""
    pass


async def retry_with_backoff(
    coro_func, 
    *args, 
    max_retries: int = 10,
    base_delay: float = 2.0, 
    max_delay: float = 30.0,
    **kwargs
) -> Any:
    """Executes a coroutine (or sync function in thread) with safe exponential backoff
    for transient, non-rate-limit errors.
    """
    for attempt in range(max_retries):
        try:
            if asyncio.iscoroutinefunction(coro_func):
                return await coro_func(*args, **kwargs)
            else:
                return await asyncio.to_thread(coro_func, *args, **kwargs)
        except Exception as e:
            err_str = str(e)
            
            # 1. Bypass retry if this is a rate limit error (caller handles this separately)
            is_rate_limit = (
                "429" in err_str or 
                "RESOURCE_EXHAUSTED" in err_str or
                "quota" in err_str.lower() or
                "rate_limit" in err_str.lower() or
                "too many requests" in err_str.lower()
            )
            if is_rate_limit:
                raise e
                
            # 2. Bypass retry if this is a known non-retriable client error
            status_code = None
            for attr in ("code", "status_code", "status"):
                val = getattr(e, attr, None)
                if val is not None:
                    status_code = val
                    break
                    
            if status_code in [400, 401, 403, 404, 422]:
                log.error(f"Non-retriable client error ({status_code}) encountered. Raising immediately.", error=str(e))
                raise e
            
            # 3. Exhausted all retries
            if attempt == max_retries - 1:
                log.error(f"Failed after {max_retries} attempts. Raising error.", error=str(e))
                raise e
                
            # 4. Safe backoff delay with proportional jitter (+/- 20%)
            delay = min(base_delay * (2.0 ** attempt), max_delay)
            jitter = random.uniform(0.8, 1.2)
            actual_delay = delay * jitter
            
            log.warning(
                f"Transient error occurred: {type(e).__name__}: {e}. "
                f"Retrying in {actual_delay:.2f}s (Attempt {attempt + 1}/{max_retries})..."
            )
            await asyncio.sleep(actual_delay)


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
        self._welcome_cache: Dict[str, List[str]] = {}  # persona_name -> list
        self._sass_cache: Dict[str, List[str]] = {}  # persona_name -> list
        self._cache_repo = cache_repo
        self._cache_loaded = False
        self._cache_lock = asyncio.Lock() # Protect against concurrent generation
        self._locks: Dict[str, asyncio.Lock] = {}
        
    def _get_lock(self, persona: str, cache_type: str) -> asyncio.Lock:
        """Get or create a lock for a specific persona and cache type."""
        key = f"{persona}:{cache_type}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]
    
    async def warm_up_cache(self):
        """Warm up cache if empty (generating initial batches in parallel)."""
        await self._load_cache_from_db()
        
        async def warm_up_persona_type(persona_name: str, cache_type: str):
            lock = self._get_lock(persona_name, cache_type)
            async with lock:
                if cache_type == "welcome":
                    if persona_name not in self._welcome_cache:
                        self._welcome_cache[persona_name] = []
                    
                    if not self._welcome_cache[persona_name]:
                        log.info(f"Warming up welcome message cache for {persona_name}...")
                        try:
                            await self._generate_welcome_batch(persona=persona_name)
                        except Exception as e:
                            log.error(f"Failed to warm up welcome cache for {persona_name}: {e}")
                elif cache_type == "sass":
                    if persona_name not in self._sass_cache:
                        self._sass_cache[persona_name] = []
                        
                    if not self._sass_cache[persona_name]:
                        log.info(f"Warming up sass message cache for {persona_name}...")
                        try:
                            await self._generate_sass_batch(persona=persona_name)
                        except Exception as e:
                            log.error(f"Failed to warm up sass cache for {persona_name}: {e}")

        # Warm up all personas and cache types in parallel
        tasks = []
        for persona_name in PERSONAS:
            tasks.append(warm_up_persona_type(persona_name, "welcome"))
            tasks.append(warm_up_persona_type(persona_name, "sass"))
            
        await asyncio.gather(*tasks, return_exceptions=True)
             
    async def _load_cache_from_db(self):
        """Load cached content from database on first access."""
        if self._cache_loaded or not self._cache_repo:
            return
        
        async with self._cache_lock:
            if self._cache_loaded: # Double check inside lock
                return
                
            try:
                for persona_name in PERSONAS:
                    welcome_items = await self._cache_repo.get_cached_items("welcome", persona=persona_name)
                    sass_items = await self._cache_repo.get_cached_items("sass", persona=persona_name)
                    self._welcome_cache[persona_name] = welcome_items
                    self._sass_cache[persona_name] = sass_items
                    log.info(f"Loaded cache from DB for {persona_name}: {len(welcome_items)} welcome, {len(sass_items)} sass")
            except Exception as e:
                log.error(f"Failed to load cache from DB: {e}")
            
            self._cache_loaded = True
    
    async def _generate_welcome_batch(self, persona: str = "barakush"):
        """Generate a batch of welcome messages and store in cache/DB."""
        persona_def = get_persona(persona)
        prompt = persona_def.welcome_batch_prompt
        
        try:
            response = await self.generate_content(prompt)
            data = self._parse_json_response(response)
            messages = data.get("welcomes", [])
            
            if messages:
                import random
                random.shuffle(messages)
                
                # Save all to DB cache
                await self._save_to_cache_db("welcome", messages, persona=persona)
                
                # Also keep in memory
                if persona not in self._welcome_cache:
                    self._welcome_cache[persona] = []
                self._welcome_cache[persona].extend(messages)
                log.info(f"Generated {len(messages)} mixed-mood welcome messages for {persona}. Cached {len(self._welcome_cache[persona])}.")
        except Exception as e:
            log.error(f"Failed to generate welcome batch for {persona}: {e}")
            raise

    async def _generate_sass_batch(self, persona: str = "barakush"):
        """Generate a batch of sass lines and store in cache/DB."""
        persona_def = get_persona(persona)
        prompt = persona_def.sass_batch_prompt
        
        try:
            response = await self.generate_content(prompt)
            data = self._parse_json_response(response)
            lines = data.get("sass_lines", [])
            
            if lines:
                import random
                random.shuffle(lines)
                
                # Save all to DB cache
                await self._save_to_cache_db("sass", lines, persona=persona)
                
                # Also keep in memory
                if persona not in self._sass_cache:
                    self._sass_cache[persona] = []
                self._sass_cache[persona].extend(lines)
                log.info(f"Generated {len(lines)} mixed-mood sass lines for {persona}. Cached {len(self._sass_cache[persona])}.")
        except Exception as e:
            log.error(f"Failed to generate sass batch for {persona}: {e}")
            raise

    async def _save_to_cache_db(self, cache_type: str, items: List[str], persona: str = "barakush"):
        """Save generated items to database cache."""
        if not self._cache_repo:
            return
        
        try:
            await self._cache_repo.add_cached_items(cache_type, items, persona=persona)
            log.info(f"Saved {len(items)} {cache_type} items to DB cache for {persona}")
        except Exception as e:
            log.error(f"Failed to save cache to DB: {e}")
    
    async def _pop_from_cache_db(self, cache_type: str, persona: str = "barakush") -> str:
        """Pop an item from database cache."""
        if not self._cache_repo:
            return None
        
        try:
            return await self._cache_repo.pop_cached_item(cache_type, persona=persona)
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
    
    async def parse_user_rules(self, hebrew_text: str, persona: str = "barakush") -> Tuple[List[Dict], str]:
        """Parse natural Hebrew text into structured rules."""
        persona_def = get_persona(persona)
        prompt = persona_def.parse_rules_prompt.format(hebrew_text=hebrew_text)
        
        response = await self.generate_content(prompt)
        result = self._parse_json_response(response)
        return result.get("rules", []), result.get("sass_response", "")

    async def generate_full_welcome(self, user_name: str, persona: str = "barakush") -> str:
        """Generate a complete, dynamic sassy welcome message (cached in DB)."""
        # Load cache from DB on first access
        await self._load_cache_from_db()
        
        target_message = None
        lock = self._get_lock(persona, "welcome")
        
        async with lock:
            # Try memory cache first (protected by lock)
            if persona in self._welcome_cache and self._welcome_cache[persona]:
                target_message = self._welcome_cache[persona].pop(0)
                # Also pop from DB asynchronously to stay in sync
                asyncio.create_task(self._pop_from_cache_db("welcome", persona=persona))
                log.info(f"Using cached welcome message for {persona}. Remaining: {len(self._welcome_cache[persona])}")

        if target_message:
            return target_message.replace("{user_name}", user_name)
        
        # If cache is empty, we must generate
        # We'll use the lock to safeguard the generation process
        async with lock:
            # Check again in case someone filled it while we waited
            if persona in self._welcome_cache and self._welcome_cache[persona]:
                target_message = self._welcome_cache[persona].pop(0)
                asyncio.create_task(self._pop_from_cache_db("welcome", persona=persona))
                return target_message.replace("{user_name}", user_name)
                
            try:
                # Generate new batch
                await self._generate_welcome_batch(persona=persona)
                
                if persona in self._welcome_cache and self._welcome_cache[persona]:
                    target_message = self._welcome_cache[persona].pop(0)
                    asyncio.create_task(self._pop_from_cache_db("welcome", persona=persona))
                    return target_message.replace("{user_name}", user_name)
            except Exception as e:
                log.error(f"Failed to generate welcome batch for {persona}: {e}")
        
        # Fallback
        log.warning(f"Falling back to single welcome generation for {persona}")
        persona_def = get_persona(persona)
        return persona_def.fallback_welcome.replace("{user_name}", user_name)

    async def get_random_sass(self, persona: str = "barakush") -> str:
        """Get a random generic sass one-liner (cached in DB)."""
        # Load cache from DB on first access
        await self._load_cache_from_db()
        
        target_line = None
        lock = self._get_lock(persona, "sass")
        
        async with lock:
             # Try memory cache first
            if persona in self._sass_cache and self._sass_cache[persona]:
                target_line = self._sass_cache[persona].pop(0)
                # Also pop from DB to stay in sync
                asyncio.create_task(self._pop_from_cache_db("sass", persona=persona))

        if target_line:
            return target_line
            
        # If empty, generate
        async with lock:
            # Double check
            if persona in self._sass_cache and self._sass_cache[persona]:
                target_line = self._sass_cache[persona].pop(0)
                asyncio.create_task(self._pop_from_cache_db("sass", persona=persona))
                return target_line
                
            try:
                await self._generate_sass_batch(persona=persona)
                
                if persona in self._sass_cache and self._sass_cache[persona]:
                    target_line = self._sass_cache[persona].pop(0)
                    asyncio.create_task(self._pop_from_cache_db("sass", persona=persona))
                    return target_line
            except Exception as e:
                 log.error(f"Failed to generate sass batch for {persona}: {e}")
            
        persona_def = get_persona(persona)
        if persona == "yekke":
            return "נא להמתין. המערכת מעבדת נתוני נדל\"ן..."
        elif persona == "mom":
            return "אמא מחכה כאן, שלא תגיד שלא אמרתי לך..."
        elif persona == "stoner":
            return "הכל סבבה לגמרי אחי, תיכף חוזרים..."
        return "נו, אני מחכה..."

    async def evaluate_custom_rules(
        self, 
        listing: Listing, 
        custom_rules: List[str],
        persona: str = "barakush"
    ) -> Tuple[bool, List[str]]:
        """Evaluate listing against custom requirements."""
        if not custom_rules:
            return True, []
        
        rules_text = "\n".join([f"- {rule}" for rule in custom_rules])
        
        persona_def = get_persona(persona)
        
        prompt = persona_def.custom_rules_prompt.format(
            title=listing.title,
            description=listing.description,
            location=listing.location,
            price=listing.price,
            bedrooms=listing.bedrooms,
            rules_text=rules_text
        )
        
        log.debug(f"Evaluating custom rules for '{listing.title}' with persona '{persona}'")
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

                # 2. Call API (retrying transient errors safely)
                response = await retry_with_backoff(
                    self.client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    max_retries=max_retries
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
                
                response = await retry_with_backoff(
                    self.client.chat.completions.create,
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_retries=max_retries
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
                
                response = await retry_with_backoff(
                    self.client.messages.create,
                    model=self.model_name,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    max_retries=max_retries
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
        
        async def _call_ollama():
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
                    if response.status != 200:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=f"HTTP {response.status}: {response.reason}"
                        )
                    result = await response.json()
                    return result.get("response", "")

        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                
                return await retry_with_backoff(
                    _call_ollama,
                    max_retries=max_retries
                )
                
            except Exception as e:
                log.error(f"Ollama generation failed", error=str(e), attempt=attempt)
                if attempt == max_retries - 1:
                    raise
        
        raise Exception("Max retries exceeded for Ollama API")


class GroqEngine(BaseAIEngine):
    """Groq API engine (Llama, Mixtral, Gemma models with fast inference)."""
    
    def __init__(
        self, 
        api_key: str = None, 
        model: str = None,
        rate_limiter: RateLimiter = None,
        cache_repo = None
    ):
        if rate_limiter is None:
            rate_limiter = RateLimiter(
                requests_per_minute=settings.GROQ_RPM_LIMIT,
                daily_limit=settings.GROQ_DAILY_LIMIT
            )
        super().__init__(rate_limiter, cache_repo)
        
        from groq import AsyncGroq
        
        api_key = api_key or settings.GROQ_API_KEY
        self.model_name = model or settings.GROQ_MODEL
        self.client = AsyncGroq(api_key=api_key)
        
        log.info(f"Initialized Groq engine", model=self.model_name)
    
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content using Groq API."""
        for attempt in range(max_retries):
            try:
                await self.rate_limiter.acquire()
                
                response = await retry_with_backoff(
                    self.client.chat.completions.create,
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_retries=max_retries
                )
                return response.choices[0].message.content
                
            except RateLimitExceeded:
                raise
                
            except Exception as e:
                err_str = str(e).lower()
                if "rate_limit" in err_str or "429" in str(e):
                    wait_time = 60 * (attempt + 1)
                    log.warning(f"Groq rate limited, waiting {wait_time}s...",
                               attempt=attempt)
                    await asyncio.sleep(wait_time)
                else:
                    log.error(f"Groq generation failed", error=str(e), attempt=attempt)
                    if attempt == max_retries - 1:
                        raise
        
        raise Exception("Max retries exceeded for Groq API")


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
        AIProvider.GROQ: GroqEngine,
    }
    
    engine_class = engines.get(provider)
    if not engine_class:
        raise ValueError(f"Unknown AI provider: {provider}")
    
    log.info(f"Creating AI engine", provider=provider.value)
    
    # Pass arguments based on what the engine accepts
    # Gemini and Groq support cache_repo
    if provider in (AIProvider.GEMINI, AIProvider.GROQ):
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
            "location": "עיר (ברירת מחדל: תל אביב)",
            "neighborhood": "שכונה ספציפית. חשוב: נסה להסיק מהרחוב! לדוגמה: אלנבי/רוטשילד/נחלת בנימין = לב תל אביב, פלורנטין = פלורנטין, דיזנגוף = הצפון הישן, ללא מידע = null",
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
            "all_mentioned_areas": ["תל אביב", "פלורנטין", ...],
            "posted_hours_ago": מספר שעות מאז הפרסום, או null אם לא ניתן לחלץ (לדוגמה: "2h" = 2, "אתמול" = 24, "3 ימים" = 72)
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
        
        # Import for fallback extraction
        from utils.hebrew_utils import extract_price, extract_bedrooms
        
        for i, listing in enumerate(listings):
            if i < len(listings_data):
                data = listings_data[i]
            else:
                data = {}
                log.debug(f"No AI data for listing #{i+1}, using regex fallback")
            
            # If listing has no posted_at but AI extracted time, apply it
            if not listing.posted_at and data.get("posted_hours_ago"):
                hours_ago = data.get("posted_hours_ago")
                if isinstance(hours_ago, (int, float)) and hours_ago > 0:
                    listing.posted_at = datetime.now() - timedelta(hours=hours_ago)
                    log.debug(f"Applied AI-extracted date for listing: {hours_ago}h ago -> {listing.posted_at}")
            
            # Determine price with multiple fallbacks:
            # 1. AI-extracted price
            # 2. Scraped price (listing.price)
            # 3. Regex extraction from raw text
            ai_price = data.get("price")
            scraped_price = listing.price
            regex_price = extract_price(listing.raw_text) if listing.raw_text else None
            final_price = ai_price or scraped_price or regex_price
            
            # Log when all sources failed to get a price
            if not final_price:
                raw_preview = listing.raw_text[:150].replace('\n', ' ') if listing.raw_text else 'N/A'
                log.warning(
                    f"No price found for listing #{i+1}: AI={ai_price}, Scraped={scraped_price}, Regex={regex_price}",
                    listing_title=listing.title[:30] if listing.title else 'N/A',
                    raw_text_preview=raw_preview
                )
            
            # Also apply AI price to listing object if we got it
            if ai_price and not listing.price:
                listing.price = ai_price
            
            # Same for bedrooms
            final_bedrooms = data.get("bedrooms") or listing.bedrooms or extract_bedrooms(listing.raw_text)
            
            enriched.append(EnrichedListing(
                listing=listing,
                extracted_price=final_price,
                extracted_bedrooms=final_bedrooms,
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
