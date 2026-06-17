import os
import json
import pytest
import shutil
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

from bot.formatters.listing_formatter import ListingFormatter
from bot.telegram_bot import ApartmentBot
from models.listing import Listing, EnrichedListing
from database.repositories import ListingRepository
from utils.screenshot_utils import (
    get_listing_screenshot_dir, 
    cleanup_screenshots, 
    cleanup_old_screenshots, 
    SCREENSHOTS_BASE_DIR
)


def test_format_listing_caption():
    # Construct a listing with a very long description
    long_desc = "זה תיאור דירה ארוך מאוד שיעבור את הגבול הרגיל " * 50
    enriched = EnrichedListing(
        listing=Listing(
            id="test_long_id",
            source="facebook",
            url="http://facebook.com/posts/1",
            title="דירה מדהימה להשכרה בפלורנטין",
            description=long_desc,
            location="Florentine",
            raw_text=long_desc,
            price=4500,
            screenshots={"post_screenshot": "path/to/post.png"}
        ),
        extracted_price=4500,
        extracted_location="Florentine",
        extracted_neighborhood="פלורנטין"
    )
    
    caption = ListingFormatter.format_listing_caption(enriched)
    
    # Assert total length is within Telegram caption limits
    assert len(caption) <= 1024
    assert "💰 *מחיר:* 4,500₪" in caption
    assert "📍 *מיקום:* פלורנטין" in caption
    assert "לצפייה בדירה" in caption
    assert "מקור: פייסבוק" in caption


@pytest.mark.asyncio
async def test_database_persistence_of_screenshots(db):
    listing_repo = ListingRepository(db)
    
    screenshots_data = {
        "post_screenshot": "data/screenshots/test_db_id/post.png",
        "gallery_screenshots": ["data/screenshots/test_db_id/gallery_0.png"]
    }
    
    enriched = EnrichedListing(
        listing=Listing(
            id="test_db_id",
            source="facebook",
            url="http://facebook.com/posts/2",
            title="דירה להשכרה",
            description="דירת שותפים נחמדה",
            location="Tel Aviv",
            raw_text="דירת שותפים נחמדה",
            price=3500,
            screenshots=screenshots_data
        ),
        extracted_price=3500,
        extracted_location="Tel Aviv"
    )
    
    # Save to database
    await listing_repo.save_enriched(enriched)
    
    # Load from database
    loaded = await listing_repo.get_enriched("test_db_id")
    
    assert loaded is not None
    assert loaded.listing.screenshots == screenshots_data
    assert loaded.listing.screenshots["post_screenshot"] == "data/screenshots/test_db_id/post.png"
    assert loaded.listing.screenshots["gallery_screenshots"] == ["data/screenshots/test_db_id/gallery_0.png"]


def test_screenshot_cleanup_utils():
    listing_id = "test_cleanup_id"
    target_dir = get_listing_screenshot_dir(listing_id)
    os.makedirs(target_dir, exist_ok=True)
    
    test_file = os.path.join(target_dir, "post.png")
    with open(test_file, "w") as f:
        f.write("dummy content")
        
    assert os.path.exists(test_file)
    
    cleanup_screenshots(listing_id)
    assert not os.path.exists(test_file)
    assert not os.path.exists(target_dir)


