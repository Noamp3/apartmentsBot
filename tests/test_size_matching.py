import pytest
from datetime import datetime
from models.search_rule import SearchRule, RuleType
from models.listing import EnrichedListing, Listing
from core.matcher import ZeroAIUserMatcher, RulePreFilter

def test_size_matching_forgiving():
    matcher = ZeroAIUserMatcher()
    
    # 1. Create a listing with NO size (None)
    listing_no_size = EnrichedListing(
        listing=Listing(
            id="apt_no_size",
            source="test",
            url="http://test.com/1",
            title="Apt 1",
            description="Nice apartment",
            location="Tel Aviv",
            raw_text="דירה יפה בתל אביב",
            price=5000,
            bedrooms=2
        ),
        extracted_price=5000,
        extracted_bedrooms=2,
        extracted_size=None # No size!
    )
    
    # User rule: minimum size of 80 sqm
    rule = SearchRule(
        user_id=1,
        rule_type=RuleType.SIZE_MIN,
        value="80",
        original_text="מינימום 80 מטר"
    )
    
    # Matching should pass (forgiving rule!)
    passes_hard, _ = RulePreFilter.passes_hard_rules(listing_no_size, [rule])
    assert passes_hard is True

def test_size_matching_enforced():
    # 2. Create a listing with size 70 sqm (less than 80)
    listing_small = EnrichedListing(
        listing=Listing(
            id="apt_small",
            source="test",
            url="http://test.com/2",
            title="Apt 2",
            description="Small apartment",
            location="Tel Aviv",
            raw_text="דירת 70 מטר יפה",
            price=5000,
            bedrooms=2,
            size=70
        ),
        extracted_price=5000,
        extracted_bedrooms=2,
        extracted_size=70
    )
    
    rule = SearchRule(
        user_id=1,
        rule_type=RuleType.SIZE_MIN,
        value="80",
        original_text="מינימום 80 מטר"
    )
    
    # Matching should fail
    passes_hard, rejections = RulePreFilter.passes_hard_rules(listing_small, [rule])
    assert passes_hard is False
    assert len(rejections) == 1
    assert "גודל דירה 70 מ\"ר < מינימום 80 מ\"ר" in rejections[0]

def test_size_matching_success():
    # 3. Create a listing with size 90 sqm (greater than 80)
    listing_large = EnrichedListing(
        listing=Listing(
            id="apt_large",
            source="test",
            url="http://test.com/3",
            title="Apt 3",
            description="Large apartment",
            location="Tel Aviv",
            raw_text="דירת 90 מטר יפה",
            price=5000,
            bedrooms=2,
            size=90
        ),
        extracted_price=5000,
        extracted_bedrooms=2,
        extracted_size=90
    )
    
    rule = SearchRule(
        user_id=1,
        rule_type=RuleType.SIZE_MIN,
        value="80",
        original_text="מינימום 80 מטר"
    )
    
    # Matching should pass
    passes_hard, _ = RulePreFilter.passes_hard_rules(listing_large, [rule])
    assert passes_hard is True
