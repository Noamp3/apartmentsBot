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
