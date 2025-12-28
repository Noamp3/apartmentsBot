import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import ApartmentBotApplication
from models.user import User
from models.listing import Listing, EnrichedListing
from models.search_rule import SearchRule, RuleType

async def test_failover():
    print("Testing processing cycle failover...")
    
    app = ApartmentBotApplication()
    
    # Mock repositories
    app.facebook_scraper = AsyncMock()
    app.facebook_scraper.scrape.return_value = []
    
    app.yad2_scraper = AsyncMock()
    app.yad2_scraper.scrape.return_value = [
        Listing(
            id="test-1", source="test", url="http://test.com", 
            title="Test Listing", description="Desc", location="Loc", 
            raw_text="raw", posted_at=None, scraped_at=None
        )
    ]
    
    # Mock enricher
    app.enricher = AsyncMock()
    app.enricher.enrich_listings.return_value = [
        EnrichedListing( 
            listing=app.yad2_scraper.scrape.return_value[0],
            extracted_price=1000,
            extracted_bedrooms=3,
            extracted_location="Loc",
            extracted_neighborhood="",
            has_broker_fee=False,
            attributes={}, area_matches={}, bordering_areas={}
        )
    ]
    
    # Mock users
    from datetime import datetime
    users = [
        User(telegram_id=1, chat_id=101, username="UserA", first_notified_at=datetime.now()), # Not new
        User(telegram_id=2, chat_id=102, username="UserB", first_notified_at=datetime.now()),
        User(telegram_id=3, chat_id=103, username="UserC", first_notified_at=datetime.now())
    ]
    
    # Mock DB and Repos
    db_mock = AsyncMock()
    
    user_repo_mock = AsyncMock()
    user_repo_mock.get_all_active.return_value = users
    
    rule_repo_mock = AsyncMock()
    def get_rules_side_effect(user_id):
        # Return a dummy rule for each user
        from datetime import datetime
        return [SearchRule(id=1, user_id=user_id, rule_type=RuleType.PRICE_MAX, value="2000", original_text="", is_active=True, created_at=datetime.now())]
    rule_repo_mock.get_user_rules.side_effect = get_rules_side_effect
    
    seen_repo_mock = AsyncMock()
    seen_repo_mock.filter_new.return_value = app.yad2_scraper.scrape.return_value
    
    listing_repo_mock = AsyncMock()
    rejection_repo_mock = AsyncMock()
    
    # Patch main.py imports
    with patch('main.get_db', return_value=db_mock), \
         patch('main.UserRepository', return_value=user_repo_mock), \
         patch('main.RuleRepository', return_value=rule_repo_mock), \
         patch('main.SeenListingsRepository', return_value=seen_repo_mock), \
         patch('main.ListingRepository', return_value=listing_repo_mock), \
         patch('main.RejectionRepository', return_value=rejection_repo_mock):
         
         # Mock matcher
         app.matcher = MagicMock()
         
         def matcher_side_effect(enriched, rules):
             # Fail for user 2 (telegram_id=2)
             if rules and rules[0].user_id == 2:
                  print(">>> Simulating EXCEPTION for User 2 <<<")
                  raise Exception("Simulated Failure for User 2")
             return True, [] # Always match for others
             
         app.matcher.evaluate_listing.side_effect = matcher_side_effect
         
         # Mock bot
         app.bot = AsyncMock()
         
         # Run cycle
         print("Running processing cycle...")
         await app.run_processing_cycle()
         print("Cycle complete.")
         
         # Assertions
         calls = app.bot.send_listing_notification.call_args_list
         print(f"Notifications sent: {len(calls)}")
         
         user_ids_notified = [c.kwargs['chat_id'] for c in calls]
         
         success = True
         if 101 in user_ids_notified:
             print("✅ User A (101) notified.")
         else:
             print("❌ User A (101) NOT notified.")
             success = False
             
         if 103 in user_ids_notified:
             print("✅ User C (103) notified.")
         else:
             print("❌ User C (103) NOT notified.")
             success = False

         if 102 not in user_ids_notified:
             print("✅ User B (102) correctly NOT notified (failed).")
         else:
             print("❌ User B (102) WAS notified (should have failed).")
             success = False
             
         if success:
             print("\nTEST PASSED: Failover logic works!")
         else:
             print("\nTEST FAILED: Failover not working as expected.")

if __name__ == "__main__":
    asyncio.run(test_failover())
