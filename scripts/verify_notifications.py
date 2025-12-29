import asyncio
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db
from database.repositories import NotificationRepository, UserRepository, RuleRepository
from core.processing import ProcessingService
from models.listing import EnrichedListing, Listing
from models.user import User
from models.search_rule import SearchRule, RuleType
from datetime import datetime

class MockBot:
    def __init__(self):
        self.sent_messages = []
        
    async def send_listing_notification(self, chat_id, enriched, sass_intro=""):
        print(f"MOCK BOT: Sending notification to {chat_id} for listing {enriched.listing.id}")
        self.sent_messages.append(enriched.listing.id)

async def test_notification_logic():
    print("Initializing DB...")
    db = await get_db()
    
    # Setup Repos
    notif_repo = NotificationRepository(db)
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    
    # Create Dummy User
    user_id = 12345
    chat_id = 54321
    await user_repo.create(User(
        telegram_id=user_id,
        chat_id=chat_id,
        username="test_user",
        created_at=datetime.now(),
        is_active=True
    ))
    
    # Create Rule (Price < 5000)
    await rule_repo.delete_all_user_rules(user_id)
    await rule_repo.create(SearchRule(
        user_id=user_id,
        rule_type=RuleType.PRICE_MAX,
        value="5000",
        original_text="עד 5000"
    ))
    
    # Create Dummy Listings
    listing1 = EnrichedListing(
        listing=Listing(id="L1", source="fb", url="http://1", title="Cheap apt", description="cheap", location="TLV", raw_text="cheap", posted_at=datetime.now(), scraped_at=datetime.now()),
        extracted_price=4000,
        extracted_location="TLV",
        extracted_bedrooms=2,
        extracted_neighborhood="Florentin",
        has_broker_fee=False,
        attributes={},
        area_matches={},
        bordering_areas={}
    )
    
    listing2 = EnrichedListing(
        listing=Listing(id="L2", source="fb", url="http://2", title="Expensive apt", description="expensive", location="TLV", raw_text="expensive", posted_at=datetime.now(), scraped_at=datetime.now()),
        extracted_price=6000,
        extracted_location="TLV",
        extracted_bedrooms=2,
        extracted_neighborhood="Florentin",
        has_broker_fee=False,
        attributes={},
        area_matches={},
        bordering_areas={}
    )
    
    # Clear previous notifications for this user/listing
    await db.execute("DELETE FROM sent_notifications WHERE user_id = ?", (user_id,))
    
    # Initialize Service
    mock_bot = MockBot()
    service = ProcessingService(bot=mock_bot)
    
    print("\n--- Test 1: First Match ---")
    user = await user_repo.get_by_telegram_id(user_id)
    sent_count = await service.match_user_to_listings(user, [listing1, listing2])
    
    print(f"Sent count: {sent_count}")
    assert sent_count == 1
    assert "L1" in mock_bot.sent_messages
    assert "L2" not in mock_bot.sent_messages
    
    print("\n--- Test 2: Re-run (Should Deduplicate) ---")
    mock_bot.sent_messages = [] # Reset mock
    sent_count = await service.match_user_to_listings(user, [listing1, listing2])
    
    print(f"Sent count: {sent_count}")
    assert sent_count == 0
    assert not mock_bot.sent_messages
    
    print("\n--- Test 3: New Match ---")
    listing3 = EnrichedListing(
        listing=Listing(id="L3", source="fb", url="http://3", title="Another cheap apt", description="cheap", location="TLV", raw_text="cheap", posted_at=datetime.now(), scraped_at=datetime.now()),
        extracted_price=4500,
        extracted_location="TLV",
        extracted_bedrooms=2,
        extracted_neighborhood="Florentin",
        has_broker_fee=False,
        attributes={},
        area_matches={},
        bordering_areas={}
    )
    
    sent_count = await service.match_user_to_listings(user, [listing1, listing2, listing3])
    print(f"Sent count: {sent_count}")
    assert sent_count == 1
    assert "L3" in mock_bot.sent_messages
    
    print("\n--- Test 4: Force Resend (include_sent=True) ---")
    mock_bot.sent_messages = []
    # Should resend all 3 listings (L1, L2, L3) - wait, L2 was never matched because price 6000 > 5000 rule
    # L1 and L3 match.
    sent_count = await service.match_user_to_listings(
        user, 
        [listing1, listing2, listing3], 
        include_sent=True
    )
    print(f"Sent count: {sent_count}")
    assert sent_count == 2 # L1 and L3
    assert "L1" in mock_bot.sent_messages
    assert "L3" in mock_bot.sent_messages
    
    print("\n✅ Verification Passed!")

if __name__ == "__main__":
    asyncio.run(test_notification_logic())
