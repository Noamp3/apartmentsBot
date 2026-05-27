import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from scrapers.scheduler import ScrapingScheduler
from config import settings

@pytest.mark.asyncio
async def test_blackout_period_logic():
    # Setup
    callback = MagicMock()
    scheduler = ScrapingScheduler(process_callback=callback)
    
    # Force settings for predictable testing
    with patch.object(settings, 'BLACKOUT_START_HOUR', 1), \
         patch.object(settings, 'BLACKOUT_END_HOUR', 7), \
         patch.object(settings, 'BLACKOUT_JITTER_MINUTES', 0): # No jitter for base cases
        
        # Case 1: Outside blackout (Noon)
        noon = datetime.now().replace(hour=12, minute=0, second=0)
        with patch('scrapers.scheduler.datetime') as mock_datetime:
            mock_datetime.now.return_value = noon
            assert scheduler._is_blackout_period() is False
            
        # Case 2: Inside blackout (3 AM)
        three_am = datetime.now().replace(hour=3, minute=0, second=0)
        with patch('scrapers.scheduler.datetime') as mock_datetime:
            mock_datetime.now.return_value = three_am
            assert scheduler._is_blackout_period() is True

@pytest.mark.asyncio
async def test_blackout_jitter_renewal():
    callback = MagicMock()
    scheduler = ScrapingScheduler(process_callback=callback)
    
    # Force jitter for testing
    with patch.object(settings, 'BLACKOUT_JITTER_MINUTES', 30):
        # Day 1
        day1 = datetime(2025, 1, 1, 12, 0)
        with patch('scrapers.scheduler.datetime') as mock_datetime:
            mock_datetime.now.return_value = day1
            scheduler._is_blackout_period()
            
            jitter_start_1 = scheduler._blackout_jitter_start
            jitter_end_1 = scheduler._blackout_jitter_end
            jitter_day_1 = scheduler._jitter_day
            
            assert jitter_day_1 == day1.date()
            
            # Same day - should not change
            day1_later = day1 + timedelta(hours=2)
            mock_datetime.now.return_value = day1_later
            scheduler._is_blackout_period()
            
            assert scheduler._blackout_jitter_start == jitter_start_1
            assert scheduler._blackout_jitter_end == jitter_end_1
            
            # Day 2 - should change (highly likely, though random could repeat)
            day2 = datetime(2025, 1, 2, 12, 0)
            mock_datetime.now.return_value = day2
            
            # To ensure it changes, we can mock random (optional but safer for test)
            with patch('random.randint') as mock_random:
                mock_random.side_effect = [15, -15] # Fixed jitters for Day 2
                scheduler._is_blackout_period()
                
                assert scheduler._jitter_day == day2.date()
                assert scheduler._blackout_jitter_start == 15
                assert scheduler._blackout_jitter_end == -15

@pytest.mark.asyncio
async def test_run_cycle_respects_blackout():
    callback = MagicMock(side_effect=asyncio.sleep(0))
    scheduler = ScrapingScheduler(process_callback=callback)
    
    # Mocking _is_blackout_period to return True
    with patch.object(scheduler, '_is_blackout_period', return_value=True):
        await scheduler._run_cycle()
        callback.assert_not_called()
        
    # Mocking _is_blackout_period to return False
    with patch.object(scheduler, '_is_blackout_period', return_value=False):
        await scheduler._run_cycle()
        callback.assert_called_once()
