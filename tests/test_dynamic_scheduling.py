import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

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

    # Save & retrieve AI retries
    assert await repo.get_ai_retries() is None
    await repo.set_ai_retries(25)
    assert await repo.get_ai_retries() == 25


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


@pytest.mark.asyncio
async def test_scheduler_restart_persistence():
    """Test that application start schedules next run based on persisted schedule."""
    from main import ApartmentBotApplication
    
    app = ApartmentBotApplication()
    
    # Mock bot to avoid connecting/running
    app.bot = MagicMock()
    app.bot.run = AsyncMock()
    
    # Mock scheduler
    app.scheduler = MagicMock()
    app.scheduler.interval = 15
    app.scheduler.start = MagicMock()
    
    # Mock database and SystemRepository
    mock_db = MagicMock()
    expected_next_run = datetime.now(timezone(timedelta(hours=3))) + timedelta(minutes=10)
    
    # Patch get_db to return our mock db
    with patch("main.get_db", return_value=mock_db), \
         patch("database.repositories.system_repository.SystemRepository.get_next_scheduled_run_time", return_value=expected_next_run):
         
         # Mock bot.run to set app._running = False so start() loop exits immediately
         async def mock_bot_run():
             app._running = False
         app.bot.run = mock_bot_run
         
         await app.start()
         
         app.scheduler.start.assert_called_once()
         args, kwargs = app.scheduler.start.call_args
         actual_next_run = kwargs.get("next_run_time")
         assert actual_next_run is not None
         assert abs((actual_next_run - expected_next_run).total_seconds()) < 1.0


@pytest.mark.asyncio
async def test_scheduler_restart_persistence_overdue():
    """Test that when the next run time has passed, scheduler is started with immediate run (now + 10s)."""
    from main import ApartmentBotApplication
    
    app = ApartmentBotApplication()
    app.bot = MagicMock()
    
    async def mock_bot_run():
        app._running = False
    app.bot.run = mock_bot_run
    
    app.scheduler = MagicMock()
    app.scheduler.interval = 15
    app.scheduler.start = MagicMock()
    
    mock_db = MagicMock()
    # Next run was scheduled for 5 minutes ago (overdue)
    past_run_time = datetime.now(timezone(timedelta(hours=3))) - timedelta(minutes=5)
    
    with patch("main.get_db", return_value=mock_db), \
         patch("database.repositories.system_repository.SystemRepository.get_next_scheduled_run_time", return_value=past_run_time):
         
         await app.start()
         
         app.scheduler.start.assert_called_once()
         args, kwargs = app.scheduler.start.call_args
         actual_next_run = kwargs.get("next_run_time")
         assert actual_next_run is not None
         # Should be scheduled to run soon (now + 10s)
         expected_next_run = datetime.now() + timedelta(seconds=10)
         assert abs((actual_next_run - expected_next_run).total_seconds()) < 2.0


@pytest.mark.asyncio
async def test_scheduler_restart_persistence_no_previous_runs():
    """Test that if there are no previous runs, scheduler starts with None next_run_time."""
    from main import ApartmentBotApplication
    
    app = ApartmentBotApplication()
    app.bot = MagicMock()
    
    async def mock_bot_run():
        app._running = False
    app.bot.run = mock_bot_run
    
    app.scheduler = MagicMock()
    app.scheduler.interval = 15
    app.scheduler.start = MagicMock()
    
    mock_db = MagicMock()
    
    with patch("main.get_db", return_value=mock_db), \
         patch("database.repositories.system_repository.SystemRepository.get_next_scheduled_run_time", return_value=None):
         
         await app.start()
         
         app.scheduler.start.assert_called_once_with(next_run_time=None)


