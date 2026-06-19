# tests/test_dynamic_scraping.py
"""Tests for dynamic scraping order and immediate notification processing."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from database.repositories.facebook_group_repository import FacebookGroupRepository
from models.facebook_group import FacebookGroup
from models.listing import Listing


@pytest.mark.asyncio
async def test_facebook_group_repository_sorting(db):
    """Test that FacebookGroupRepository correctly stores and sorts groups by last_scraped_count."""
    fb_group_repo = FacebookGroupRepository(db)
    
    # 1. Create mock groups with different last_scraped_count
    group_a = FacebookGroup(url="https://facebook.com/groups/a")
    group_b = FacebookGroup(url="https://facebook.com/groups/b")
    group_c = FacebookGroup(url="https://facebook.com/groups/c")
    group_d = FacebookGroup(url="https://facebook.com/groups/d")
    
    await fb_group_repo.create(group_a)
    await fb_group_repo.create(group_b)
    await fb_group_repo.create(group_c)
    await fb_group_repo.create(group_d)
    
    # 2. Update their scraped counts to simulate varying activity
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/a", 2)
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/b", 12)
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/c", 0)
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/d", 12)
    
    # 3. Retrieve all groups from database
    groups = await fb_group_repo.get_all_groups()
    
    # Check counts match
    urls_sorted = [g.url for g in groups]
    
    # Sorting order should be:
    # 1. B (count=12, added first between B & D)
    # 2. D (count=12, added second)
    # 3. A (count=2)
    # 4. C (count=0)
    assert urls_sorted == [
        "https://facebook.com/groups/b",
        "https://facebook.com/groups/d",
        "https://facebook.com/groups/a",
        "https://facebook.com/groups/c"
    ]
    
    # 4. Change count of A to make it the highest
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/a", 20)
    
    groups_updated = await fb_group_repo.get_all_groups()
    urls_updated = [g.url for g in groups_updated]
    
    # New order: A (20), B (12), D (12), C (0)
    assert urls_updated == [
        "https://facebook.com/groups/a",
        "https://facebook.com/groups/b",
        "https://facebook.com/groups/d",
        "https://facebook.com/groups/c"
    ]


@pytest.mark.asyncio
async def test_on_group_completed_updates_db_and_flushes_listings():
    """Test that on_group_completed updates database count and flushes batch immediately."""
    from main import ApartmentBotApplication
    
    app = ApartmentBotApplication()
    
    # Mock database repository operations
    mock_db = MagicMock()
    mock_fb_group_repo = MagicMock(spec=FacebookGroupRepository)
    mock_fb_group_repo.update_scraped_count = AsyncMock()
    
    # Mock SeenListingsRepository
    from database.repositories.listing_repository import SeenListingsRepository
    mock_seen_repo = MagicMock(spec=SeenListingsRepository)
    mock_seen_repo.is_seen = AsyncMock(return_value=False)
    mock_seen_repo.find_duplicate_by_fingerprint = AsyncMock(return_value=None)
    
    # Mock other dependencies on app
    app.facebook_scraper = MagicMock()
    app.facebook_scraper.scrape = AsyncMock(return_value=[])
    app.yad2_scraper = MagicMock()
    app.yad2_scraper.scrape = AsyncMock(return_value=[])
    
    # Mock reload_facebook_groups to avoid running DB logic
    app.reload_facebook_groups = AsyncMock()
    
    # Mock process_enrich_and_notify_batch
    app.process_enrich_and_notify_batch = AsyncMock()
    app.enricher = MagicMock()
    app.enricher.batch_size = 5
    
    # Mock the database getter
    with patch("main.get_db", return_value=mock_db), \
         patch("main.SeenListingsRepository", return_value=mock_seen_repo), \
         patch("database.repositories.facebook_group_repository.FacebookGroupRepository", return_value=mock_fb_group_repo):
         
        # We start the processing cycle task
        cycle_task = asyncio.create_task(app.run_processing_cycle())
        
        # Give event loop a small tick to start the task and declare variables
        await asyncio.sleep(0.01)
        
        # Verify that facebook_scraper.scrape was called
        app.facebook_scraper.scrape.assert_called_once()
        
        # Get the callbacks passed to scrape()
        kwargs = app.facebook_scraper.scrape.call_args[1]
        on_listing_scraped_cb = kwargs.get("on_listing_scraped")
        on_group_completed_cb = kwargs.get("on_group_completed")
        
        assert on_listing_scraped_cb is not None
        assert on_group_completed_cb is not None
        
        # Simulate scraping one listing
        mock_listing = Listing(
            id="test_listing_1",
            source="facebook",
            url="https://facebook.com/1",
            title="Apartment A",
            description="Nice place",
            location="Tel Aviv",
            raw_text="Nice place",
            price=5000,
            bedrooms=2,
            phone="12345",
            posted_at=None,
            scraped_at=None
        )
        
        await on_listing_scraped_cb(mock_listing)
        
        # Listing should be accumulated, but not processed yet since batch size is 5
        app.process_enrich_and_notify_batch.assert_not_called()
        
        # Trigger on_group_completed callback
        group_url = "https://facebook.com/groups/xyz"
        group_listings = [mock_listing]
        
        await on_group_completed_cb(group_url, group_listings)
        
        # Verify database update count was called
        mock_fb_group_repo.update_scraped_count.assert_called_once_with(group_url, 1)
        
        # Verify the batch was immediately flushed/processed even though it was size 1 (less than 5)
        app.process_enrich_and_notify_batch.assert_called_once_with([mock_listing])
        
        # Cancel the active cycle task to clean up
        cycle_task.cancel()
        try:
            await cycle_task
        except asyncio.CancelledError:
            pass
