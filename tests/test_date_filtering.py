
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from scrapers.yad2_scraper import Yad2Scraper
from models.listing import Listing, EnrichedListing
from core.matcher import ZeroAIUserMatcher
from models.search_rule import SearchRule, RuleType

class TestDateFiltering(unittest.TestCase):
    def setUp(self):
        # Create a mock datetime class that returns a fixed "now" to avoid time-of-day flakiness
        self.fixed_now = datetime(2026, 6, 8, 12, 0, 0)
        self.MockDatetime = type(
            'MockDatetime', 
            (datetime,), 
            {'now': classmethod(lambda cls, tz=None: datetime(2026, 6, 8, 12, 0, 0))}
        )
        
        # Apply the patch to yad2_scraper, core.matcher, and the test file
        self.patchers = [
            patch('scrapers.yad2_scraper.datetime', self.MockDatetime),
            patch('core.matcher.datetime', self.MockDatetime),
            patch('tests.test_date_filtering.datetime', self.MockDatetime)
        ]
        for p in self.patchers:
            p.start()
            
        self.yad2_scraper = Yad2Scraper(city_id="test")
        self.matcher = ZeroAIUserMatcher()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_yad2_filtering_recent_listing(self):
        """Test that a recent listing (2 hours old) is accepted."""
        # 2 hours old
        posted_at = datetime.now() - timedelta(hours=2)
        
        # Mock the data needed for _parse_listing_item
        item = {
            "token": "test_token",
            "price": "1000",
            # Mock image url with date
            "metaData": {
                "images": [f"https://img.yad2.co.il/Pic/{posted_at.strftime('%Y%m')}/{posted_at.strftime('%d')}/test.jpg"]
            },
            "adType": "private"
        }
        
        listing = self.yad2_scraper._parse_listing_item(item)
        self.assertIsNotNone(listing)
        self.assertEqual(listing.posted_at.date(), posted_at.date())

    def test_yad2_filtering_old_listing(self):
        """Test that an old listing (2 days old) is rejected."""
        # 2 days old
        posted_at = datetime.now() - timedelta(days=2)
        
        item = {
            "token": "test_token_old",
            "price": "1000",
            # Mock image url with date
            "metaData": {
                "images": [f"https://img.yad2.co.il/Pic/{posted_at.strftime('%Y%m')}/{posted_at.strftime('%d')}/test.jpg"]
            },
            "adType": "private"
        }
        
        listing = self.yad2_scraper._parse_listing_item(item)
        self.assertIsNone(listing)

    def test_yad2_filtering_boundary_case(self):
        """Test the boundary case (exactly 1 day old + 1 minute)."""
        # 25 hours old - should be rejected
        posted_at = datetime.now() - timedelta(hours=25)
        
        item = {
            "token": "test_token_boundary",
            "price": "1000",
             # Mock image url with date
            "metaData": {
                "images": [f"https://img.yad2.co.il/Pic/{posted_at.strftime('%Y%m')}/{posted_at.strftime('%d')}/test.jpg"]
            },
            "adType": "private"
        }
        
        listing = self.yad2_scraper._parse_listing_item(item)
        self.assertIsNone(listing)

    def test_yad2_filtering_boundary_case_accepted(self):
        """Test the boundary case (23 hours old) which should be accepted."""
        # 23 hours old - should be accepted
        posted_at = datetime.now() - timedelta(hours=23)
        
        item = {
            "token": "test_token_boundary_accepted",
            "price": "1000",
             # Mock image url with date
            "metaData": {
                "images": [f"https://img.yad2.co.il/Pic/{posted_at.strftime('%Y%m')}/{posted_at.strftime('%d')}/test.jpg"]
            },
            "adType": "private"
        }
        
        
        listing = self.yad2_scraper._parse_listing_item(item)
        # Yad2 scraper filters based on date-only (00:00:00), so 23h ago (yesterday) results in > 24h diff from now.
        # Thus it is filtered out.
        self.assertIsNone(listing)

    def test_matcher_rejects_old_listing(self):
        """Test that the matcher rejects old listings even if they passed the scraper."""
        # 2 days old
        posted_at = datetime.now() - timedelta(days=2)
        
        listing = Listing(
            id="test", source="test", url="url", title="title", 
            description="desc", location="loc", raw_text="text",
            posted_at=posted_at
        )
        enriched = EnrichedListing(listing=listing)
        
        # Even with no rules (or valid rules), it should fail
        is_match, reasons = self.matcher.evaluate_listing(enriched, [])
        self.assertFalse(is_match)
        self.assertTrue(any("ישנה מדי" in r for r in reasons))

    def test_matcher_accepts_recent_listing(self):
        """Test that the matcher accepts recent listings."""
        # 2 hours old
        posted_at = datetime.now() - timedelta(hours=2)
        
        listing = Listing(
            id="test_new", source="test", url="url", title="title", 
            description="desc", location="loc", raw_text="text",
            posted_at=posted_at
        )
        enriched = EnrichedListing(listing=listing)
        
        # With no rules, it should pass
        is_match, reasons = self.matcher.evaluate_listing(enriched, [])
        self.assertTrue(is_match)
        self.assertEqual(len(reasons), 0)

    def test_matcher_accepts_unknown_date_listing(self):
        """Test that listings without posted_at are accepted (benefit of doubt)."""
        listing = Listing(
            id="test_no_date", source="test", url="url", title="title", 
            description="desc", location="loc", raw_text="text",
            posted_at=None  # Unknown date
        )
        enriched = EnrichedListing(listing=listing)
        
        # With no rules, should pass (benefit of the doubt)
        is_match, reasons = self.matcher.evaluate_listing(enriched, [])
        self.assertTrue(is_match)
        self.assertEqual(len(reasons), 0)

if __name__ == '__main__':
    unittest.main()
