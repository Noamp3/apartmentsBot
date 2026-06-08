import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram import Update, User as TGUser, Chat as TGChat, CallbackQuery
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository, RuleRepository
from bot.handlers.command_handler import CommandHandler
from bot.handlers.callback_handler import CallbackHandler
from bot.handlers.message_handler import MessageHandler
from models.search_rule import RuleType

@pytest.mark.asyncio
async def test_complete_onboarding_flow(db, monkeypatch):
    import database.connection
    monkeypatch.setattr(database.connection, "_db_manager", db)
    
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    
    test_user_id = 987654321
    
    # 1. Clean up user and rules if they exist
    if await user_repo.exists(test_user_id):
        await user_repo.delete_user(test_user_id)
        
    assert not await user_repo.exists(test_user_id)
    
    # 2. Setup mock Update and Context for /start
    update_mock = MagicMock(spec=Update)
    effective_user_mock = MagicMock(spec=TGUser)
    effective_user_mock.id = test_user_id
    effective_user_mock.username = "test_onboard_user"
    effective_user_mock.first_name = "Noam"
    effective_chat_mock = MagicMock(spec=TGChat)
    effective_chat_mock.id = test_user_id
    
    update_mock.effective_user = effective_user_mock
    update_mock.effective_chat = effective_chat_mock
    
    message_mock = MagicMock()
    message_mock.reply_text = AsyncMock()
    update_mock.message = message_mock
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": None, "processing_service": None}
    context_mock.user_data = {}
    
    # --- STEP 1: Run /start to begin onboarding ---
    cmd_handler = CommandHandler()
    await cmd_handler.start(update_mock, context_mock)
    
    # Verify user registered with onboarding_step="choose_persona"
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user is not None
    assert user.onboarding_step == "choose_persona"
    assert message_mock.reply_text.called
    
    # --- STEP 2: Choose persona "barakush" via callback ---
    callback_handler = CallbackHandler()
    
    cb_update_mock = MagicMock(spec=Update)
    cb_update_mock.effective_user = effective_user_mock
    cb_update_mock.effective_chat = effective_chat_mock
    
    query_mock = MagicMock(spec=CallbackQuery)
    query_mock.data = "set_persona:barakush"
    query_mock.from_user = effective_user_mock
    query_mock.answer = AsyncMock()
    query_mock.edit_message_text = AsyncMock()
    cb_update_mock.callback_query = query_mock
    
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    # Verify persona updated and step advanced to ask_location
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user.persona == "barakush"
    assert user.onboarding_step == "ask_location"
    assert query_mock.edit_message_text.called
    
    # --- STEP 3: Send location "לב העיר" ---
    msg_handler = MessageHandler(ai_engine=None)
    
    loc_message_mock = MagicMock()
    loc_message_mock.text = "לב העיר"
    loc_message_mock.reply_text = AsyncMock()
    
    loc_update_mock = MagicMock(spec=Update)
    loc_update_mock.effective_user = effective_user_mock
    loc_update_mock.effective_chat = effective_chat_mock
    loc_update_mock.message = loc_message_mock
    
    await msg_handler.handle_message(loc_update_mock, context_mock)
    
    # Verify step advanced to ask_budget and onboarding_rules contains the location
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user.onboarding_step == "ask_budget"
    assert len(context_mock.user_data.get("onboarding_rules", [])) == 1
    assert context_mock.user_data["onboarding_rules"][0]["type"] == "area"
    assert context_mock.user_data["onboarding_rules"][0]["value"] == "לב העיר"
    assert loc_message_mock.reply_text.called
    
    # --- STEP 4: Send budget "5000" ---
    budget_message_mock = MagicMock()
    budget_message_mock.text = "5000 שקל בחודש"
    budget_message_mock.reply_text = AsyncMock()
    
    budget_update_mock = MagicMock(spec=Update)
    budget_update_mock.effective_user = effective_user_mock
    budget_update_mock.effective_chat = effective_chat_mock
    budget_update_mock.message = budget_message_mock
    
    await msg_handler.handle_message(budget_update_mock, context_mock)
    
    # Verify step advanced to ask_bedrooms and budget rule added
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user.onboarding_step == "ask_bedrooms"
    assert len(context_mock.user_data.get("onboarding_rules", [])) == 2
    assert context_mock.user_data["onboarding_rules"][1]["type"] == "price_max"
    assert context_mock.user_data["onboarding_rules"][1]["value"] == 5000
    assert budget_message_mock.reply_text.called
    
    # --- STEP 5: Send bedrooms "3 חדרים" (completes flow) ---
    beds_message_mock = MagicMock()
    beds_message_mock.text = "3 חדרים"
    beds_message_mock.reply_text = AsyncMock()
    
    beds_update_mock = MagicMock(spec=Update)
    beds_update_mock.effective_user = effective_user_mock
    beds_update_mock.effective_chat = effective_chat_mock
    beds_update_mock.message = beds_message_mock
    
    await msg_handler.handle_message(beds_update_mock, context_mock)
    
    # Verify onboarding_step is now None (completed)
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user.onboarding_step is None
    assert context_mock.user_data.get("onboarding_rules") is None
    
    # Verify rules are saved in database
    saved_rules = await rule_repo.get_user_rules(test_user_id)
    assert len(saved_rules) == 4
    
    rule_types = [r.rule_type for r in saved_rules]
    assert RuleType.AREA in rule_types
    assert RuleType.PRICE_MAX in rule_types
    assert RuleType.BEDROOMS_MIN in rule_types
    assert RuleType.BEDROOMS_MAX in rule_types
    
    price_rule = next(r for r in saved_rules if r.rule_type == RuleType.PRICE_MAX)
    assert price_rule.value == "5000"
    
    area_rule = next(r for r in saved_rules if r.rule_type == RuleType.AREA)
    assert area_rule.value == "לב העיר"
    
    # Clean up user and rules
    await user_repo.delete_user(test_user_id)


