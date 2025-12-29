
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from core.processing import ProcessingService
from database.repositories import UserRepository, RuleRepository
from models.search_rule import SearchRule, RuleType
from models.user import User
from models.listing import EnrichedListing, Listing
from bot.telegram_bot import ApartmentBot
from database import get_db

@pytest.mark.asyncio
async def test_handle_deleted_user():
    # Setup DB
    db = await get_db()
    await db.initialize()
    
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    
    # Create dummy user
    user_id = 999999
    user = User(
        telegram_id=user_id,
        chat_id=user_id,
        username="deleted_user",
        created_at=datetime.now(),
        is_active=True
    )
    await user_repo.create(user)
    
    # Add a rule so processing happens
    rule = SearchRule(
        user_id=user_id,
        rule_type=RuleType.PRICE_MAX,
        value="5000",
        original_text="max price 5000"
    )
    await rule_repo.create(rule)
    
    # Create dummy listing that matches
    listing = EnrichedListing(
        listing=Listing(
            id="test_listing_1",
            source="test",
            url="http://test.com",
            title="Test Apt",
            description="Good apt",
            location="Tel Aviv",
            raw_text="דירה טובה בתל אביב 4000 שקל",
            price=4000
        ),
        extracted_price=4000,
        extracted_location="Tel Aviv"
    )
    
    # Mock Bot
    bot_mock = MagicMock(spec=ApartmentBot)
    # Simulate Chat not found error
    bot_mock.send_listing_notification = AsyncMock(side_effect=Exception("Chat not found"))
    
    # Init Service
    service = ProcessingService(bot=bot_mock)
    
    # Run processing
    print("Running match_user_to_listings...")
    await service.match_user_to_listings(user, [listing])
    
    # Check if user is deleted
    exists = await user_repo.exists(user_id)
    print(f"User exists after error: {exists}")
    
    # Clean up (if test failed and user still exists)
    if exists:
        await user_repo.delete_user(user_id)
        
    assert not exists, "User should have been deleted after 'Chat not found' error"

if __name__ == "__main__":
    asyncio.run(test_handle_deleted_user())
