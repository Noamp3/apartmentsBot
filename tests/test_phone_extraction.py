# tests/test_phone_extraction.py
import pytest
import json
from unittest.mock import MagicMock
from models.listing import Listing, EnrichedListing
from bot.formatters.listing_formatter import ListingFormatter
from core.ai_engine import ListingEnricher, BaseAIEngine

def test_format_whatsapp_url():
    """Verify that ListingFormatter.format_whatsapp_url correctly formats phone numbers."""
    # Test Israeli mobile number formats
    assert ListingFormatter.format_whatsapp_url("050-123-4567") == "https://wa.me/972501234567"
    assert ListingFormatter.format_whatsapp_url("0541234567") == "https://wa.me/972541234567"
    assert ListingFormatter.format_whatsapp_url("052 123 4567") == "https://wa.me/972521234567"
    assert ListingFormatter.format_whatsapp_url("+972 50-123-4567") == "https://wa.me/972501234567"
    assert ListingFormatter.format_whatsapp_url("972501234567") == "https://wa.me/972501234567"
    assert ListingFormatter.format_whatsapp_url("") == ""
    assert ListingFormatter.format_whatsapp_url(None) == ""

def test_listing_formatter_shows_phone_whatsapp_link():
    """Verify that ListingFormatter renders phone number as a WhatsApp link at the top."""
    listing = Listing(
        id="test_id",
        source="facebook",
        url="https://facebook.com/123",
        title="דירת 3 חדרים",
        description="תיאור מפורט",
        location="תל אביב",
        raw_text="תיאור מפורט",
        phone="050-123-4567"
    )
    enriched = EnrichedListing(
        listing=listing,
        extracted_price=5000,
        extracted_bedrooms=3,
        extracted_location="תל אביב"
    )
    
    formatted_msg = ListingFormatter.format_listing(enriched)
    formatted_caption = ListingFormatter.format_listing_caption(enriched)
    
    # Verify the phone number WhatsApp link exists in the formatted outputs
    expected_link = "[050\\-123\\-4567](https://wa.me/972501234567)"
    assert expected_link in formatted_msg
    assert expected_link in formatted_caption
    assert "📞 *טלפון:*" in formatted_msg
    assert "📞 *טלפון:*" in formatted_caption

@pytest.mark.asyncio
async def test_database_phone_saving(db):
    """Verify that the repository saves and restores the phone number correctly."""
    from database.repositories import ListingRepository
    repo = ListingRepository(db)
    
    listing = Listing(
        id="test_db_phone_id",
        source="facebook",
        url="https://facebook.com/123",
        title="דירת 3 חדרים",
        description="תיאור מפורט",
        location="תל אביב",
        raw_text="תיאור מפורט",
        phone="054-987-6543"
    )
    enriched = EnrichedListing(
        listing=listing,
        extracted_price=6000,
        extracted_bedrooms=3,
        extracted_location="תל אביב"
    )
    
    await repo.save_enriched(enriched)
    
    retrieved = await repo.get_enriched("test_db_phone_id")
    assert retrieved is not None
    assert retrieved.listing.phone == "054-987-6543"

@pytest.mark.asyncio
async def test_ai_enrichment_phone_resolution():
    """Verify ListingEnricher extracts and resolves phone numbers from AI response and regex fallbacks."""
    mock_ai = MagicMock(spec=BaseAIEngine)
    
    # 1. Test extraction from AI response
    enricher = ListingEnricher(ai_engine=mock_ai, batch_size=2)
    mock_ai._parse_json_response.return_value = {
        "listings": [
            {
                "is_real_estate": True,
                "price": 5000,
                "bedrooms": 3,
                "phone": "050-111-2222",
                "location": "תל אביב"
            }
        ]
    }
    mock_ai.generate_content.return_value = "dummy"
    
    listings = [
        Listing(
            id="l1",
            source="facebook",
            url="http://test1",
            title="דירה 1",
            description="חפשו אותי בטלפון 050-111-2222",
            location="תל אביב",
            raw_text="חפשו אותי בטלפון 050-111-2222"
        )
    ]
    
    results = await enricher.enrich_listings(listings)
    assert len(results) == 1
    assert results[0].listing.phone == "050-111-2222"
    
    # 2. Test fallback to regex when AI returns no phone
    mock_ai._parse_json_response.return_value = {
        "listings": [
            {
                "is_real_estate": True,
                "price": 5000,
                "bedrooms": 3,
                "phone": None,
                "location": "תל אביב"
            }
        ]
    }
    
    listings = [
        Listing(
            id="l2",
            source="facebook",
            url="http://test2",
            title="דירה 2",
            description="חפשו אותי בטלפון 050-555-5555",
            location="תל אביב",
            raw_text="חפשו אותי בטלפון 050-555-5555"
        )
    ]
    
    results = await enricher.enrich_listings(listings)
    assert len(results) == 1
    assert results[0].listing.phone == "050-555-5555"