@pytest.mark.asyncio
async def test_scheduler_persists_run_time():
    """Test that scheduler persists next_run_time to DB on start, update, and cycle."""
    mock_callback = AsyncMock()
    scheduler = ScrapingScheduler(process_callback=mock_callback)
    
    # Mock APScheduler job with next_run_time
    mock_job = MagicMock()
    run_time = datetime.now() + timedelta(minutes=15)
    mock_job.next_run_time = run_time
    scheduler.scheduler.get_job = MagicMock(return_value=mock_job)
    scheduler.scheduler.start = MagicMock()
    
    # Mock DB
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    
    with patch("database.get_db", return_value=mock_db):
        # 1. Test starting the scheduler persists the run time
        scheduler.start(next_run_time=run_time)
        
        # Give asyncio tasks a moment to run
        await asyncio.sleep(0.1)
        
        # Verify set_setting was called with next_scheduled_run_time
        mock_db.execute.assert_called()
        args, kwargs = mock_db.execute.call_args
        sql = args[0]
        params = args[1]
        assert "system_settings" in sql
        assert "next_scheduled_run_time" in params
        assert run_time.isoformat() in params
        
        # Reset mock
        mock_db.execute.reset_mock()
        
        # 2. Test updating interval persists the run time
        scheduler.update_interval(10)
        await asyncio.sleep(0.1)
        
        mock_db.execute.assert_called()
        args, kwargs = mock_db.execute.call_args
        assert "next_scheduled_run_time" in args[1]
        
        # Reset mock
        mock_db.execute.reset_mock()
        
        # 3. Test running cycle persists the run time
        # We need to temporarily set _is_blackout_period to return False
        scheduler._is_blackout_period = MagicMock(return_value=False)
        await scheduler._run_cycle()
        await asyncio.sleep(0.1)
        
        mock_db.execute.assert_called()
        args, kwargs = mock_db.execute.call_args
        assert "next_scheduled_run_time" in args[1]


@pytest.mark.asyncio
async def test_scraper_concurrency_lock():
    """Test that concurrent calls to run_processing_cycle are locked and only one executes."""
    from main import ApartmentBotApplication
    app = ApartmentBotApplication()
    app._cycle_lock = asyncio.Lock()
    
    # Mock the internal implementation to simulate a slow execution
    async def mock_impl():
        await asyncio.sleep(0.2)
        return 10, 0
        
    app._run_processing_cycle_impl = mock_impl
    
    # Start two tasks concurrently
    task1 = asyncio.create_task(app.run_processing_cycle())
    # Wait a tiny bit to let task1 acquire the lock
    await asyncio.sleep(0.05)
    
    task2 = asyncio.create_task(app.run_processing_cycle())
    
    res1 = await task1
    res2 = await task2
    
    # Task 1 should have executed and returned the yield (10, 0)
    assert res1 == (10, 0)
    # Task 2 should have skipped and returned (0, 0) because the lock was held
    assert res2 == (0, 0)


@pytest.mark.asyncio
async def test_adaptive_yield_scheduling():
    """Test that QuotaAwareScheduler adapts its interval based on listings yield."""
    callback = MagicMock()
    rate_limiter = MagicMock()
    rate_limiter.get_remaining_quota.return_value = {"daily_remaining": 500}
    rate_limiter.daily_reset = datetime.now() + timedelta(hours=10)
    
    scheduler = QuotaAwareScheduler(process_callback=callback, rate_limiter=rate_limiter)
    
    # Set base settings
    settings.SCRAPE_INTERVAL_MINUTES = 30
    scheduler.interval = 30
    
    # Case 1: yield >= 4 -> should decrease interval by 5
    new_interval = scheduler.calculate_optimal_interval(new_listings_found=5)
    assert new_interval == 25
    
    # Case 2: yield < 4 -> should increase interval by 5
    scheduler.interval = 30
    new_interval = scheduler.calculate_optimal_interval(new_listings_found=2)
    assert new_interval == 35
    
    # Case 3: yield < 4 -> should increase interval up to max cap (120)
    scheduler.interval = 120
    new_interval = scheduler.calculate_optimal_interval(new_listings_found=0)
    assert new_interval == 120
    
    # Case 4: yield >= 4 -> should decrease interval down to min cap (10)
    settings.SCRAPE_INTERVAL_MINUTES = 16
    scheduler.interval = 10
    new_interval = scheduler.calculate_optimal_interval(new_listings_found=6)
    assert new_interval == 10
