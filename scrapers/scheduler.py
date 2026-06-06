# scrapers/scheduler.py
"""Scheduling for periodic scraping tasks."""

from datetime import datetime, timedelta
from typing import Callable, List, Optional, Awaitable, Any
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from utils.logger import Loggers

log = Loggers.scheduler()


class ScrapingScheduler:
    """Manages periodic scraping tasks with staggered execution."""
    
    def __init__(
        self,
        process_callback: Callable[[], Awaitable[None]],
        interval_minutes: Optional[int] = None
    ):
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler()
        self.process_callback: Callable[[], Awaitable[None]] = process_callback
        self.interval: int = interval_minutes or settings.SCRAPE_INTERVAL_MINUTES
        self._running: bool = False
        
        # Blackout period state
        self._blackout_jitter_start = 0
        self._blackout_jitter_end = 0
        self._jitter_day = None
    
    def start(self):
        """Start the scheduler."""
        if self._running:
            log.warning("Scheduler already running")
            return
        
        # Add main processing job
        self.scheduler.add_job(
            self._run_cycle,
            IntervalTrigger(
                minutes=self.interval,
                jitter=settings.SCRAPE_JITTER_SECONDS
            ),
            id='main_cycle',
            name='Main scraping cycle',
            next_run_time=datetime.now() + timedelta(seconds=10)  # Start soon
        )
        
        self.scheduler.start()
        self._running = True
        log.info(f"Scheduler started", interval_minutes=self.interval)
    
    def stop(self):
        """Stop the scheduler."""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            log.info("Scheduler stopped")
    
    async def _run_cycle(self):
        """Run a single processing cycle."""
        if self._is_blackout_period():
            return
            
        log.info("Starting scraping cycle")
        start_time = datetime.now()
        
        try:
            await self.process_callback()
            
            duration = (datetime.now() - start_time).total_seconds()
            log.info("Scraping cycle complete", duration_seconds=round(duration, 1))
            
        except Exception as e:
            log.exception("Scraping cycle failed", error=str(e))
    
    def get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        job = self.scheduler.get_job('main_cycle')
        return job.next_run_time if job else None
    
    def trigger_now(self):
        """Trigger an immediate run."""
        asyncio.create_task(self._run_cycle())
        log.info("Manual cycle triggered")

    def _is_blackout_period(self) -> bool:
        """Check if current time is within the blackout period."""
        now = datetime.now()
        current_day = now.date()
        
        # Refresh jitter if it's a new day
        if self._jitter_day != current_day:
            self._refresh_blackout_jitter(current_day)
            
        # Calculate current blackout window with jitter
        # We assume Israel time is system time (confirmed during planning)
        start_hour = settings.BLACKOUT_START_HOUR
        end_hour = settings.BLACKOUT_END_HOUR
        
        # Create datetime objects for the window
        # Note: If start > end, it crosses midnight (e.g., 11 PM to 4 AM)
        # But here it's 1 AM to 7 AM, so it's simple.
        
        blackout_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + \
                        timedelta(minutes=self._blackout_jitter_start)
                        
        blackout_end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0) + \
                      timedelta(minutes=self._blackout_jitter_end)
                      
        if blackout_start <= now <= blackout_end:
            log.info("Skipping cycle: Current time is within blackout period", 
                     now=now.strftime("%H:%M"),
                     blackout_start=blackout_start.strftime("%H:%M"),
                     blackout_end=blackout_end.strftime("%H:%M"))
            return True
            
        return False

    def _refresh_blackout_jitter(self, day):
        """Randomize blackout jitter for the given day."""
        import random
        max_jitter = settings.BLACKOUT_JITTER_MINUTES
        self._blackout_jitter_start = random.randint(-max_jitter, max_jitter)
        self._blackout_jitter_end = random.randint(-max_jitter, max_jitter)
        self._jitter_day = day
        
        log.info("Refreshed blackout jitter for the day",
                 day=day.isoformat(),
                 start_jitter_mins=self._blackout_jitter_start,
                 end_jitter_mins=self._blackout_jitter_end)


class QuotaAwareScheduler(ScrapingScheduler):
    """Scheduler that adapts to API quota availability."""
    
    DEFAULT_UNLIMITED_INTERVAL = 5
    LOW_QUOTA_THRESHOLD = 10
    LOW_QUOTA_INTERVAL = 30
    MAX_INTERVAL = 15
    MIN_INTERVAL = 5
    ESTIMATED_CALLS_PER_CYCLE = 6
    MIN_DAILY_REMAINING_QUOTA = 20
    
    def __init__(
        self,
        process_callback: Callable[[], Awaitable[None]],
        rate_limiter: Any,
        target_cycles_per_day: int = 200
    ):
        super().__init__(process_callback)
        self.rate_limiter = rate_limiter
        self.target_cycles_per_day = target_cycles_per_day
    
    def calculate_optimal_interval(self) -> int:
        """Calculate optimal minutes between cycles based on quota."""
        quota = self.rate_limiter.get_remaining_quota()
        daily_remaining = quota["daily_remaining"]
        
        # Handle unlimited quota (e.g., OpenAI models without daily limits)
        if not isinstance(daily_remaining, (int, float)):
            return self.DEFAULT_UNLIMITED_INTERVAL
        
        hours_remaining = (self.rate_limiter.daily_reset - datetime.now()).seconds / 3600
        
        if hours_remaining <= 0:
            return self.DEFAULT_UNLIMITED_INTERVAL
        
        # Calculate how many cycles we can do
        remaining_cycles = daily_remaining / self.ESTIMATED_CALLS_PER_CYCLE
        
        if remaining_cycles < self.LOW_QUOTA_THRESHOLD:
            log.warning("Low quota - extending intervals",
                       remaining_cycles=remaining_cycles)
            return self.LOW_QUOTA_INTERVAL
        
        # Distribute remaining cycles across remaining hours
        cycles_per_hour = remaining_cycles / hours_remaining
        
        minutes_between_cycles = max(self.MIN_INTERVAL, int(60 / cycles_per_hour))
        
        return min(minutes_between_cycles, self.MAX_INTERVAL)
    
    async def _run_cycle(self):
        """Run cycle with quota awareness."""
        # Check quota before running
        quota = self.rate_limiter.get_remaining_quota()
        daily_remaining = quota["daily_remaining"]
        
        # Skip quota check for unlimited-quota providers
        if isinstance(daily_remaining, (int, float)) and daily_remaining < self.MIN_DAILY_REMAINING_QUOTA:
            log.warning("Quota too low, skipping cycle",
                       daily_remaining=daily_remaining)
            return
        
        await super()._run_cycle()
        
        # Adjust next interval based on remaining quota
        new_interval = self.calculate_optimal_interval()
        if new_interval != self.interval:
            self.interval = new_interval
            log.info(f"Adjusted interval to {new_interval} minutes")
