import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram import Update, User as TGUser, Chat as TGChat, CallbackQuery, InlineKeyboardButton
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository, NotificationRepository, ListingRepository
from bot.handlers.callback_handler import CallbackHandler
from models.user import User
from models.search_rule import SearchRule, RuleType
from models.listing import Listing, EnrichedListing
from datetime import datetime

@pytest.mark.asyncio
async def test_admin_user_inspection():
    db = await get_db()
    await db.initialize()
    
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    notification_repo = NotificationRepository(db)
    listing_repo = ListingRepository(db)
    
    admin_id = 111111111
    user_id = 222222222
    
    # 1. Clean up users if they exist
    if await user_repo.exists(admin_id):
        await user_repo.delete_user(admin_id)
    if await user_repo.exists(user_id):
        await user_repo.delete_user(user_id)
        
    # 2. Create admin and regular user
    admin_obj = User(telegram_id=admin_id, chat_id=admin_id, username="admin_user", is_admin=True)
    user_obj = User(telegram_id=user_id, chat_id=user_id, username="normal_user", is_admin=False)
    await user_repo.create(admin_obj)
    await user_repo.create(user_obj)
    
    # 3. Create some rules and a match
    rule = SearchRule(user_id=user_id, rule_type=RuleType.AREA, value="פלורנטין", original_text="פלורנטין")
    await rule_repo.create(rule)
    
    listing = Listing(id="listing_test_1", source="facebook", url="http://facebook.com/1", title="דירת 2 חדרים בפלורנטין", description="משהו טוב", location="פלורנטין", raw_text="דירת 2 חדרים בפלורנטין")
    enriched = EnrichedListing(listing=listing, extracted_price=4500, extracted_bedrooms=2, extracted_location="פלורנטין", extracted_neighborhood="פלורנטין")
    await listing_repo.save_enriched(enriched)
    await notification_repo.mark_sent(user_id, "listing_test_1")
    
    # 4. Setup mock Update and CallbackQuery
    callback_handler = CallbackHandler()
    
    effective_user_mock = MagicMock(spec=TGUser)
    effective_user_mock.id = admin_id
    effective_user_mock.username = "admin_user"
    
    effective_chat_mock = MagicMock(spec=TGChat)
    effective_chat_mock.id = admin_id
    
    cb_update_mock = MagicMock(spec=Update)
    cb_update_mock.effective_user = effective_user_mock
    cb_update_mock.effective_chat = effective_chat_mock
    
    query_mock = MagicMock(spec=CallbackQuery)
    query_mock.from_user = effective_user_mock
    query_mock.answer = AsyncMock()
    query_mock.edit_message_text = AsyncMock()
    query_mock.edit_message_reply_markup = AsyncMock()
    cb_update_mock.callback_query = query_mock
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": None, "processing_service": None}
    
    # Test _show_admin_users (admin menu users list)
    query_mock.data = "admin_menu_users"
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    # Verify we edited the text
    assert query_mock.edit_message_text.called
    args, kwargs = query_mock.edit_message_text.call_args
    msg_text = args[0]
    assert "@normal_user" in msg_text
    
    # Verify the keyboard has a button for normal_user
    assert query_mock.edit_message_reply_markup.called
    reply_markup = query_mock.edit_message_reply_markup.call_args[1]["reply_markup"]
    buttons = reply_markup.inline_keyboard
    flat_buttons = [btn for row in buttons for btn in row]
    assert any(btn.callback_data == f"admin_view_user:{user_id}" for btn in flat_buttons)
    
    # Reset mocks for user detail test
    query_mock.edit_message_text.reset_mock()
    query_mock.edit_message_reply_markup.reset_mock()
    
    # Test _show_admin_user_detail
    query_mock.data = f"admin_view_user:{user_id}"
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    assert query_mock.edit_message_text.called
    args, kwargs = query_mock.edit_message_text.call_args
    msg_text = args[0]
    assert "normal_user" in msg_text
    assert f"מזהה טלגרם:</b> <code>{user_id}</code>" in msg_text
    assert "כללים:</b> <code>1</code>" in msg_text
    assert "התאמות (שידוכים):</b> <code>1</code>" in msg_text
    
    # Verify buttons for rules and matches exist
    reply_markup = query_mock.edit_message_reply_markup.call_args[1]["reply_markup"]
    flat_buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
    assert any(btn.callback_data == f"admin_user_rules:{user_id}" for btn in flat_buttons)
    assert any(btn.callback_data == f"admin_user_matches:{user_id}" for btn in flat_buttons)
    
    # Reset mocks for user rules test
    query_mock.edit_message_text.reset_mock()
    query_mock.edit_message_reply_markup.reset_mock()
    
    # Test _show_admin_user_rules
    query_mock.data = f"admin_user_rules:{user_id}"
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    assert query_mock.edit_message_text.called
    args, kwargs = query_mock.edit_message_text.call_args
    msg_text = args[0]
    assert "כללי חיפוש עבור" in msg_text
    assert "פלורנטין" in msg_text
    
    # Reset mocks for user matches test
    query_mock.edit_message_text.reset_mock()
    query_mock.edit_message_reply_markup.reset_mock()
    
    # Test _show_admin_user_matches
    query_mock.data = f"admin_user_matches:{user_id}"
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    assert query_mock.edit_message_text.called
    args, kwargs = query_mock.edit_message_text.call_args
    msg_text = args[0]
    assert "הדירות האחרונות שהתאימו" in msg_text
    assert "דירת 2 חדרים בפלורנטין" in msg_text
    assert "4,500 ₪" in msg_text
    
    # Cleanup
    await user_repo.delete_user(admin_id)
    await user_repo.delete_user(user_id)
