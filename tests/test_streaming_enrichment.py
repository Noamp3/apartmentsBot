# tests/test_streaming_enrichment.py
"""Tests for batch-driven streaming enrichment and validation in main orchestrator."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from models.listing import Listing, EnrichedListing
from main import ApartmentBotApplication

@pytest.mark.asyncio
async def test_streaming_enrichment_processing_cycle():
    """Verify that run_processing_cycle processes listings as soon as batch size is met."""
    app = ApartmentBotApplication()
    
    # Mock seen repository
    mock_seen_repo = MagicMock()
    mock_seen_repo.is_seen = AsyncMock(return_value=False)
    mock_seen_repo.find_duplicate_by_fingerprint = AsyncMock(return_value=None)
    mock_seen_repo.mark_many_seen = AsyncMock()
    mock_seen_repo.save_fingerprint = AsyncMock()
    
    # Mock other database repositories
    app.facebook_scraper = MagicMock()
    app.yad2_scraper = MagicMock()
    app.enricher = MagicMock()
    app.enricher.batch_size = 3
    
    # Set up mock enrichment to return list of EnrichedListings
    async def mock_enrich_listings(batch):
        return [
            EnrichedListing(
                listing=l,
                extracted_price=5000,
                extracted_bedrooms=2,
                extracted_location=l.location,
            )
            for l in batch
        ]
    app.enricher.enrich_listings = AsyncMock(side_effect=mock_enrich_listings)
    
    # Mock location db and geo grounding engine
    app.geo_grounding_ai_engine = None
    
    # Mock processing service (matching & notifications)
    app.processing_service = MagicMock()
    app.processing_service.process_cycle = AsyncMock()
    
    # Listings to scrape: 5 listings total (1 batch of 3, 1 remaining flush of 2)
    listings_scraped = [
        Listing(
            id=f"id_{i}",
            source="facebook" if i < 3 else "yad2",
            url=f"http://url_{i}",
            title=f"title_{i}",
            description=f"desc_{i}",
            location=f"loc_{i}",
            raw_text=f"text_{i}"
        )
        for i in range(5)
    ]
    
    # Mock scrape methods to feed listings through the callback
    async def mock_scrape_fb(on_listing_scraped=None, **kwargs):
        if on_listing_scraped:
            for l in listings_scraped[:3]:
                await on_listing_scraped(l)
        return listings_scraped[:3]
        
    async def mock_scrape_yad2(on_listing_scraped=None, **kwargs):
        if on_listing_scraped:
            for l in listings_scraped[3:]:
                await on_listing_scraped(l)
        return listings_scraped[3:]
        
    app.facebook_scraper.scrape = AsyncMock(side_effect=mock_scrape_fb)
    app.yad2_scraper.scrape = AsyncMock(side_effect=mock_scrape_yad2)
    
    # Patch get_db and repositories inside main.py
    with patch("main.get_db", new_callable=AsyncMock) as mock_get_db, \
         patch("main.SeenListingsRepository", return_value=mock_seen_repo), \
         patch("main.ListingRepository") as mock_listing_repo_class:
             
        mock_listing_repo = MagicMock()
        mock_listing_repo.save_enriched = AsyncMock()
        mock_listing_repo_class.return_value = mock_listing_repo
        
        # Run processing cycle
        await app.run_processing_cycle()
        
        # Assertions:
        # 1. enrich_listings should have been called twice (once for batch of 3, once for flush of 2)
        assert app.enricher.enrich_listings.call_count == 2
        
        # Check call arguments
        calls = app.enricher.enrich_listings.call_args_list
        batch_1_ids = [l.id for l in calls[0][0][0]]
        batch_2_ids = [l.id for l in calls[1][0][0]]
        
        assert len(batch_1_ids) == 3
        assert len(batch_2_ids) == 2
        assert batch_1_ids == ["id_0", "id_1", "id_2"]
        assert batch_2_ids == ["id_3", "id_4"]
        
        # 2. process_cycle should have been called twice (once for each batch)
        assert app.processing_service.process_cycle.call_count == 2
