import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram import Update, User as TGUser, Chat as TGChat
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository
from bot.handlers.message_handler import MessageHandler
from models.search_rule import SearchRule, RuleType
from models.user import User
from datetime import datetime

@pytest.mark.asyncio
async def test_area_rule_splitting_on_parsing(db, monkeypatch):
    """Verify that parsing a rule with multiple neighborhoods splits them into separate AREA SearchRule instances."""
    monkeypatch.setattr("database.connection._db_manager", db)
    
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    
    test_user_id = 999111
    
    # Setup test user
    user_obj = User(
        telegram_id=test_user_id,
        chat_id=test_user_id,
        username="rule_splitter_user",
        created_at=datetime.now(),
        is_active=True
    )
    await user_repo.create(user_obj)
    
    # Mock AI Engine response to return a rule with multiple neighborhoods in a single rule entry
    mock_ai = MagicMock()
    mock_ai.parse_user_rules = AsyncMock(return_value=([
        {
            "type": "area",
            "value": "פלורנטין, לב העיר, נווה צדק",
            "original_text": "פלורנטין, לב העיר, נווה צדק"
        }
    ], "מעולה!"))
    
    msg_handler = MessageHandler(ai_engine=mock_ai)
    
    # Mock Update and Context
    update_mock = MagicMock(spec=Update)
    effective_user_mock = MagicMock(spec=TGUser)
    effective_user_mock.id = test_user_id
    effective_user_mock.username = "rule_splitter_user"
    effective_chat_mock = MagicMock(spec=TGChat)
    effective_chat_mock.id = test_user_id
    
    update_mock.effective_user = effective_user_mock
    update_mock.effective_chat = effective_chat_mock
    
    message_mock = MagicMock()
    message_mock.text = "אני רוצה פלורנטין, לב העיר, נווה צדק"
    message_mock.reply_text = AsyncMock()
    update_mock.message = message_mock
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": mock_ai}
    context_mock.user_data = {}
    
    # Handle the message to trigger rules parsing
    await msg_handler.handle_message(update_mock, context_mock)
    
    # Check pending confirmation in user_data
    pending = context_mock.user_data.get("pending_rule_confirmation")
    assert pending is not None
    
    all_pending_rules = pending.get("all_pending_rules", [])
    # Verify that it was split into 3 separate AREA rules!
    assert len(all_pending_rules) == 3
    assert all(r.rule_type == RuleType.AREA for r in all_pending_rules)
    
    values = [r.value for r in all_pending_rules]
    assert "פלורנטין" in values
    assert "לב העיר" in values
    assert "נווה צדק" in values


@pytest.mark.asyncio
async def test_natural_language_removals_from_comma_separated_rules(db, monkeypatch):
    """Verify that a user can remove a single neighborhood from a legacy comma-separated rule in their pending confirmation."""
    monkeypatch.setattr("database.connection._db_manager", db)
    
    user_repo = UserRepository(db)
    test_user_id = 999222
    
    user_obj = User(
        telegram_id=test_user_id,
        chat_id=test_user_id,
        username="remover_user",
        created_at=datetime.now(),
        is_active=True
    )
    await user_repo.create(user_obj)
    
    msg_handler = MessageHandler(ai_engine=None)
    
    # Setup legacy combined rule in pending confirmation
    legacy_rule = SearchRule(
        user_id=test_user_id,
        rule_type=RuleType.AREA,
        value="פלורנטין, נווה צדק, שפירא",
        original_text="פלורנטין, נווה צדק, שפירא"
    )
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {}
    context_mock.user_data = {
        "pending_rule_confirmation": {
            "user_id": test_user_id,
            "all_pending_rules": [legacy_rule],
            "border_rules_data": []
        }
    }
    
    # Mock Update for removal command "בלי שפירא"
    update_mock = MagicMock(spec=Update)
    effective_user_mock = MagicMock(spec=TGUser)
    effective_user_mock.id = test_user_id
    effective_user_mock.username = "remover_user"
    
    update_mock.effective_user = effective_user_mock
    update_mock.effective_chat = effective_user_mock
    
    message_mock = MagicMock()
    message_mock.text = "בלי שפירא"
    message_mock.reply_text = AsyncMock()
    update_mock.message = message_mock
    
    # Handle message to apply adjustments
    await msg_handler.handle_message(update_mock, context_mock)
    
    # Verify that "שפירא" was successfully removed from the pending rule!
    pending = context_mock.user_data.get("pending_rule_confirmation")
    assert pending is not None
    
    all_pending_rules = pending.get("all_pending_rules", [])
    assert len(all_pending_rules) == 1
    
    updated_rule = all_pending_rules[0]
    assert updated_rule.rule_type == RuleType.AREA
    
    # Verify value and display text updated
    assert updated_rule.value == "פלורנטין,נווה צדק"
    assert updated_rule.original_text == "פלורנטין, נווה צדק"
