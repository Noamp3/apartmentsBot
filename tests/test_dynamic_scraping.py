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
            scraped_at=None,
            group_url="https://facebook.com/groups/xyz"
        )
        
        await on_listing_scraped_cb(mock_listing)
        
        # Listing should be accumulated, but not processed yet since batch size is 5
        app.process_enrich_and_notify_batch.assert_not_called()
        
        # Trigger on_group_completed callback
        group_url = "https://facebook.com/groups/xyz"
        group_listings = [mock_listing]
        
        await on_group_completed_cb(group_url, group_listings)
        
        # Give event loop a small tick to allow background task to run
        await asyncio.sleep(0.01)
        
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


@pytest.mark.asyncio
async def test_facebook_group_skip_next_db_updates(db):
    """Test that FacebookGroupRepository.update_scraped_count sets skip_next = 1 when count is 0, and 0 otherwise."""
    fb_group_repo = FacebookGroupRepository(db)
    
    group_a = FacebookGroup(url="https://facebook.com/groups/skipa")
    group_b = FacebookGroup(url="https://facebook.com/groups/skipb")
    
    await fb_group_repo.create(group_a)
    await fb_group_repo.create(group_b)
    
    # Update group A with 0 new posts -> should set skip_next to 1
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/skipa", 0)
    # Update group B with 3 new posts -> should set skip_next to 0
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/skipb", 3)
    
    # Retrieve and assert
    retrieved_a = await fb_group_repo.get_by_url("https://facebook.com/groups/skipa")
    retrieved_b = await fb_group_repo.get_by_url("https://facebook.com/groups/skipb")
    
    assert retrieved_a.skip_next == 1
    assert retrieved_b.skip_next == 0
    
    # Update A with 5 new posts -> should reset skip_next to 0
    await fb_group_repo.update_scraped_count("https://facebook.com/groups/skipa", 5)
    retrieved_a_after = await fb_group_repo.get_by_url("https://facebook.com/groups/skipa")
    assert retrieved_a_after.skip_next == 0
    
    # Update skip_next directly
    await fb_group_repo.update_skip_next("https://facebook.com/groups/skipb", 1)
    retrieved_b_after = await fb_group_repo.get_by_url("https://facebook.com/groups/skipb")
    assert retrieved_b_after.skip_next == 1


@pytest.mark.asyncio
async def test_facebook_group_skipping_logic_in_cycle():
    """Test that ApartmentBotApplication's cycle skips groups with skip_next=1 and resets them to 0."""
    from main import ApartmentBotApplication
    
    app = ApartmentBotApplication()
    
    # Mock databases/repos
    mock_db = MagicMock()
    mock_fb_group_repo = MagicMock(spec=FacebookGroupRepository)
    
    # Set up some mock groups: Group A (skip_next=0), Group B (skip_next=1)
    group_a = FacebookGroup(url="https://facebook.com/groups/a", skip_next=0, name="Group A")
    group_b = FacebookGroup(url="https://facebook.com/groups/b", skip_next=1, name="Group B")
    
    mock_fb_group_repo.get_all_groups = AsyncMock(return_value=[group_a, group_b])
    mock_fb_group_repo.update_skip_next = AsyncMock()
    
    # Mock SeenListingsRepository
    from database.repositories.listing_repository import SeenListingsRepository
    mock_seen_repo = MagicMock(spec=SeenListingsRepository)
    mock_seen_repo.is_seen = AsyncMock(return_value=False)
    mock_seen_repo.find_duplicate_by_fingerprint = AsyncMock(return_value=None)
    
    # Mock scrapers
    app.facebook_scraper = MagicMock()
    app.facebook_scraper.scrape = AsyncMock(return_value=[])
    app.yad2_scraper = MagicMock()
    app.yad2_scraper.scrape = AsyncMock(return_value=[])
    
    # Mock reload_facebook_groups to not run real DB operations
    app.reload_facebook_groups = AsyncMock()
    
    # Mock the database getter
    with patch("main.get_db", return_value=mock_db), \
         patch("main.SeenListingsRepository", return_value=mock_seen_repo), \
         patch("database.repositories.facebook_group_repository.FacebookGroupRepository", return_value=mock_fb_group_repo):
         
        # Run implementation detail directly or trigger cycle
        cycle_task = asyncio.create_task(app.run_processing_cycle())
        await asyncio.sleep(0.01)
        
        # We assert that facebook_scraper's group_urls was set to ONLY group_a (excluding group_b because skip_next=1)
        assert app.facebook_scraper.group_urls == ["https://facebook.com/groups/a"]
        
        # We assert that update_skip_next was called for the skipped group to reset it to 0
        mock_fb_group_repo.update_skip_next.assert_called_once_with("https://facebook.com/groups/b", 0)
        
        # Clean up task
        cycle_task.cancel()
        try:
            await cycle_task
        except asyncio.CancelledError:
            pass
