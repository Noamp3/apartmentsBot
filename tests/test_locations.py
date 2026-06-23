# tests/test_locations.py
"""Tests for Israeli location matching."""

import pytest
from utils.israeli_locations import IsraeliLocationDatabase


class TestIsraeliLocationDatabase:
    """Test location matching functionality."""
    
    def setup_method(self):
        self.db = IsraeliLocationDatabase()
    
    def test_exact_neighborhood_match(self):
        """Test exact neighborhood matching."""
        is_match, match_type, _ = self.db.is_location_match(
            "פלורנטין, תל אביב",
            "פלורנטין"
        )
        assert is_match
        assert match_type == "exact"
    
    def test_bordering_neighborhood_match(self):
        """Test bordering neighborhood matching."""
        is_match, match_type, _ = self.db.is_location_match(
            "נווה צדק",
            "פלורנטין"
        )
        assert is_match
        assert match_type == "bordering"
    
    def test_city_contains_match(self):
        """Test city-level matching."""
        is_match, match_type, _ = self.db.is_location_match(
            "רמת אביב",
            "תל אביב"
        )
        assert is_match
        assert match_type == "contains"
    
    def test_city_alias_match(self):
        """Test city alias matching."""
        is_match, match_type, _ = self.db.is_location_match(
            "תל אביב יפו",
            "ת\"א"
        )
        assert is_match
    
    def test_no_match_different_cities(self):
        """Test non-matching locations."""
        is_match, match_type, _ = self.db.is_location_match(
            "הרצליה",
            "תל אביב"
        )
        assert not is_match
        assert match_type == "none"
    
    def test_bordering_disabled(self):
        """Test that bordering can be disabled."""
        is_match, match_type, _ = self.db.is_location_match(
            "נווה צדק",
            "פלורנטין",
            allow_bordering=False
        )
        # Should not match because exact match is False
        # נווה צדק is not פלורנטין
        assert not is_match or match_type != "bordering"
    
    def test_expand_area_search(self):
        """Test area expansion."""
        expanded = self.db.expand_area_search("פלורנטין")
        assert "פלורנטין" in expanded
        assert "נווה צדק" in expanded  # Bordering
    
    def test_normalize_location(self):
        """Test location normalization."""
        result = self.db.normalize_location("דירה בפלורנטין תל אביב")
        assert result["city"] == "תל אביב"
        assert result["neighborhood"] == "פלורנטין"

    def test_unrelated_neighborhood_no_match(self):
        """Test that unrelated neighborhoods in the same city do not match."""
        is_match, match_type, _ = self.db.is_location_match(
            "רמת אביב, תל אביב",
            "פלורנטין"
        )
        assert not is_match
        assert match_type == "none"

    def test_reverse_containment_only_when_unspecified(self):
        """Test that reverse containment matches only when neighborhood is unspecified."""
        is_match, match_type, _ = self.db.is_location_match(
            "תל אביב",
            "פלורנטין"
        )
        assert is_match
        assert match_type == "contains"

    def test_matcher_area_match_ignores_unrelated_extracted_neighborhood(self):
        """Test that ZeroAIUserMatcher correctly identifies extracted neighborhood and doesn't trigger city-wide containment."""
        from core.matcher import ZeroAIUserMatcher
        from models.listing import Listing, EnrichedListing
        from models.search_rule import SearchRule, RuleType
        from datetime import datetime

        matcher = ZeroAIUserMatcher()
        listing = Listing(
            id="test_hamishtela", source="facebook", url="url", title="title", 
            description="להשכרה בתל אביב שכונת המשתלה", location="תל אביב", raw_text="text",
            posted_at=datetime.now()
        )
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_location = "תל אביב"
        enriched.extracted_neighborhood = "המשתלה"

        rule = SearchRule(
            id=1, user_id=123, rule_type=RuleType.AREA, 
            value="פלורנטין", is_active=True
        )

        is_match, reasons = matcher.evaluate_listing(enriched, [rule])
        assert not is_match
        assert any("לא תואם" in r for r in reasons)

    def test_multiple_area_rules_evaluated_as_or(self):
        """Test that multiple active AREA rules are evaluated as an OR constraint rather than AND constraint."""
        from core.matcher import ZeroAIUserMatcher
        from models.listing import Listing, EnrichedListing
        from models.search_rule import SearchRule, RuleType
        from datetime import datetime

        matcher = ZeroAIUserMatcher()
        
        # Create listing in Florentin
        listing = Listing(
            id="test_florentin_or", source="facebook", url="url", title="title", 
            description="להשכרה בפלורנטין", location="תל אביב", raw_text="text",
            posted_at=datetime.now()
        )
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_location = "תל אביב"
        enriched.extracted_neighborhood = "פלורנטין"

        # Rules for Florentin OR Lev HaIr
        rule_florentin = SearchRule(
            id=1, user_id=123, rule_type=RuleType.AREA, 
            value="פלורנטין", is_active=True
        )
        rule_lev_hair = SearchRule(
            id=2, user_id=123, rule_type=RuleType.AREA, 
            value="לב העיר", is_active=True
        )

        # Florenin listing should pass when evaluated with BOTH rules active (OR logic)
        is_match, reasons = matcher.evaluate_listing(enriched, [rule_florentin, rule_lev_hair])
        assert is_match, f"Failed: {reasons}"
        assert len(reasons) == 0

    def test_is_city_mismatch(self):
        """Test the is_city_mismatch helper method."""
        # Exact and alias matches
        assert not self.db.is_city_mismatch("תל אביב", "תל אביב")
        assert not self.db.is_city_mismatch("תל-אביב", "תל אביב")
        assert not self.db.is_city_mismatch("תא", "תל אביב")
        assert not self.db.is_city_mismatch("תל אביב - יפו", "תל אביב")
        assert not self.db.is_city_mismatch("בתא", "תל אביב")
        assert not self.db.is_city_mismatch("בחלקי תל אביב", "תל אביב")
        
        # Explicit mismatches
        assert self.db.is_city_mismatch("רמת גן", "תל אביב")
        assert self.db.is_city_mismatch("גבעתיים", "תל אביב")
        assert self.db.is_city_mismatch("נתיבות", "תל אביב")
        assert self.db.is_city_mismatch("הוד השרון", "תל אביב")

    def test_homonymous_neighborhood_override(self):
        """Test that matching a neighborhood in a different explicit city is discarded."""
        # Florentin is a TLV neighborhood, but the raw text mentions Ramat Gan
        res = self.db.normalize_location("פלורנטין רמת גן")
        assert res["city"] == "רמת גן"
        assert res["neighborhood"] is None
        
        # Lev HaIr in Ramat Gan
        res2 = self.db.normalize_location("לב העיר, רמת גן")
        assert res2["city"] == "רמת גן"
        assert res2["neighborhood"] is None

    def test_matcher_enforces_city_match(self):
        """Test that ZeroAIUserMatcher prevents listings from other cities from matching area rules."""
        from core.matcher import ZeroAIUserMatcher
        from models.listing import Listing, EnrichedListing
        from models.search_rule import SearchRule, RuleType
        from datetime import datetime

        matcher = ZeroAIUserMatcher()
        
        # Florentin in Ramat Gan (city mismatch!)
        listing = Listing(
            id="test_mismatch", source="facebook", url="url", title="title", 
            description="דירה בפלורנטין רמת גן", location="רמת גן", raw_text="text",
            posted_at=datetime.now()
        )
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_location = "רמת גן"
        enriched.extracted_neighborhood = ""

        rule = SearchRule(
            id=1, user_id=123, rule_type=RuleType.AREA, 
            value="פלורנטין", is_active=True
        )

        is_match, reasons = matcher.evaluate_listing(enriched, [rule])
        assert not is_match
        assert any("לא תואם" in r for r in reasons)

    def test_matcher_enforces_city_match_border_area(self):
        """Test that ZeroAIUserMatcher prevents listings from other cities from matching border area rules."""
        from core.matcher import ZeroAIUserMatcher
        from models.listing import Listing, EnrichedListing
        from models.search_rule import SearchRule, RuleType
        from datetime import datetime

        matcher = ZeroAIUserMatcher()
        
        # Listing in Givatayim (unidentified neighborhood, but city is Givatayim)
        listing = Listing(
            id="test_givatayim_border", source="facebook", url="url", title="title", 
            description="דירה בגבעתיים", location="גבעתיים", raw_text="text",
            posted_at=datetime.now()
        )
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_location = "גבעתיים"

        # User wants TLV border area
        rule = SearchRule(
            id=1, user_id=123, rule_type=RuleType.BORDER_AREA, 
            value="לב העיר,רוטשילד,הצפון הישן", is_active=True
        )

        is_match, reasons = matcher.evaluate_listing(enriched, [rule])
        assert not is_match
        assert any("לא תואם" in r for r in reasons)

    def test_matcher_rejects_empty_locations(self):
        """Test that ZeroAIUserMatcher rejects listings with completely empty location info."""
        from core.matcher import ZeroAIUserMatcher
        from models.listing import Listing, EnrichedListing
        from models.search_rule import SearchRule, RuleType
        from datetime import datetime

        matcher = ZeroAIUserMatcher()
        
        # Listing with completely empty location
        listing = Listing(
            id="test_empty_location", source="facebook", url="url", title="title", 
            description="description", location="", raw_text="text",
            posted_at=datetime.now()
        )
        enriched = EnrichedListing(listing=listing)
        enriched.extracted_location = ""
        enriched.extracted_neighborhood = ""
        enriched.extracted_street = ""

        # User wants TLV border area
        rule_border = SearchRule(
            id=1, user_id=123, rule_type=RuleType.BORDER_AREA, 
            value="לב העיר,רוטשילד,הצפון הישן", is_active=True
        )
        
        # User wants TLV area
        rule_area = SearchRule(
            id=2, user_id=123, rule_type=RuleType.AREA, 
            value="תל אביב", is_active=True
        )

        # Should be rejected for both
        is_match_border, reasons_border = matcher.evaluate_listing(enriched, [rule_border])
        assert not is_match_border
        assert any("לא תואם" in r for r in reasons_border)

        is_match_area, reasons_area = matcher.evaluate_listing(enriched, [rule_area])
        assert not is_match_area
        assert any("לא תואם" in r for r in reasons_area)

    def test_normalize_location_word_boundaries(self):
        """Test that normalize_location respects word boundaries to prevent substring matching bugs."""
        # Setup custom test keys in lookup to simulate 'שיר' being a registered street/alias
        from utils.israeli_locations import Neighborhood
        self.db.neighborhood_lookup["שיר"] = Neighborhood(
            name="הצפון הישן", city="תל אביב", aliases=[], bordering=[], area_type="central"
        )
        
        # Test substring inside another word should NOT match
        res_false = self.db.normalize_location("להשכרה, תפנו אליי לשירותכם")
        assert res_false["neighborhood"] is None
        
        # Test whole word should match
        res_true_1 = self.db.normalize_location("להשכרה ברחוב שיר בתל אביב")
        assert res_true_1["neighborhood"] == "הצפון הישן"
        
        # Clean up lookup
        if "שיר" in self.db.neighborhood_lookup:
            del self.db.neighborhood_lookup["שיר"]



