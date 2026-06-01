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
