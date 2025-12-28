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
from scrapers import FacebookScraper, Yad2Scraper, AntiDetectionModule
from scrapers.scheduler import QuotaAwareScheduler
from bot import ApartmentBot
from models.listing import EnrichedListing

# Initialize logging
LoggerFactory.initialize(debug=settings.DEBUG)
log = Loggers.scheduler()


class ApartmentBotApplication:
    """Main application class that wires everything together."""
    
    def __init__(self):
        self.bot: ApartmentBot = None
        self.scheduler: QuotaAwareScheduler = None
        self.ai_engine = None  # BaseAIEngine
        self.rate_limiter: RateLimiter = None
        self.enricher: ListingEnricher = None
        self.matcher: ZeroAIUserMatcher = None
        
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
        
        # Initialize AI engine (uses settings.AI_PROVIDER)
        self.ai_engine = create_ai_engine()
        self.rate_limiter = RateLimiter()  # Rate limiter for quota management
        self.enricher = ListingEnricher(self.ai_engine)
        log.info(f"AI engine initialized", provider=settings.AI_PROVIDER.value)
        
        # Initialize matcher
        self.matcher = ZeroAIUserMatcher()
        
        # Initialize scrapers
        anti_detection = AntiDetectionModule(
            min_delay=settings.MIN_DELAY_SECONDS,
            max_delay=settings.MAX_DELAY_SECONDS
        )
        
        self.facebook_scraper = FacebookScraper(
            group_urls=settings.facebook_groups,
            anti_detection=anti_detection
        )
        
        self.yad2_scraper = Yad2Scraper(
            anti_detection=anti_detection
        )
        log.info("Scrapers initialized")
        
        # Initialize Telegram bot
        self.bot = ApartmentBot(ai_engine=self.ai_engine)
        await self.bot.setup()
        log.info("Telegram bot initialized")
        
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
        log.info(f"New listings: {len(new_listings)} of {len(all_listings)}")
        
        if not new_listings:
            return
        
        # Phase 2: Enrich with AI (ONE batch call)
        enriched_listings = await self.enricher.enrich_listings(new_listings)
        
        # Mark as seen
        await seen_repo.mark_many_seen(new_listings)
        
        # Cache enriched listings
        for enriched in enriched_listings:
            await listing_repo.save_enriched(enriched)
        
        # Phase 3: Match to all users
        users = await user_repo.get_all_active()
        log.info(f"Matching against {len(users)} users")
        
        for user in users:
            try:
                rules = await rule_repo.get_user_rules(user.telegram_id)
                if not rules:
                    continue
                
                # For new users, only send listings from the last 24 hours
                # After first notification, they only receive truly new listings
                listings_for_user = enriched_listings
                if user.is_new_user:
                    # Get recent listings for new user (max 24 hours old)
                    listings_for_user = await listing_repo.get_recent_for_new_user(
                        max_age_hours=24, limit=20
                    )
                    log.info(f"New user {user.telegram_id}: sending up to {len(listings_for_user)} recent listings")
                
                notifications_sent = 0
                for enriched in listings_for_user:
                    try:
                        is_match, reasons = self.matcher.evaluate_listing(enriched, rules)
                        
                        if is_match:
                            # Send notification
                            await self.bot.send_listing_notification(
                                chat_id=user.chat_id,
                                enriched=enriched
                            )
                            notifications_sent += 1
                        else:
                            # Log rejection
                            await rejection_repo.log_rejection(
                                listing_id=enriched.listing.id,
                                user_id=user.telegram_id,
                                failed_rules=[r.value for r in rules if not is_match],
                                reasons=reasons,
                                listing_url=enriched.listing.url,
                                listing_price=enriched.extracted_price,
                                listing_location=enriched.extracted_location,
                                match_method="attribute"
                            )
                    except Exception as e:
                        log.error(f"Error processing listing {enriched.listing.id} for user {user.telegram_id}: {e}")
                        continue
                
                # Mark first notification if any were sent
                if notifications_sent > 0 and user.is_new_user:
                    await user_repo.mark_first_notification(user.telegram_id)
                    log.info(f"Marked first notification for user {user.telegram_id}")

            except Exception as e:
                log.error(f"Error processing user {user.telegram_id}: {e}")
                continue
        
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
