# main.py
"""Main entry point for the Apartment Search Bot."""

# Patch platform._wmi_query to avoid hangs on Windows environments with broken WMI
import sys
if sys.platform == "win32":
    try:
        import platform
        platform._wmi_query = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("WMI disabled"))
    except Exception:
        pass

import asyncio
import signal
from typing import Dict, List

from config import settings
from utils.logger import LoggerFactory, Loggers
from utils.telemetry import telemetry
from database import get_db
from database.repositories import (
    UserRepository, 
    RuleRepository, 
    RejectionRepository,
    SeenListingsRepository,
    ListingRepository
)
from core.ai_engine import create_ai_engine, ListingEnricher, RateLimiter
from core.matcher import ZeroAIUserMatcher
from core.processing import ProcessingService
from scrapers import FacebookScraper, Yad2Scraper, AntiDetectionModule
from scrapers.yad2_playwright_scraper import Yad2PlaywrightScraper
from scrapers.scheduler import QuotaAwareScheduler
from bot import ApartmentBot
from models.listing import EnrichedListing, Listing

# Initialize logging
import logging
LoggerFactory.initialize(debug=settings.DEBUG)
log = Loggers.app()

from utils.admin_notifier import admin_notifier_handler
logging.root.addHandler(admin_notifier_handler)


