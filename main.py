# main.py
"""Main entry point for the Apartment Search Bot."""

import asyncio
import signal
from typing import Dict, List

from config import settings
from utils.logger import LoggerFactory, Loggers
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
from models.listing import EnrichedListing

# Initialize logging
LoggerFactory.initialize(debug=settings.DEBUG)
log = Loggers.app()


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
            
        self.facebook_scraper = FacebookScraper(
            group_urls=settings.facebook_groups,
            anti_detection=anti_detection,
            is_seen_callback=seen_repo.is_seen,
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
        
        log.info("Cleanup complete")
    
    async def run_processing_cycle(self):
        """Run a complete processing cycle: scrape -> enrich -> match -> notify."""
        log.info("Starting processing cycle")
        
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        seen_repo = SeenListingsRepository(db)
        listing_repo = ListingRepository(db)
        rejection_repo = RejectionRepository(db)
        
        # Phase 1: Scrape all sources
        all_listings = []
        
        try:
            fb_listings = await self.facebook_scraper.scrape()
            all_listings.extend(fb_listings)
            log.info(f"Facebook: {len(fb_listings)} listings")
        except Exception as e:
            log.error(f"Facebook scrape failed: {e}")
        
        try:
            yad2_listings = await self.yad2_scraper.scrape()
            all_listings.extend(yad2_listings)
            log.info(f"Yad2: {len(yad2_listings)} listings")
        except Exception as e:
            log.error(f"Yad2 scrape failed: {e}")
        
        if not all_listings:
            log.info("No listings found, ending cycle")
            return
        
        # Filter out already-seen listings
        new_listings = await seen_repo.filter_new(all_listings)
        duplicate_count = len(all_listings) - len(new_listings)
        
        if duplicate_count > 0:
            log.info(f"Processing listings: {len(new_listings)} new, {duplicate_count} skipped (already seen)")
        else:
            log.info(f"Processing listings: {len(new_listings)} new (all fresh)")
        
        if not new_listings:
            return
        
        # Check for cross-source duplicates using fingerprints (pre-enrichment)
        non_duplicate_listings = []
        cross_source_duplicates_pre = 0
        
        for listing in new_listings:
            # Check if this listing duplicates an existing one from another source
            duplicate_info = await seen_repo.find_duplicate_by_fingerprint(listing)
            
            if duplicate_info:
                duplicate_id, matched_fields = duplicate_info
                cross_source_duplicates_pre += 1
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
                # Mark as seen to avoid reprocessing
                await seen_repo.mark_seen(listing)
            else:
                non_duplicate_listings.append(listing)
        
        if cross_source_duplicates_pre > 0:
            log.info(f"Filtered {cross_source_duplicates_pre} cross-source duplicate(s) before enrichment")
        
        if not non_duplicate_listings:
            log.info("All listings were duplicates, ending cycle")
            return
            
        # Deduplicate results from different scrapers/pages
        seen_in_cycle = set()
        unique_new_listings = []
        for l in non_duplicate_listings:
            if l.id not in seen_in_cycle:
                unique_new_listings.append(l)
                seen_in_cycle.add(l.id)
                
        if len(unique_new_listings) < len(non_duplicate_listings):
            log.info(f"Deduplicated cycle batch: {len(non_duplicate_listings)} -> {len(unique_new_listings)}")
        
        # Phase 2: Enrich with AI (ONE batch call)
        enriched_listings = await self.enricher.enrich_listings(unique_new_listings)
        
        # Mark as seen
        await seen_repo.mark_many_seen(unique_new_listings)
        
        # Cache enriched listings and save fingerprints
        saved_enriched_count = 0
        valid_enriched_listings = []
        cross_source_duplicates_post = 0
        
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
            saved_enriched_count += 1
            
        if cross_source_duplicates_post > 0:
            log.info(f"Filtered {cross_source_duplicates_post} cross-source duplicate(s) after enrichment")
            
        if not valid_enriched_listings:
            log.info("No valid listings after enrichment (all dropped due to missing data or post-enrichment duplicates)")
            return
        
        # Phase 3: Match and Notify
        await self.processing_service.process_cycle(valid_enriched_listings)
        
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