def test_cleanup_old_screenshots():
    # Setup base dir
    os.makedirs(SCREENSHOTS_BASE_DIR, exist_ok=True)
    
    old_listing_id = "old_listing_123"
    old_dir = get_listing_screenshot_dir(old_listing_id)
    os.makedirs(old_dir, exist_ok=True)
    
    new_listing_id = "new_listing_456"
    new_dir = get_listing_screenshot_dir(new_listing_id)
    os.makedirs(new_dir, exist_ok=True)
    
    # Touch files
    old_file = os.path.join(old_dir, "post.png")
    with open(old_file, "w") as f:
        f.write("old")
        
    new_file = os.path.join(new_dir, "post.png")
    with open(new_file, "w") as f:
        f.write("new")
        
    # Change access and modification time of old dir to 3 hours ago
    three_hours_ago = (datetime.now() - timedelta(hours=3)).timestamp()
    os.utime(old_dir, (three_hours_ago, three_hours_ago))
    os.utime(old_file, (three_hours_ago, three_hours_ago))
    
    # Run cleanup specifying 2 hours threshold
    cleanup_old_screenshots(max_age_hours=2)
    
    # The old directory should be deleted, new should remain
    assert not os.path.exists(old_dir)
    assert os.path.exists(new_dir)
    
    # Cleanup new dir
    cleanup_screenshots(new_listing_id)


@pytest.mark.asyncio
async def test_bot_send_listing_notification_with_screenshots(monkeypatch):
    bot_instance = ApartmentBot()
    bot_instance.application = MagicMock()
    bot_instance.application.bot = AsyncMock()
    
    # Mock database manager / user repository for logging
    mock_db = MagicMock()
    mock_user_repo = MagicMock()
    mock_user_repo.get_by_chat_id = AsyncMock(return_value=MagicMock(telegram_id=123, username="testuser", persona="barakush"))
    
    import database
    monkeypatch.setattr(database, "get_db", AsyncMock(return_value=mock_db))
    
    import bot.telegram_bot
    monkeypatch.setattr(bot.telegram_bot, "UserRepository", MagicMock(return_value=mock_user_repo))
    
    # Create temp files to simulate screenshots existing on disk
    listing_id = "test_bot_id"
    target_dir = get_listing_screenshot_dir(listing_id)
    os.makedirs(target_dir, exist_ok=True)
    
    post_png = os.path.join(target_dir, "post.png")
    with open(post_png, "w") as f:
        f.write("data")
        
    gallery_png = os.path.join(target_dir, "gallery_0.png")
    with open(gallery_png, "w") as f:
        f.write("data")
        
    enriched = EnrichedListing(
        listing=Listing(
            id=listing_id,
            source="facebook",
            url="http://facebook.com/posts/3",
            title="דירה נחמדה",
            description="תיאור קצר",
            location="Tel Aviv",
            raw_text="תיאור קצר",
            price=4000,
            screenshots={
                "post_screenshot": post_png,
                "gallery_screenshots": [gallery_png]
            }
        ),
        extracted_price=4000,
        extracted_location="Tel Aviv"
    )
    
    # Test 1: Send within 1024 char limit (should use single media group with caption)
    await bot_instance.send_listing_notification(chat_id=12345, enriched=enriched)
    
    assert bot_instance.application.bot.send_media_group.call_count == 1
    args, kwargs = bot_instance.application.bot.send_media_group.call_args
    assert kwargs["chat_id"] == 12345
    assert len(kwargs["media"]) == 2
    # First item should have the caption
    assert kwargs["media"][0].caption is not None
    assert "💰 *מחיר:* 4,000₪" in kwargs["media"][0].caption
    
    # Clean mock counts
    bot_instance.application.bot.send_media_group.reset_mock()
    bot_instance.application.bot.send_message.reset_mock()
    
    # Test 2: Send with extremely long message (> 1024 chars)
    # This should trigger sending text message first, then media group without caption
    bot_instance.formatter = MagicMock()
    bot_instance.formatter.format_listing = MagicMock(return_value="A" * 1100)
    
    await bot_instance.send_listing_notification(chat_id=12345, enriched=enriched)
    
    # Should send message first
    assert bot_instance.application.bot.send_message.call_count == 1
    # Then send media group
    assert bot_instance.application.bot.send_media_group.call_count == 1
    
    group_args, group_kwargs = bot_instance.application.bot.send_media_group.call_args
    # First item caption should be None because text was sent separately
    assert group_kwargs["media"][0].caption is None
    
    # Cleanup temp screenshot files
    cleanup_screenshots(listing_id)