class ApartmentBotApplication:
    """Main application class that wires everything together."""
    
    def __init__(self):
        self.bot: ApartmentBot = None
        self.scheduler: QuotaAwareScheduler = None
        self.ai_engine = None  # BaseAIEngine
        self.rate_limiter: RateLimiter = None
        self.enricher: ListingEnricher = None
        self.matcher: ZeroAIUserMatcher = None
        self.processing_service: ProcessingService = None
        
        # Scrapers
        self.facebook_scraper: FacebookScraper = None
        self.yad2_scraper: Yad2Scraper = None
        
        # Running flag
        self._running = False
    
    async def initialize(self):
        """Initialize all components."""
        log.info("Initializing Apartment Bot Application")
        
        # Initialize database
        db = await get_db()
        log.info("Database initialized")
        
        # Reset database components if configured
        tables_to_drop = []
        
        # Data reset (listings, seen history, rejections)
        if settings.RESET_DB_ON_STARTUP:
            log.warning("⚠️ RESET_DB_ON_STARTUP is True. Resetting data, history and rejections.")
            # Drop child tables first
            tables_to_drop.extend(["rejection_logs", "enriched_listings", "seen_listings"])
            
        # User account reset (users and their rules)
        if settings.RESET_USERS_ON_STARTUP:
            log.warning("⚠️ RESET_USERS_ON_STARTUP is True. Resetting users and rules.")
            # Ensure children are dropped before parents
            for t in ["rejection_logs", "search_rules"]:
                if t not in tables_to_drop:
                    tables_to_drop.append(t)
            tables_to_drop.append("users")
            
        if tables_to_drop:
            # deduplicate and maintain order (child tables first)
            seen = set()
            ordered_drops = []
            for t in ["rejection_logs", "search_rules", "enriched_listings", "seen_listings", "users"]:
                if t in tables_to_drop and t not in seen:
                    ordered_drops.append(t)
                    seen.add(t)
            
            for table in ordered_drops:
                await db.execute(f"DROP TABLE IF EXISTS {table}")
            
            # Re-initialize schema
            await db.initialize()
            log.info(f"Database reset complete. Dropped: {', '.join(ordered_drops)}")
        
        # Initialize Cache Repository
        from database.repositories.cache_repository import CacheRepository
        db_manager = await get_db()
        cache_repo = CacheRepository(db_manager)
        seen_repo = SeenListingsRepository(db_manager)
        
        # Reset persona cache if configured
        if settings.RESET_PERSONA_CACHE_ON_STARTUP:
            log.warning(f"⚠️ Clearing persona cache (Config value: {settings.RESET_PERSONA_CACHE_ON_STARTUP}). Check .env if this is unexpected.")
            await cache_repo.clear_cache()
            log.info("Persona cache cleared")

        # Initialize Chat Rate Limiter and AI Engine
        self.chat_rate_limiter = RateLimiter(
            requests_per_minute=settings.chat_rate_limit,
            daily_limit=settings.chat_daily_limit
        )
        self.chat_ai_engine = create_ai_engine(
            provider=settings.chat_provider,
            api_key=settings.chat_api_key,
            model_name=settings.chat_model,
            rate_limiter=self.chat_rate_limiter,
            cache_repo=cache_repo
        )
        self.ai_engine = self.chat_ai_engine  # For backward compatibility
        
        # Warm up Chat AI cache in the background so the app won't wait for it
        asyncio.create_task(self.chat_ai_engine.warm_up_cache())
        log.info("Chat AI engine initialized (cache warming up in background)", provider=settings.chat_provider.value, model=settings.chat_model)

        # Initialize Enrichment Rate Limiter and AI Engine
        self.enrich_rate_limiter = RateLimiter(
            requests_per_minute=settings.enrich_rate_limit,
            daily_limit=settings.enrich_daily_limit
        )
        self.enrich_ai_engine = create_ai_engine(
            provider=settings.enrich_provider,
            api_key=settings.enrich_api_key,
            model_name=settings.enrich_model,
            rate_limiter=self.enrich_rate_limiter,
            cache_repo=cache_repo
        )
        self.enricher = ListingEnricher(self.enrich_ai_engine)
        log.info("Enrichment AI engine initialized", provider=settings.enrich_provider.value, model=settings.enrich_model)
        
        # Initialize Geo Grounding AI Engine (configurable via settings.GEO_GROUNDING_MODEL)
        self.geo_grounding_rate_limiter = RateLimiter(
            requests_per_minute=settings.GEMINI_RPM_LIMIT,
            daily_limit=settings.GEMINI_DAILY_LIMIT
        )
        from config import AIProvider
        self.geo_grounding_ai_engine = create_ai_engine(
            provider=AIProvider.GEMINI,
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEO_GROUNDING_MODEL,
            rate_limiter=self.geo_grounding_rate_limiter,
            cache_repo=cache_repo
        )
        log.info("Geo Grounding AI engine initialized", provider="gemini", model=settings.GEO_GROUNDING_MODEL)
        
        # Set self.rate_limiter (used by scheduler) to the enrich rate limiter
        self.rate_limiter = self.enrich_rate_limiter

        # Initialize matcher
        self.matcher = ZeroAIUserMatcher()
        
        # Initialize scrapers
        anti_detection = AntiDetectionModule(
            min_delay=settings.MIN_DELAY_SECONDS,
            max_delay=settings.MAX_DELAY_SECONDS
        )
        
        # Determine Healer AI Engine
        healer_engine = self.enrich_ai_engine
        if settings.SELF_HEALING_AI_PROVIDER or settings.SELF_HEALING_MODEL:
            healer_provider = settings.SELF_HEALING_AI_PROVIDER or settings.enrich_provider
            healer_model = settings.SELF_HEALING_MODEL or settings.enrich_model
            
            # Select correct API key for the healer provider
            healer_api_key = settings.get_provider_api_key(healer_provider)
            
            log.info("Creating dedicated AI engine for scraper self-healing", provider=healer_provider.value, model=healer_model)
            healer_engine = create_ai_engine(
                provider=healer_provider,
                api_key=healer_api_key,
                model_name=healer_model
            )
            
        # Load Facebook groups from DB, seeding with config defaults if empty
        from database.repositories.facebook_group_repository import FacebookGroupRepository
        from models.facebook_group import FacebookGroup
        fb_group_repo = FacebookGroupRepository(db_manager)
        db_groups = await fb_group_repo.get_all_groups()
        if not db_groups:
            log.info("Facebook groups table is empty. Seeding from settings.facebook_groups...")
            for url in settings.facebook_groups:
                await fb_group_repo.create(FacebookGroup(url=url))
            db_groups = await fb_group_repo.get_all_groups()
            
        group_urls = [g.url for g in db_groups]
        
        self.facebook_scraper = FacebookScraper(
            group_urls=group_urls,
            anti_detection=anti_detection,
            is_seen_callback=seen_repo.is_seen,
            duplicate_check_callback=seen_repo.find_duplicate_by_fingerprint,
            ai_engine=healer_engine
        )
        
        # Initialize Yad2 scraper (Playwright or HTTP based on config)
        if settings.YAD2_USE_PLAYWRIGHT:
            log.info("Using Playwright-based Yad2 scraper (recommended)")
            self.yad2_scraper = Yad2PlaywrightScraper(
                anti_detection=anti_detection
            )
        else:
            log.info("Using HTTP-based Yad2 scraper (might encounter CAPTCHAs)")
            self.yad2_scraper = Yad2Scraper(
                anti_detection=anti_detection
            )
        log.info("Scrapers initialized")
        
        # Initialize Telegram bot (uses chat_ai_engine)
        self.bot = ApartmentBot(ai_engine=self.chat_ai_engine)
        self.bot.app_instance = self
        
        # Initialize Processing Service (uses chat_ai_engine for sass/dialogue)
        self.processing_service = ProcessingService(self.bot, self.chat_ai_engine)
        self.bot.processing_service = self.processing_service  # Inject into bot
        
        await self.bot.setup()
        log.info("Telegram bot initialized")
        
        # Bind bot to the admin error notification handler
        from utils.admin_notifier import admin_notifier_handler
        admin_notifier_handler.set_bot(self.bot)
        
        # Inject bot into Facebook scraper for Telegram-based logins
        if self.facebook_scraper:
            self.facebook_scraper.bot = self.bot
        
        # Initialize scheduler
        self.scheduler = QuotaAwareScheduler(
            process_callback=self.run_processing_cycle,
            rate_limiter=self.rate_limiter
        )
        log.info("Scheduler initialized")
    
    async def run_cleanup(self):
        """Run database cleanup to remove old data."""
        log.info("Running database cleanup")
        db = await get_db()
        
        seen_repo = SeenListingsRepository(db)
        listing_repo = ListingRepository(db)
        rejection_repo = RejectionRepository(db)
        
        # Clean up old data (keep 7 days)
        await seen_repo.cleanup_old_entries(days_to_keep=7)
        await listing_repo.cleanup_old_listings(days_to_keep=7)
        await rejection_repo.delete_old_rejections(older_than_days=7)
        
        # Clean up old screenshots (using configured age, defaults to 24 hours)
        try:
            from utils.screenshot_utils import cleanup_old_screenshots
            cleanup_old_screenshots()
        except Exception as e:
            log.warning(f"Error cleaning up old screenshots: {e}")
            
        log.info("Cleanup complete")
    
    async def reload_facebook_groups(self):
        """Reload Facebook group URLs from the database and update the scraper."""
        if not self.facebook_scraper:
            return
        db = await get_db()
        from database.repositories.facebook_group_repository import FacebookGroupRepository
        fb_group_repo = FacebookGroupRepository(db)
        db_groups = await fb_group_repo.get_all_groups()
        group_urls = [g.url for g in db_groups]
        self.facebook_scraper.group_urls = group_urls
        log.info("Facebook groups reloaded from database", count=len(group_urls))
    
    async def process_enrich_and_notify_batch(self, batch_listings: List[Listing]):
        """Enrich, validate, geo-resolve, deduplicate, save, and match a batch of listings."""
        if not batch_listings:
            return
            
        log.info(f"Processing and enriching batch of {len(batch_listings)} listings")
        db = await get_db()
        seen_repo = SeenListingsRepository(db)
        listing_repo = ListingRepository(db)
        
        # Phase 2: Enrich with AI (ONE batch call)
        enriched_listings = await self.enricher.enrich_listings(batch_listings)
        
        # Mark as seen
        await seen_repo.mark_many_seen(batch_listings)
        
        # Cache enriched listings and save fingerprints
        valid_price_listings = []
        
        for enriched in enriched_listings:
            # VALIDATION: Drop listings with no price
            if enriched.extracted_price is None or enriched.extracted_price == 0:
                raw_preview = enriched.listing.raw_text[:200].replace('\n', ' ') if enriched.listing.raw_text else 'N/A'
                log.warning(
                    f"Dropping invalid listing (no price): {enriched.listing.title[:30]}...", 
                    id=enriched.listing.id,
                    scraped_price=enriched.listing.price,
                    ai_price=enriched.extracted_price,
                    raw_text_preview=raw_preview
                )
                continue
            valid_price_listings.append(enriched)
            
        # Self-heal locations in parallel if uncertain
        from utils.israeli_locations import get_location_db
        loc_db = get_location_db()
        
        healing_tasks = []
        heal_targets = []
        
        for enriched in valid_price_listings:
            location_signals = []
            if enriched.extracted_neighborhood:
                location_signals.append(enriched.extracted_neighborhood)
            if enriched.extracted_street:
                location_signals.append(enriched.extracted_street)
                
            # Include all parsed mentioned areas (excluding generic city names)
            city_names = {"תל אביב", "תל אביב יפו", "תל אביב-יפו", "tel aviv"}
            if enriched.area_matches:
                for area in enriched.area_matches.keys():
                    if area.strip() and area.strip().lower() not in city_names:
                        location_signals.append(area.strip())
                        
            location_signals.append(enriched.extracted_location or enriched.listing.location)
            
            listing_loc = ", ".join(location_signals)
            
            norm = loc_db.normalize_location(listing_loc)
            
            if norm["neighborhood"]:
                # Successfully resolved via database schema lookup (including custom schema)
                enriched.extracted_neighborhood = norm["neighborhood"]
                if norm["city"]:
                    enriched.extracted_location = norm["city"]
            elif self.geo_grounding_ai_engine:
                log.info(
                    f"Location uncertainty detected for listing {enriched.listing.id[:8]} ('{listing_loc}'). Preparing parallel AI location self-healing..."
                )
                details = f"Title: {enriched.listing.title}\nDescription: {enriched.listing.description}"
                task = loc_db.async_resolve_unknown_location(
                    raw_location=listing_loc,
                    listing_details=details,
                    ai_engine=self.geo_grounding_ai_engine
                )
                healing_tasks.append(task)
                heal_targets.append((enriched, listing_loc))
                
        if healing_tasks:
            healed_results = await asyncio.gather(*healing_tasks, return_exceptions=True)
            for (enriched, listing_loc), result in zip(heal_targets, healed_results):
                if isinstance(result, Exception):
                    log.error(f"Failed to resolve unknown location via AI self-healing for listing {enriched.listing.id[:8]}: {result}")
                elif result and result.get("neighborhood"):
                    log.info(
                        f"Location self-healed successfully for listing {enriched.listing.id[:8]} -> '{result['neighborhood']}'"
                    )
                    enriched.extracted_neighborhood = result["neighborhood"]
                    if result.get("city"):
                        enriched.extracted_location = result["city"]
                        
        valid_enriched_listings = []
        cross_source_duplicates_post = 0
        
        for enriched in valid_price_listings:
            # Post-Enrichment Fingerprint Deduplication
            duplicate_info = await seen_repo.find_duplicate_by_fingerprint(enriched.listing, enriched)
            if duplicate_info:
                duplicate_id, matched_fields = duplicate_info
                cross_source_duplicates_post += 1
                log.info(
                    f"Cross-source duplicate detected (post-enrichment)",
                    current_listing_id=enriched.listing.id[:8],
                    current_source=enriched.listing.source,
                    current_phone=enriched.listing.phone,
                    current_price=enriched.extracted_price,
                    matched_listing_id=duplicate_id[:8],
                    matched_fields=matched_fields,
                )
                # Mark as seen to avoid reprocessing
                await seen_repo.mark_seen(enriched.listing)
                continue
                
            valid_enriched_listings.append(enriched)
            await listing_repo.save_enriched(enriched)
            
            # Save fingerprint immediately so the next listing in this loop can match against it
            await seen_repo.save_fingerprint(enriched.listing, enriched)
            
        if cross_source_duplicates_post > 0:
            log.info(f"Filtered {cross_source_duplicates_post} cross-source duplicate(s) after enrichment")
            
        if not valid_enriched_listings:
            log.info("No valid listings after enrichment in this batch")
            return
        
        # Phase 3: Match and Notify
        await self.processing_service.process_cycle(valid_enriched_listings)

    async def run_processing_cycle(self):
        """Run a complete processing cycle: scrape -> enrich -> match -> notify."""
        log.info("Starting processing cycle")
        
        # Reload Facebook groups to ensure correct dynamic order
        await self.reload_facebook_groups()
        
        db = await get_db()
        seen_repo = SeenListingsRepository(db)
        
        # Phase 1: Scrape all sources concurrently
        import time
        
        start_fb = time.perf_counter()
        start_yad2 = time.perf_counter()
        
        fb_listings = []
        yad2_listings = []
        fb_failed = False
        yad2_failed = False
        
        # State for accumulating new unique listings across both scrapers
        accumulating_listings = []
        seen_ids_in_cycle = set()
        lock = asyncio.Lock()
        
        fb_new_count = 0
        yad2_new_count = 0
        
        background_tasks = set()
        
        async def run_batch_in_background(batch):
            try:
                await self.process_enrich_and_notify_batch(batch)
            except Exception as e:
                log.error(f"Error in background batch processing: {e}", exc_info=True)

        def start_background_batch(batch):
            task = asyncio.create_task(run_batch_in_background(batch))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        
        async def on_listing_scraped(listing: Listing):
            nonlocal fb_new_count, yad2_new_count
            
            # Check if this listing was already seen in previous cycles
            is_in_db = await seen_repo.is_seen(listing.id)
            if is_in_db:
                return
                
            batch_to_process = []
            async with lock:
                # Deduplicate within the current cycle
                if listing.id in seen_ids_in_cycle:
                    return
                seen_ids_in_cycle.add(listing.id)
                
                # Check pre-enrichment fingerprint duplicate detection
                duplicate_info = await seen_repo.find_duplicate_by_fingerprint(listing)
                if duplicate_info:
                    duplicate_id, matched_fields = duplicate_info
                    log.info(
                         f"Cross-source duplicate detected (pre-enrichment)",
                        current_listing_id=listing.id[:8],
                        current_source=listing.source,
                        current_author=listing.author[:20] if listing.author else None,
                        current_phone=listing.phone,
                        current_price=listing.price,
                        current_bedrooms=listing.bedrooms,
                        matched_listing_id=duplicate_id[:8],
                        matched_fields=matched_fields,
                    )
                    await seen_repo.mark_seen(listing)
                    return
                
                # It is a fresh unique listing!
                if listing.source == "facebook":
                    fb_new_count += 1
                elif listing.source == "yad2":
                    yad2_new_count += 1
                
                accumulating_listings.append(listing)
                if len(accumulating_listings) >= self.enricher.batch_size:
                    batch_to_process = list(accumulating_listings)
                    accumulating_listings.clear()
            
            if batch_to_process:
                start_background_batch(batch_to_process)
                    
        async def on_group_completed(group_url: str, group_listings: List[Listing]):
            # 1. Update database with count of scraped listings
            try:
                db_manager = await get_db()
                from database.repositories.facebook_group_repository import FacebookGroupRepository
                fb_group_repo = FacebookGroupRepository(db_manager)
                await fb_group_repo.update_scraped_count(group_url, len(group_listings))
                log.info(f"Updated database: group {group_url} scraped count = {len(group_listings)}")
            except Exception as e:
                log.error(f"Failed to update group scraped count in DB: {e}", exc_info=True)
                
            # 2. Immediately flush and process any new listings from this group
            nonlocal accumulating_listings
            batch_to_process = []
            async with lock:
                if accumulating_listings:
                    batch_to_process = list(accumulating_listings)
                    accumulating_listings.clear()
                    
            if batch_to_process:
                log.info(f"Group scraping complete ({group_url}). Flushing batch of {len(batch_to_process)} listings in background.")
                start_background_batch(batch_to_process)
        
        # Run scrapers concurrently
        fb_task = asyncio.create_task(self.facebook_scraper.scrape(
            on_listing_scraped=on_listing_scraped,
            on_group_completed=on_group_completed
        ))
        yad2_task = asyncio.create_task(self.yad2_scraper.scrape(on_listing_scraped=on_listing_scraped))
        
        fb_res, yad2_res = await asyncio.gather(fb_task, yad2_task, return_exceptions=True)
        
        duration_fb = time.perf_counter() - start_fb
        duration_yad2 = time.perf_counter() - start_yad2
        
        if isinstance(fb_res, Exception):
            fb_failed = True
            log.error(f"Facebook scrape failed: {fb_res}")
            telemetry.track_error("facebook_scraper", type(fb_res).__name__)
        else:
            fb_listings = fb_res
            log.info(f"Facebook: {len(fb_listings)} listings")
            
        if isinstance(yad2_res, Exception):
            yad2_failed = True
            log.error(f"Yad2 scrape failed: {yad2_res}")
            telemetry.track_error("yad2_scraper", type(yad2_res).__name__)
        else:
            yad2_listings = yad2_res
            log.info(f"Yad2: {len(yad2_listings)} listings")
            
        # Flush any remaining listings
        async with lock:
            remaining_batch = list(accumulating_listings)
            accumulating_listings.clear()
            
        if remaining_batch:
            log.info(f"Flushing remaining {len(remaining_batch)} listings at end of cycle")
            start_background_batch(remaining_batch)
            
        # Wait for all background enrichment and notifications to finish before declaring cycle complete
        if background_tasks:
            log.info(f"Waiting for {len(background_tasks)} background enrichment/matching task(s) to finish...")
            await asyncio.gather(*background_tasks, return_exceptions=True)
            
        # Track scrape details with actual new counts
        telemetry.track_scrape("facebook", duration_fb, len(fb_listings), fb_new_count, failed=fb_failed)
        telemetry.track_scrape("yad2", duration_yad2, len(yad2_listings), yad2_new_count, failed=yad2_failed)
        
        log.info("Processing cycle complete")
    
    async def start(self):
        """Start the application."""
        log.info("Starting Apartment Bot Application")
        self._running = True
        
        # Start bot
        await self.bot.run()
        
        # Start scheduler
        self.scheduler.start()
        
        # Schedule daily cleanup
        from apscheduler.triggers.interval import IntervalTrigger
        self.scheduler.scheduler.add_job(
            self.run_cleanup,
            IntervalTrigger(days=1),
            id='daily_cleanup',
            name='Daily database cleanup'
        )
        
        log.info("Application started successfully")
        log.info(f"Scraping interval: {settings.SCRAPE_INTERVAL_MINUTES} minutes")
        
        # Keep running
        while self._running:
            await asyncio.sleep(1)
    
    async def stop(self):
        """Stop the application."""
        log.info("Stopping application")
        self._running = False
        
        if self.scheduler:
            self.scheduler.stop()
        
        if self.bot:
            await self.bot.stop()
        
        db = await get_db()
        await db.close()
        
        log.info("Application stopped")


async def main():
    """Main entry point."""
    app = ApartmentBotApplication()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        log.info("Shutdown signal received")
        asyncio.create_task(app.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    try:
        await app.initialize()
        await app.start()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
    except Exception as e:
        log.critical(f"Application error: {e}")
        raise
    finally:
        await app.stop()


if __name__ == "__main__":
    print("🏠 Apartment Search Bot starting...")
    print("Press Ctrl+C to stop")
    asyncio.run(main())
