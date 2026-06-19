import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from core.processing import ProcessingService
from database.repositories import UserRepository, RuleRepository, RejectionRepository
from models.search_rule import SearchRule, RuleType
from models.user import User
from models.listing import EnrichedListing, Listing
from bot.telegram_bot import ApartmentBot
from database import get_db

@pytest.mark.asyncio
async def test_sublets_filtering(db, monkeypatch):
    import database.connection
    monkeypatch.setattr(database.connection, "_db_manager", db)
    
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    rejection_repo = RejectionRepository(db)
    
    # Create test user
    user_id = 999999
    user = User(
        telegram_id=user_id,
        chat_id=user_id,
        username="sublets_tester",
        created_at=datetime.now(),
        is_active=True,
        allow_sublets=False  # Sublets are disabled by default
    )
    await user_repo.create(user)
    
    # Add an active rule so they qualify for processing
    rule = SearchRule(
        user_id=user_id,
        rule_type=RuleType.PRICE_MAX,
        value="6000",
        original_text="עד 6000 שח"
    )
    await rule_repo.create(rule)
    
    # Create a sublet listing
    sublet_listing = EnrichedListing(
        listing=Listing(
            id="sublet_apt_1",
            source="test",
            url="http://test.com/1",
            title="Sublet in Florentine",
            description="Beautiful sublet",
            location="Florentine",
            raw_text="סאבלט מהמם בפלורנטין",
            price=4000,
            is_sublet=True
        ),
        extracted_price=4000,
        extracted_location="Florentine",
        is_sublet=True,
        sublet_duration="חודשיים",
        sublet_dates="1.7 עד 31.8"
    )
    
    # Create a non-sublet listing
    whole_listing = EnrichedListing(
        listing=Listing(
            id="whole_apt_1",
            source="test",
            url="http://test.com/2",
            title="Whole 2-room Apt",
            description="Beautiful apartment",
            location="Florentine",
            raw_text="דירת 2 חדרים שלמה להשכרה בפלורנטין",
            price=5500,
            is_sublet=False
        ),
        extracted_price=5500,
        extracted_location="Florentine",
        is_sublet=False
    )
    
    # Mock bot
    bot_mock = MagicMock(spec=ApartmentBot)
    bot_mock.send_listing_notification = AsyncMock()
    
    service = ProcessingService(bot=bot_mock)
    
    # 1. Test filtering when allow_sublets is False
    await service.match_user_to_listings(user, [sublet_listing, whole_listing])
    
    # The sublet listing should NOT have sent notification, only the whole listing
    assert bot_mock.send_listing_notification.call_count == 1
    # Check that it was called with whole_listing, not sublet_listing
    args, kwargs = bot_mock.send_listing_notification.call_args
    assert kwargs['enriched'].listing.id == "whole_apt_1"
    
    # Check that sublet listing rejection was logged in rejection repository
    rejections = await rejection_repo.get_user_rejections(user_id)
    assert len(rejections) == 1
    assert rejections[0].listing_id == "sublet_apt_1"
    assert rejections[0].reasons[0] == "סאבלט (קבלה מנוטרלת בהגדרות שלך)"
    
    # Clean up rejections and user notifications
    await db.execute("DELETE FROM rejection_logs WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM sent_notifications WHERE user_id = ?", (user_id,))
    bot_mock.send_listing_notification.reset_mock()
    
    # 2. Test matching when allow_sublets is True
    user.allow_sublets = True
    await user_repo.create(user)  # update in database
    
    await service.match_user_to_listings(user, [sublet_listing, whole_listing])
    
    # Both listings should have sent notifications
    assert bot_mock.send_listing_notification.call_count == 2
    
    # Clean up DB
    await user_repo.delete_user(user_id)

if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
