import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.listing import Listing, EnrichedListing
from models.search_rule import SearchRule, RuleType
from core.matcher import ZeroAIUserMatcher
from utils.israeli_locations import get_location_db

def test_zvi_matching():
    print("Testing Zvi matching logic flow...")
    
    # 1. Construct the raw listing as it would be scraped
    raw = Listing(
        id="4dc9dd65b43fd686",
        source="facebook",
        url="https://www.facebook.com/groups/333022240594651/posts/2110946456135545/",
        title="צביקה בירן",
        description="רחוב ארלוזורוב 22 רמת גן...",
        location="רמת גן", # Scraper set correct raw location
        raw_text="צביקה בירן\nרחוב ארלוזורוב 22 רמת גן..."
    )
    
    # 2. Construct EnrichedListing simulating the new parser output
    enriched = EnrichedListing(
        listing=raw,
        extracted_price=7000,
        extracted_bedrooms=3,
        extracted_street="ארלוזורוב 22",
        extracted_neighborhood="הצפון הישן", # Overlap error from street
        extracted_location="תל אביב", # Overlap error from street
        extracted_city="רמת גן", # Correctly extracted/normalized city!
        area_matches={"רמת גן": True}
    )
    
    matcher = ZeroAIUserMatcher()
    
    # 3. Create a search rule for Tel Aviv / Old North
    rule_tlv = SearchRule(
        id=1,
        user_id=123,
        rule_type=RuleType.AREA,
        value="תל אביב",
        original_text="תל אביב"
    )
    
    rule_old_north = SearchRule(
        id=2,
        user_id=123,
        rule_type=RuleType.AREA,
        value="הצפון הישן",
        original_text="הצפון הישן"
    )
    
    # 4. Check matching
    res_tlv, reasons_tlv = matcher.evaluate_listing(enriched, [rule_tlv], allow_roomies=True, allow_sublets=True)
    res_on, reasons_on = matcher.evaluate_listing(enriched, [rule_old_north], allow_roomies=True, allow_sublets=True)
    
    print(f"Match against Tel Aviv rule: {res_tlv}")
    if reasons_tlv:
        print(f"  Rejection Reason: {reasons_tlv[0]}")
        
    print(f"Match against Old North rule: {res_on}")
    if reasons_on:
        print(f"  Rejection Reason: {reasons_on[0]}")
        
    # Check results
    if not res_tlv and not res_on:
        print("✅ Success: The listing was correctly rejected for both Tel Aviv and Old North rules!")
    else:
        print("❌ Failure: Listing incorrectly matched Tel Aviv/Old North rules.")

if __name__ == "__main__":
    test_zvi_matching()