@pytest.mark.asyncio
async def test_onboarding_budget_range_and_min(db, monkeypatch):
    import database.connection
    monkeypatch.setattr(database.connection, "_db_manager", db)
    user_repo = UserRepository(db)
    
    test_user_id = 987654321
    if await user_repo.exists(test_user_id):
        await user_repo.delete_user(test_user_id)
        
    # Create test user
    user = await user_repo.get_or_create(telegram_id=test_user_id, chat_id=test_user_id, username="test_onboard_user")
    await user_repo.update_onboarding_step(test_user_id, "ask_budget")
    
    msg_handler = MessageHandler(ai_engine=None)
    
    # 1. Test Price Range
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": None, "processing_service": None}
    context_mock.user_data = {"onboarding_rules": []}
    
    budget_message_mock = MagicMock()
    budget_message_mock.text = "בין 3000 ל-5000 שקל"
    budget_message_mock.reply_text = AsyncMock()
    
    update_mock = MagicMock(spec=Update)
    update_mock.effective_user = MagicMock(id=test_user_id)
    update_mock.effective_chat = MagicMock(id=test_user_id)
    update_mock.message = budget_message_mock
    
    await msg_handler.handle_message(update_mock, context_mock)
    
    rules = context_mock.user_data["onboarding_rules"]
    assert len(rules) == 2
    assert any(r["type"] == "price_min" and r["value"] == 3000 for r in rules)
    assert any(r["type"] == "price_max" and r["value"] == 5000 for r in rules)
    
    # 2. Test Minimum Price Only
    await user_repo.update_onboarding_step(test_user_id, "ask_budget")
    context_mock.user_data = {"onboarding_rules": []}
    budget_message_mock.text = "מינימום 4000 שקל"
    
    await msg_handler.handle_message(update_mock, context_mock)
    
    rules = context_mock.user_data["onboarding_rules"]
    assert len(rules) == 1
    assert rules[0]["type"] == "price_min"
    assert rules[0]["value"] == 4000

    await user_repo.delete_user(test_user_id)


@pytest.mark.asyncio
async def test_multi_rule_onboarding_direct_completion(db, monkeypatch):
    import database.connection
    monkeypatch.setattr(database.connection, "_db_manager", db)
    user_repo = UserRepository(db)
    rule_repo = RuleRepository(db)
    
    test_user_id = 987654321
    if await user_repo.exists(test_user_id):
        await user_repo.delete_user(test_user_id)
        
    await user_repo.get_or_create(telegram_id=test_user_id, chat_id=test_user_id, username="test_onboard_user")
    await user_repo.update_onboarding_step(test_user_id, "ask_location")
    
    # Mock AI Engine to return location and price max (multi-rule)
    mock_ai = AsyncMock()
    mock_ai.parse_user_rules.return_value = (
        [
            {"type": "area", "value": "פלורנטין", "original_text": "פלורנטין"},
            {"type": "price_max", "value": 5000, "original_text": "עד 5000₪"}
        ],
        "תגובה כלשהי"
    )
    mock_ai.get_random_sass.return_value = "יאס מלכה"
    
    msg_handler = MessageHandler(ai_engine=mock_ai)
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": mock_ai, "processing_service": None}
    context_mock.user_data = {"onboarding_rules": []}
    
    message_mock = MagicMock()
    message_mock.text = "רוצה בפלורנטין עד 5000"
    message_mock.reply_text = AsyncMock()
    
    update_mock = MagicMock(spec=Update)
    update_mock.effective_user = MagicMock(id=test_user_id)
    update_mock.effective_chat = MagicMock(id=test_user_id)
    update_mock.message = message_mock
    
    await msg_handler.handle_message(update_mock, context_mock)
    
    # Verify onboarding_step is set to None (completed)
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user.onboarding_step is None
    
    # Verify rules were successfully written to the DB
    saved_rules = await rule_repo.get_user_rules(test_user_id)
    assert len(saved_rules) == 2
    rule_types = [r.rule_type for r in saved_rules]
    assert RuleType.AREA in rule_types
    assert RuleType.PRICE_MAX in rule_types
    
    await user_repo.delete_user(test_user_id)


@pytest.mark.asyncio
async def test_single_rule_bypasses_ai(db, monkeypatch):
    import database.connection
    monkeypatch.setattr(database.connection, "_db_manager", db)
    user_repo = UserRepository(db)
    
    test_user_id = 987654321
    if await user_repo.exists(test_user_id):
        await user_repo.delete_user(test_user_id)
        
    await user_repo.get_or_create(telegram_id=test_user_id, chat_id=test_user_id, username="test_onboard_user")
    await user_repo.update_onboarding_step(test_user_id, "ask_location")
    
    mock_ai = AsyncMock()
    msg_handler = MessageHandler(ai_engine=mock_ai)
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": mock_ai, "processing_service": None}
    context_mock.user_data = {"onboarding_rules": []}
    
    message_mock = MagicMock()
    message_mock.text = "פלורנטין"
    message_mock.reply_text = AsyncMock()
    
    update_mock = MagicMock(spec=Update)
    update_mock.effective_user = MagicMock(id=test_user_id)
    update_mock.effective_chat = MagicMock(id=test_user_id)
    update_mock.message = message_mock
    
    await msg_handler.handle_message(update_mock, context_mock)
    
    # AI engine should NOT be called (bypassed!)
    mock_ai.parse_user_rules.assert_not_called()
    
    # We should have proceeded to ask_budget
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user.onboarding_step == "ask_budget"
    
    await user_repo.delete_user(test_user_id)
