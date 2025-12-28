# scrapers/scheduler.py
"""Scheduling for periodic scraping tasks."""

from datetime import datetime, timedelta
from typing import Callable, List, Optional
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
        process_callback: Callable,
        interval_minutes: int = None
    ):
        self.scheduler = AsyncIOScheduler()
        self.process_callback = process_callback
        self.interval = interval_minutes or settings.SCRAPE_INTERVAL_MINUTES
        self._running = False
    
    def start(self):
        """Start the scheduler."""
        if self._running:
            log.warning("Scheduler already running")
            return
        
        # Add main processing job
        self.scheduler.add_job(
            self._run_cycle,
            IntervalTrigger(minutes=self.interval),
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
        log.info("Starting scraping cycle")
        start_time = datetime.now()
        
        try:
            await self.process_callback()
            
            duration = (datetime.now() - start_time).total_seconds()
            log.info("Scraping cycle complete", duration_seconds=round(duration, 1))
            
        except Exception as e:
            log.error("Scraping cycle failed", error=str(e))
    
    def get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        job = self.scheduler.get_job('main_cycle')
        return job.next_run_time if job else None
    
    def trigger_now(self):
        """Trigger an immediate run."""
        asyncio.create_task(self._run_cycle())
        log.info("Manual cycle triggered")


class QuotaAwareScheduler(ScrapingScheduler):
    """Scheduler that adapts to API quota availability."""
    
    def __init__(
        self,
        process_callback: Callable,
        rate_limiter: 'GeminiRateLimiter',
        target_cycles_per_day: int = 200
    ):
        super().__init__(process_callback)
        self.rate_limiter = rate_limiter
        self.target_cycles_per_day = target_cycles_per_day
    
    def calculate_optimal_interval(self) -> int:
        """Calculate optimal minutes between cycles based on quota."""
        quota = self.rate_limiter.get_remaining_quota()
        hours_remaining = (self.rate_limiter.daily_reset - datetime.now()).seconds / 3600
        
        if hours_remaining <= 0:
            return 5  # New day starting, normal interval
        
        # Estimate calls per cycle (5-7 typically)
        calls_per_cycle = 6
        
        # Calculate how many cycles we can do
        remaining_cycles = quota["daily_remaining"] / calls_per_cycle
        
        if remaining_cycles < 10:
            log.warning("Low quota - extending intervals",
                       remaining_cycles=remaining_cycles)
            return 30  # Long interval when low on quota
        
        # Distribute remaining cycles across remaining hours
        cycles_per_hour = remaining_cycles / hours_remaining
        
        minutes_between_cycles = max(5, int(60 / cycles_per_hour))
        
        return min(minutes_between_cycles, 15)  # Cap at 15 minutes
    
    async def _run_cycle(self):
        """Run cycle with quota awareness."""
        # Check quota before running
        quota = self.rate_limiter.get_remaining_quota()
        
        if quota["daily_remaining"] < 20:
            log.warning("Quota too low, skipping cycle",
                       daily_remaining=quota["daily_remaining"])
            return
        
        await super()._run_cycle()
        
        # Adjust next interval based on remaining quota
        new_interval = self.calculate_optimal_interval()
        if new_interval != self.interval:
            self.interval = new_interval
            log.info(f"Adjusted interval to {new_interval} minutes")
