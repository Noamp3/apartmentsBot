import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from database.repositories.system_repository import SystemRepository
from scrapers.scheduler import ScrapingScheduler, QuotaAwareScheduler
from config import settings


@pytest.mark.asyncio
async def test_system_repository_settings(db):
    """Test saving and retrieving system settings in SystemRepository."""
    repo = SystemRepository(db)
    
    # Defaults
    assert await repo.get_scrape_interval() is None
    assert await repo.get_auto_adjust_interval() is True
    
    # Save & retrieve interval
    await repo.set_scrape_interval(45)
    assert await repo.get_scrape_interval() == 45
    
    # Save & retrieve auto adjust
    await repo.set_auto_adjust_interval(False)
    assert await repo.get_auto_adjust_interval() is False
    
    await repo.set_auto_adjust_interval(True)
    assert await repo.get_auto_adjust_interval() is True


@pytest.mark.asyncio
async def test_system_repository_scraping_runs(db):
    """Test starting, completing, and retrieving scraping runs."""
    repo = SystemRepository(db)
    
    # Get last run when none exist
    assert await repo.get_last_run() is None
    
    # Start a run
    run_id = await repo.start_scraping_run()
    assert run_id > 0
    
    # Verify it is listed as running
    last_run = await repo.get_last_run()
    assert last_run is not None
    assert last_run["id"] == run_id
    assert last_run["status"] == "running"
    assert last_run["fb_total"] == 0
    assert bool(last_run["fb_failed"]) is False
    
    # Complete the run
    await repo.complete_scraping_run(
        run_id=run_id,
        fb_total=12,
        fb_new=3,
        fb_failed=False,
        yad2_total=8,
        yad2_new=1,
        yad2_failed=True,
        status="partial_success",
        duration_seconds=42.5,
        error_message="Yad2 failed connection"
    )
    
    # Verify updated values
    last_run = await repo.get_last_run()
    assert last_run is not None
    assert last_run["id"] == run_id
    assert last_run["status"] == "partial_success"
    assert last_run["fb_total"] == 12
    assert last_run["fb_new"] == 3
    assert bool(last_run["fb_failed"]) is False
    assert last_run["yad2_total"] == 8
    assert last_run["yad2_new"] == 1
    assert bool(last_run["yad2_failed"]) is True
    assert last_run["duration_seconds"] == 42.5
    assert last_run["error_message"] == "Yad2 failed connection"


@pytest.mark.asyncio
async def test_scheduler_update_interval():
    """Test that update_interval correctly reschedules the APScheduler job."""
    callback = MagicMock()
    scheduler = ScrapingScheduler(process_callback=callback)
    
    # Mock APScheduler job reschedule
    mock_job = MagicMock()
    scheduler.scheduler.get_job = MagicMock(return_value=mock_job)
    scheduler._running = True
    
    scheduler.update_interval(15)
    
    assert scheduler.interval == 15
    scheduler.scheduler.get_job.assert_called_with('main_cycle')
    mock_job.reschedule.assert_called_once()
    
    # Verify rescheduling triggers IntervalTrigger
    args, kwargs = mock_job.reschedule.call_args
    trigger = kwargs["trigger"]
    assert trigger is not None


@pytest.mark.asyncio
async def test_quota_aware_scheduler_auto_adjust():
    """Test that QuotaAwareScheduler respects the auto_adjust flag."""
    callback = MagicMock()
    rate_limiter = MagicMock()
    
    # Mock quota remaining
    rate_limiter.get_remaining_quota.return_value = {"daily_remaining": 50}
    rate_limiter.daily_reset = datetime.now() + timedelta(hours=5)
    
    scheduler = QuotaAwareScheduler(process_callback=callback, rate_limiter=rate_limiter)
    scheduler.update_interval = MagicMock()
    
    # Case 1: auto_adjust is True -> calculate_optimal_interval and update_interval are called
    scheduler.auto_adjust = True
    with patch.object(scheduler, 'calculate_optimal_interval', return_value=12) as mock_calc:
        await scheduler._run_cycle()
        mock_calc.assert_called_once()
        scheduler.update_interval.assert_called_with(12)
        
    # Reset mock
    scheduler.update_interval.reset_mock()
    
    # Case 2: auto_adjust is False -> calculate_optimal_interval and update_interval are skipped
    scheduler.auto_adjust = False
    with patch.object(scheduler, 'calculate_optimal_interval', return_value=12) as mock_calc:
        await scheduler._run_cycle()
        mock_calc.assert_not_called()
        scheduler.update_interval.assert_not_called()
