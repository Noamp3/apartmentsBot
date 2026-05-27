"""Test duplicate detection across different sources."""

import unittest
from datetime import datetime

from database.connection import DatabaseManager
from database.repositories import SeenListingsRepository
from models.listing import Listing, EnrichedListing


def create_listing(listing_id: str, source: str, **kwargs) -> Listing:
    """Helper to create test listings."""
    defaults = {
        "id": listing_id,
        "source": source,
        "url": f"https://example.com/{listing_id}",
        "title": "Test Listing",
        "description": "Test description",
        "location": "Tel Aviv",
        "raw_text": "Test raw text",
        "price": None,
        "phone": None,
    }
    defaults.update(kwargs)
    return Listing(**defaults)


def create_enriched(listing: Listing, **kwargs) -> EnrichedListing:
    """Helper to create enriched listings."""
    defaults = {
        "listing": listing,
        "extracted_price": None,
        "extracted_bedrooms": None,
        "extracted_street": "",
        "extracted_neighborhood": "",
    }
    defaults.update(kwargs)
    return EnrichedListing(**defaults)


class TestDuplicateDetection(unittest.IsolatedAsyncioTestCase):
    """Test cases for cross-source duplicate detection."""
    
    async def asyncSetUp(self):
        """Set up test database and repository."""
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        await self.db.initialize()
        self.seen_repo = SeenListingsRepository(self.db)
    
    async def asyncTearDown(self):
        """Close database connection."""
        await self.db.close()
    
    async def test_exact_duplicate_phone_and_price(self):
        """Test duplicate detection with same phone and price."""
        # Create first listing (Facebook)
        listing1 = create_listing("fb_1", "facebook", phone="050-123-4567", price=5000)
        enriched1 = create_enriched(listing1, extracted_price=5000)
        
        # Save fingerprint
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing (Yad2) with same phone and price
        listing2 = create_listing("yad2_1", "yad2", phone="050-123-4567", price=5000)
        enriched2 = create_enriched(listing2, extracted_price=5000)
        
        # Should detect duplicate
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNotNone(duplicate_info)
        duplicate_id, matched_fields = duplicate_info
        self.assertEqual(duplicate_id, "fb_1")
        self.assertIn("phone", matched_fields)
        self.assertIn("price", matched_fields)
    
    async def test_partial_match_one_field_not_duplicate(self):
        """Test that matching only 1 field does NOT create duplicate."""
        # Create first listing
        listing1 = create_listing("fb_1", "facebook", phone="050-123-4567", price=5000)
        enriched1 = create_enriched(listing1, extracted_price=5000)
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with only same phone (different price)
        listing2 = create_listing("yad2_1", "yad2", phone="050-123-4567", price=6000)
        enriched2 = create_enriched(listing2, extracted_price=6000)
        
        # Should NOT detect duplicate (only 1 field matches)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNone(duplicate_info)
    
    async def test_price_tolerance(self):
        """Test that prices within ±5% are considered matching."""
        # Create first listing with price 5000
        listing1 = create_listing("fb_1", "facebook", phone="050-123-4567", price=5000)
        enriched1 = create_enriched(listing1, extracted_price=5000, extracted_bedrooms=2)
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create listing with price 5200 (4% higher, within tolerance)
        listing2 = create_listing("yad2_1", "yad2", phone="050-123-4567", price=5200)
        enriched2 = create_enriched(listing2, extracted_price=5200, extracted_bedrooms=2)
        
        # Should detect duplicate (phone + price within tolerance)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNotNone(duplicate_info)
        _, matched_fields = duplicate_info
        self.assertIn("phone", matched_fields)
        self.assertIn("price", matched_fields)
    
    async def test_phone_normalization(self):
        """Test that different phone formats match correctly."""
        # Create first listing with formatted phone
        listing1 = create_listing("fb_1", "facebook", phone="050-123-4567", price=5000)
        enriched1 = create_enriched(listing1, extracted_price=5000)
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with unformatted phone
        listing2 = create_listing("yad2_1", "yad2", phone="0501234567", price=5000)
        enriched2 = create_enriched(listing2, extracted_price=5000)
        
        # Should detect duplicate (normalized phones match)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNotNone(duplicate_info)
        _, matched_fields = duplicate_info
        self.assertIn("phone", matched_fields)
    
    async def test_israeli_country_code_normalization(self):
        """Test phone normalization with +972 country code."""
        # Create first listing with local format
        listing1 = create_listing("fb_1", "facebook", phone="050-123-4567", price=5000)
        enriched1 = create_enriched(listing1, extracted_price=5000)
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with international format
        listing2 = create_listing("yad2_1", "yad2", phone="+972-50-123-4567", price=5000)
        enriched2 = create_enriched(listing2, extracted_price=5000)
        
        # Should detect duplicate
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNotNone(duplicate_info)
    
    async def test_bedrooms_and_price_not_duplicate_without_identifying_field(self):
        """Test that bedrooms + price alone do NOT create duplicate (not identifying enough)."""
        # Create first listing
        listing1 = create_listing("fb_1", "facebook", price=5000)
        enriched1 = create_enriched(
            listing1,
            extracted_price=5000,
            extracted_bedrooms=3,
        )
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with matching bedrooms and price (but no phone or street)
        listing2 = create_listing("yad2_1", "yad2", price=5000)
        enriched2 = create_enriched(
            listing2,
            extracted_price=5000,
            extracted_bedrooms=3,
        )
        
        # Should NOT detect duplicate (price+bedrooms not identifying enough)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNone(duplicate_info)
    
    async def test_street_and_price_match(self):
        """Test that street + price IS a duplicate (location-based identification)."""
        # Create first listing
        listing1 = create_listing("fb_1", "facebook")
        enriched1 = create_enriched(
            listing1,
            extracted_price=5000,
            extracted_street="dizengoff"
        )
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with same street and price
        listing2 = create_listing("yad2_1", "yad2")
        enriched2 = create_enriched(
            listing2,
            extracted_price=5000,
            extracted_street="Dizengoff"  # Different case
        )
        
        # Should detect duplicate (street + price = same apartment)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNotNone(duplicate_info)
        _, matched_fields = duplicate_info
        self.assertIn("street", matched_fields)
        self.assertIn("price", matched_fields)
    
    async def test_cross_source_detection(self):
        """Test that duplicates are detected across different sources."""
        # Save Facebook listing
        fb_listing = create_listing("fb_123", "facebook", phone="050-123-4567", price=5000)
        fb_enriched = create_enriched(fb_listing, extracted_price=5000, extracted_bedrooms=3)
        
        await self.seen_repo.save_fingerprint(fb_listing, fb_enriched)
        
        # Try to save Yad2 listing with same attributes
        yad2_listing = create_listing("yad2_456", "yad2", phone="0501234567", price=5000)
        yad2_enriched = create_enriched(yad2_listing, extracted_price=5000, extracted_bedrooms=3)
        
        # Should detect duplicate from different source
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(yad2_listing, yad2_enriched)
        
        self.assertIsNotNone(duplicate_info)
        duplicate_id, matched_fields = duplicate_info
        self.assertEqual(duplicate_id, "fb_123")
        self.assertGreaterEqual(len(matched_fields), 2)
    
    async def test_author_and_price_match(self):
        """Test that same author + price IS a duplicate (poster identification)."""
        # Create first listing with author and price
        listing1 = create_listing("fb_1", "facebook")
        listing1.author = "John Doe"
        enriched1 = create_enriched(listing1, extracted_price=5000, extracted_bedrooms=3)
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with same author and price
        listing2 = create_listing("yad2_1", "yad2")
        listing2.author = "john doe"  # Different case
        enriched2 = create_enriched(listing2, extracted_price=5000, extracted_bedrooms=3)
        
        # Should detect duplicate (same author + price = same listing)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        self.assertIsNotNone(duplicate_info)
        _, matched_fields = duplicate_info
        self.assertIn("author", matched_fields)
        self.assertIn("price", matched_fields)
    
    async def test_no_duplicate_when_insufficient_fields(self):
        """Test that duplicate is not detected when less than 2 fields available."""
        # Create listing with only phone (no price, bedrooms, street)
        listing1 = create_listing("fb_1", "facebook", phone="050-123-4567")
        enriched1 = create_enriched(listing1)
        
        await self.seen_repo.save_fingerprint(listing1, enriched1)
        
        # Create second listing with same phone
        listing2 = create_listing("yad2_1", "yad2", phone="0501234567")
        enriched2 = create_enriched(listing2)
        
        # Should NOT detect duplicate (insufficient fields for match)
        duplicate_info = await self.seen_repo.find_duplicate_by_fingerprint(listing2, enriched2)
        
        # Will return None because we need at least 2 fields to check
        self.assertIsNone(duplicate_info)


if __name__ == "__main__":
    unittest.main()

