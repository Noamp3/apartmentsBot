# scripts/test_logic.py
"""Standalone script to test matching logic without scrapers or bot."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from utils.logger import LoggerFactory
from core.ai_engine import create_ai_engine, ListingEnricher
from core.matcher import ZeroAIUserMatcher, RulePreFilter
from models.listing import Listing, EnrichedListing
from models.search_rule import SearchRule, RuleType
from utils.israeli_locations import get_location_db


def create_mock_listings():
    """Create mock listings for testing."""
    return [
        Listing(
            id="test1",
            source="test",
            url="https://example.com/1",
            title="דירה 3 חדרים בפלורנטין",
            description="דירה מהממת בלב פלורנטין, 3 חדרים, מרפסת גדולה, חניה בבניין. 4500 ש\"ח",
            location="פלורנטין, תל אביב",
            raw_text="דירה 3 חדרים בפלורנטין 4500 שח עם מרפסת וחניה",
            price=4500,
            bedrooms=3,
            scraped_at=datetime.now()
        ),
        Listing(
            id="test2",
            source="test",
            url="https://example.com/2",
            title="דירת 2 חדרים בנווה צדק + תיווך",
            description="דירה יפה בנווה צדק, 2 חדרים, קרובה לים. 6000 ש\"ח + תיווך",
            location="נווה צדק, תל אביב",
            raw_text="דירה 2 חדרים בנווה צדק 6000 שקל דמי תיווך",
            price=6000,
            bedrooms=2,
            scraped_at=datetime.now()
        ),
        Listing(
            id="test3",
            source="test",
            url="https://example.com/3",
            title="דירה ברמת גן",
            description="דירה גדולה ברמת גן, 4 חדרים, מותר חיות מחמד",
            location="רמת גן",
            raw_text="דירה 4 חדרים ברמת גן 5500 שקל מותר כלבים",
            price=5500,
            bedrooms=4,
            scraped_at=datetime.now()
        ),
    ]


def create_mock_rules():
    """Create mock search rules for testing."""
    return [
        SearchRule(user_id=1, rule_type=RuleType.PRICE_MAX, value="5000", original_text="עד 5000 ש\"ח"),
        SearchRule(user_id=1, rule_type=RuleType.BEDROOMS_MIN, value="3", original_text="לפחות 3 חדרים"),
        SearchRule(user_id=1, rule_type=RuleType.AREA, value="תל אביב", original_text="בתל אביב"),
    ]


def test_location_matching():
    """Test location database matching."""
    print("\n" + "="*50)
    print("📍 Testing Location Matching")
    print("="*50)
    
    db = get_location_db()
    
    test_cases = [
        ("פלורנטין", "תל אביב"),
        ("נווה צדק", "פלורנטין"),  # Should match bordering
        ("רמת גן", "תל אביב"),  # Should NOT match
        ("הצפון החדש", "צפון תל אביב"),  # Area group
        ("הרצליה", "גוש דן"),  # Should NOT match
    ]
    
    for listing_loc, target in test_cases:
        is_match, match_type, explanation = db.is_location_match(listing_loc, target)
        status = "✅" if is_match else "❌"
        print(f"\n  {status} '{listing_loc}' matches '{target}'?")
        print(f"     Type: {match_type}, Reason: {explanation}")


def test_rule_prefilter():
    """Test rule pre-filtering."""
    print("\n" + "="*50)
    print("🔧 Testing Rule Pre-Filter")
    print("="*50)
    
    listings = create_mock_listings()
    rules = create_mock_rules()
    
    for listing in listings:
        # Create enriched listing
        enriched = EnrichedListing(
            listing=listing,
            extracted_price=listing.price,
            extracted_bedrooms=listing.bedrooms,
            extracted_location=listing.location,
            has_broker_fee="תיווך" in listing.raw_text,
        )
        
        passes, failures = RulePreFilter.passes_hard_rules(enriched, rules)
        status = "✅ PASS" if passes else "❌ FAIL"
        
        print(f"\n  {status}: {listing.title}")
        print(f"     Price: {enriched.extracted_price}₪ (effective: {enriched.effective_monthly_price}₪)")
        print(f"     Rooms: {enriched.extracted_bedrooms}")
        if failures:
            for f in failures:
                print(f"     ⚠️ {f}")


def test_zero_ai_matcher():
    """Test the zero-AI user matcher."""
    print("\n" + "="*50)
    print("🤖 Testing Zero-AI Matcher")
    print("="*50)
    
    matcher = ZeroAIUserMatcher()
    listings = create_mock_listings()
    rules = create_mock_rules()
    
    print(f"\n  Rules being tested:")
    for rule in rules:
        print(f"    • {rule.rule_type.value}: {rule.original_text}")
    
    for listing in listings:
        enriched = EnrichedListing(
            listing=listing,
            extracted_price=listing.price,
            extracted_bedrooms=listing.bedrooms,
            extracted_location=listing.location,
            has_broker_fee="תיווך" in listing.raw_text,
            attributes={"allows_pets": "כלב" in listing.raw_text or "חיות" in listing.raw_text}
        )
        
        is_match, reasons = matcher.evaluate_listing(enriched, rules)
        status = "✅ MATCH" if is_match else "❌ REJECT"
        
        print(f"\n  {status}: {listing.title}")
        print(f"     Location: {listing.location}")
        if reasons:
            print(f"     Rejection reasons:")
            for r in reasons:
                print(f"       • {r}")


async def test_ai_enrichment():
    """Test AI enrichment (requires API key)."""
    print("\n" + "="*50)
    print("🧠 Testing AI Enrichment")
    print("="*50)
    
    if not settings.active_api_key:
        print("  ⚠️ No API key configured. Skipping AI test.")
        print(f"     Set {settings.AI_PROVIDER.value.upper()}_API_KEY in .env")
        return
    
    try:
        ai_engine = create_ai_engine()
        enricher = ListingEnricher(ai_engine)
        
        listings = create_mock_listings()[:1]  # Test with 1 listing to save API calls
        
        print(f"  Enriching {len(listings)} listing(s) with {settings.AI_PROVIDER.value}...")
        enriched = await enricher.enrich_listings(listings)
        
        for e in enriched:
            print(f"\n  ✅ Enriched: {e.listing.title}")
            print(f"     Price: {e.extracted_price}")
            print(f"     Bedrooms: {e.extracted_bedrooms}")
            print(f"     Location: {e.extracted_location}")
            print(f"     Neighborhood: {e.extracted_neighborhood}")
            print(f"     Has broker: {e.has_broker_fee}")
            print(f"     Attributes: {e.attributes}")
            
    except Exception as e:
        print(f"  ❌ AI enrichment failed: {e}")


async def main():
    """Run all logic tests."""
    LoggerFactory.initialize(debug=True)
    
    print("\n🏠 Apartment Bot - Logic Test")
    print("==============================\n")
    
    test_location_matching()
    test_rule_prefilter()
    test_zero_ai_matcher()
    await test_ai_enrichment()
    
    print("\n" + "="*50)
    print("✅ Logic tests complete!")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(main())
