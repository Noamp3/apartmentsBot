import unittest
from datetime import datetime
from models.listing import Listing, EnrichedListing
from core.matcher import ZeroAIUserMatcher
from models.search_rule import SearchRule, RuleType

class TestFloatRuleParsing(unittest.TestCase):
    def setUp(self):
        self.matcher = ZeroAIUserMatcher()
        
    def test_float_bedroom_rules(self):
        # Create a listing with 2 bedrooms
        listing = Listing(
            id="test_beds", source="test", url="url", title="title", 
            description="desc", location="loc", raw_text="text",
            posted_at=datetime.now()
        )
        # Note: ZeroAIUserMatcher uses enriched.extracted_bedrooms
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_bedrooms = 2.0
        
        # Test BEDROOMS_MIN rule with float string "2.0" (should pass)
        rule_min = SearchRule(
            id=1, user_id=123, rule_type=RuleType.BEDROOMS_MIN, 
            value="2.0", is_active=True
        )
        is_match, reasons = self.matcher.evaluate_listing(enriched, [rule_min])
        self.assertTrue(is_match, f"Failed: {reasons}")
        
        # Test BEDROOMS_MAX rule with float string "2.0" (should pass)
        rule_max = SearchRule(
            id=2, user_id=123, rule_type=RuleType.BEDROOMS_MAX, 
            value="2.0", is_active=True
        )
        is_match, reasons = self.matcher.evaluate_listing(enriched, [rule_max])
        self.assertTrue(is_match, f"Failed: {reasons}")

    def test_float_price_rules(self):
        # Create a listing with 5000 price
        listing = Listing(
            id="test_price", source="test", url="url", title="title", 
            description="desc", location="loc", raw_text="text",
            posted_at=datetime.now()
        )
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_price = 5000
        
        # Test PRICE_MAX rule with float string "5500.0"
        rule_max = SearchRule(
            id=3, user_id=123, rule_type=RuleType.PRICE_MAX, 
            value="5500.0", is_active=True
        )
        is_match, reasons = self.matcher.evaluate_listing(enriched, [rule_max])
        self.assertTrue(is_match, f"Failed: {reasons}")
        
        # Test PRICE_MIN rule with float string "4500.0"
        rule_min = SearchRule(
            id=4, user_id=123, rule_type=RuleType.PRICE_MIN, 
            value="4500.0", is_active=True
        )
        is_match, reasons = self.matcher.evaluate_listing(enriched, [rule_min])
        self.assertTrue(is_match, f"Failed: {reasons}")

if __name__ == '__main__':
    unittest.main()
