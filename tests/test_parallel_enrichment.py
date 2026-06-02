# tests/test_parallel_enrichment.py
"""Tests for parallel batch enrichment in ListingEnricher."""

import pytest
import asyncio
from unittest.mock import MagicMock
from models.listing import Listing, EnrichedListing
from core.ai_engine import ListingEnricher, BaseAIEngine


@pytest.mark.asyncio
async def test_parallel_enrichment_success():
    """Verify that batches are processed in parallel and final order is preserved."""
    mock_ai = MagicMock(spec=BaseAIEngine)
    enricher = ListingEnricher(ai_engine=mock_ai, batch_size=2)
    
    # We want to enrich 5 listings -> should be split into 3 batches (2, 2, 1)
    listings = [
        Listing(
            id=f"id_{i}",
            source="facebook",
            url=f"http://url_{i}",
            title=f"title_{i}",
            description=f"desc_{i}",
            location=f"loc_{i}",
            raw_text=f"text_{i}"
        )
        for i in range(5)
    ]
    
    calls = []
    
    async def mock_enrich_batch(batch_listings):
        calls.append(batch_listings)
        await asyncio.sleep(0.1)  # Simulate network/AI call
        return [
            EnrichedListing(
                listing=l,
                extracted_price=1000,
                extracted_bedrooms=2,
                extracted_location=l.location,
            )
            for l in batch_listings
        ]
        
    enricher._enrich_batch = mock_enrich_batch
    
    # Act
    start_time = asyncio.get_event_loop().time()
    results = await enricher.enrich_listings(listings)
    end_time = asyncio.get_event_loop().time()
    
    # Assert
    assert len(results) == 5
    assert [r.listing.id for r in results] == [f"id_{i}" for i in range(5)]
    assert len(calls) == 3  # 3 batches: [id_0, id_1], [id_2, id_3], [id_4]
    
    # Since they run in parallel, total time should be close to 0.1s rather than 0.3s (sequential)
    duration = end_time - start_time
    assert duration < 0.25  # Sequential would take >= 0.3s


@pytest.mark.asyncio
async def test_parallel_enrichment_partial_failure():
    """Verify that if one batch fails, other batches still succeed and fallback is applied only to the failed batch."""
    mock_ai = MagicMock(spec=BaseAIEngine)
    enricher = ListingEnricher(ai_engine=mock_ai, batch_size=2)
    
    listings = [
        Listing(
            id=f"id_{i}",
            source="facebook",
            url=f"http://url_{i}",
            title=f"title_{i}",
            description=f"desc_{i}",
            location=f"loc_{i}",
            raw_text=f"text_{i}",
            price=5000
        )
        for i in range(4)
    ]
    
    # Batch 1 (idx 0, listings id_0, id_1) succeeds, Batch 2 (idx 1, listings id_2, id_3) fails
    async def mock_enrich_batch(batch_listings):
        if any(l.id in ("id_2", "id_3") for l in batch_listings):
            raise Exception("AI Error in Batch 2")
        return [
            EnrichedListing(
                listing=l,
                extracted_price=6000,
                extracted_bedrooms=3,
                extracted_location=l.location,
            )
            for l in batch_listings
        ]
        
    enricher._enrich_batch = mock_enrich_batch
    
    # Act
    results = await enricher.enrich_listings(listings)
    
    # Assert
    assert len(results) == 4
    assert [r.listing.id for r in results] == [f"id_{i}" for i in range(4)]
    
    # Batch 1 results should be enriched via mock AI
    assert results[0].extracted_price == 6000
    assert results[1].extracted_price == 6000
    
    # Batch 2 results should have fallen back to basic enrich (which preserves listing.price or extracts it)
    assert results[2].extracted_price == 5000
    assert results[3].extracted_price == 5000
