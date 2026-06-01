# tests/test_hebrew_rules_llm.py
"""Integration tests for parsing Hebrew search rules using real LLM calls."""

import sys
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from config import settings, AIProvider
from core.ai_engine import create_ai_engine, GeminiAIEngine
from bot.handlers.message_handler import MessageHandler
from database.connection import DatabaseManager
from database.repositories.user_repository import UserRepository
from models.user import User
from models.search_rule import SearchRule, RuleType


def safe_print(msg: str):
    """Safely print a string to stdout, handling terminal encoding limitations on Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback to UTF-8 encoded bytes decoded to ASCII (with replacements) or escaped string representation
        try:
            print(msg.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
        except Exception:
            print(repr(msg))


@pytest.fixture(scope="module")
def ai_engine():
    """Constructs a real AI engine for testing using the configured Gemini key."""
    # Ensure a Gemini key is configured
    if not settings.GEMINI_API_KEY:
        pytest.skip("GEMINI_API_KEY is not set in environment or .env file.")
    
    # We use a reliable, fast model explicitly to ensure success and speed up tests
    engine = create_ai_engine(
        provider=AIProvider.GEMINI,
        api_key=settings.GEMINI_API_KEY,
        model_name="gemini-2.5-flash"
    )
    return engine


@pytest.mark.asyncio
async def test_real_llm_parsing_barakush(ai_engine):
    """Test parsing simple Hebrew rules using the Barakush (sassy) persona."""
    hebrew_text = "מחפש דירה בתל אביב עד 6500 שקל לפחות 3 חדרים"
    
    safe_print(f"\n--- Testing Barakush with input: '{hebrew_text}' ---")
    rules, sass = await ai_engine.parse_user_rules(hebrew_text, persona="barakush")
    
    safe_print(f"Parsed Rules: {rules}")
    safe_print(f"Sass Response: {sass}")
    
    # Assert structural properties
    assert isinstance(rules, list), "Parsed rules should be a list"
    assert len(rules) >= 2, "Should parse at least two rules (price and rooms/area)"
    assert isinstance(sass, str) and sass.strip(), "Sass response should be a non-empty string"
    
    # Verify rules are mapped correctly
    rule_types = [r["type"] for r in rules]
    assert "price_max" in rule_types, "Should extract a price_max rule"
    assert "bedrooms_min" in rule_types or "bedrooms_max" in rule_types, "Should extract a bedrooms rule"
    
    # Verify values
    for rule in rules:
        if rule["type"] == "price_max":
            assert float(rule["value"]) == 6500, "Price max should be 6500"
        elif rule["type"] == "bedrooms_min":
            assert float(rule["value"]) >= 3, "Bedrooms min should be at least 3"


@pytest.mark.asyncio
async def test_real_llm_parsing_yekke(ai_engine):
    """Test parsing complex Hebrew rules with ranges using the Yekke (professional) persona."""
    hebrew_text = "אני רוצה 2-3 חדרים בלב תל אביב או כרם התימנים בין 5000 ל-7000 שקל עם מרפסת וחניה"
    
    safe_print(f"\n--- Testing Yekke with input: '{hebrew_text}' ---")
    rules, sass = await ai_engine.parse_user_rules(hebrew_text, persona="yekke")
    
    safe_print(f"Parsed Rules: {rules}")
    safe_print(f"Sass Response: {sass}")
    
    # Assert structural properties
    assert isinstance(rules, list), "Parsed rules should be a list"
    assert len(rules) >= 3, "Should parse multiple rules (price max/min, bedrooms, areas, custom)"
    assert isinstance(sass, str) and sass.strip(), "Sass response should be a non-empty string"
    
    # Verify rule types
    rule_types = [r["type"] for r in rules]
    
    # Ranges must be split into min/max rules per instructions in parse_rules_prompt!
    assert "price_max" in rule_types or "price_min" in rule_types, "Should extract price rules"
    assert "bedrooms_min" in rule_types or "bedrooms_max" in rule_types, "Should extract bedroom rules"
    assert "area" in rule_types or "border_area" in rule_types, "Should extract area or border_area rule"
    assert "custom" in rule_types or any(r["type"] not in ["price_max", "price_min", "bedrooms_min", "bedrooms_max", "area", "border_area"] for r in rules), "Should extract custom rules for amenities"
    
    # Verify values
    for r in rules:
        if r["type"] == "price_max":
            assert float(r["value"]) == 7000, "Price max should be 7000"
        elif r["type"] == "price_min":
            assert float(r["value"]) == 5000, "Price min should be 5000"
        elif r["type"] == "bedrooms_max":
            assert float(r["value"]) == 3, "Bedrooms max should be 3"
        elif r["type"] == "bedrooms_min":
            assert float(r["value"]) == 2, "Bedrooms min should be 2"


@pytest.mark.asyncio
async def test_real_llm_parsing_stoner(ai_engine):
    """Test parsing geographic border constraints using the Stoner (chill) persona."""
    hebrew_text = "משהו מערבית לאיילון וצפונית ליפו ודרומית לארלוזורוב"
    
    safe_print(f"\n--- Testing Stoner with input: '{hebrew_text}' ---")
    rules, sass = await ai_engine.parse_user_rules(hebrew_text, persona="stoner")
    
    safe_print(f"Parsed Rules: {rules}")
    safe_print(f"Sass Response: {sass}")
    
    assert isinstance(rules, list), "Parsed rules should be a list"
    assert len(rules) >= 1, "Should parse at least one rule"
    assert isinstance(sass, str) and sass.strip(), "Sass response should be a non-empty string"
    
    # Verify border area rule exists
    rule_types = [r["type"] for r in rules]
    assert "border_area" in rule_types, "Geographic border constraints should map to border_area"


@pytest.mark.asyncio
async def test_exact_neighborhoods_are_parsed_as_area(ai_engine):
    """Test that exact neighborhood names are parsed as 'area' rules, NOT 'border_area' rules."""
    hebrew_text = "אני רוצה רק פלורנטין או כרם התימנים"
    
    safe_print(f"\n--- Testing Exact Neighborhoods with input: '{hebrew_text}' ---")
    rules, sass = await ai_engine.parse_user_rules(hebrew_text, persona="barakush")
    
    safe_print(f"Parsed Rules: {rules}")
    
    assert isinstance(rules, list), "Parsed rules should be a list"
    assert len(rules) >= 1, "Should parse at least one rule"
    
    rule_types = [r["type"] for r in rules]
    
    # EXACT neighborhood names MUST be mapped to 'area' rule type, NOT 'border_area'!
    # Because 'border_area' triggers coordinate range calculations, whereas exact neighborhoods are string matched against listings.
    for rule in rules:
        if any(nb in rule["original_text"] for nb in ["פלורנטין", "כרם"]):
            assert rule["type"] == "area", f"Exact neighborhood '{rule['original_text']}' was incorrectly parsed as '{rule['type']}' instead of 'area'!"


@pytest.mark.asyncio
async def test_message_handler_real_llm_flow(ai_engine):
    """Tests the full Telegram MessageHandler flow with a real LLM call against an in-memory database."""
    # 1. Setup in-memory database
    db_manager = DatabaseManager(db_url="sqlite:///:memory:")
    await db_manager.initialize()
    
    try:
        user_repo = UserRepository(db_manager)
        
        # Create a test user in DB
        telegram_id = 987654321
        user_obj = User(
            telegram_id=telegram_id,
            chat_id=telegram_id,
            username="real_llm_tester",
            created_at=datetime.now(),
            is_active=True,
            persona="barakush"  # Sassy persona for the message handler
        )
        await user_repo.create(user_obj)
        
        # 2. Instantiate message handler with the real AI engine
        handler = MessageHandler(ai_engine=ai_engine)
        
        # 3. Mock Telegram Update and Context
        update = MagicMock()
        update.effective_user.id = telegram_id
        update.effective_user.username = "real_llm_tester"
        update.effective_chat.id = telegram_id
        update.message.text = "דירה בתל אביב עד 5000 שח"
        
        # We will capture the message sent by _safe_reply_text
        sent_messages = []
        async def mock_reply_text(text, parse_mode=None, reply_markup=None, **kwargs):
            sent_messages.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup
            })
            return MagicMock()
            
        update.message.reply_text = AsyncMock(side_effect=mock_reply_text)
        
        context = MagicMock()
        context.user_data = {}
        context.bot_data = {}
        
        # 4. Patch database lookup within MessageHandler to use our in-memory test database
        with patch("bot.handlers.message_handler.get_db", return_value=db_manager):
            safe_print(f"\n--- Testing MessageHandler full flow with real LLM ---")
            await handler.handle_message(update, context)
            
        # 5. Assertions on the outcome of the message handler
        # A confirmation message should have been sent
        assert len(sent_messages) == 1, "Should send exactly one confirmation message"
        conf_msg = sent_messages[0]
        
        safe_print(f"MessageHandler Confirmation Message Sent:\n{conf_msg['text']}")
        
        assert "רגע, בוא נוודא שהבנתי נכון" in conf_msg["text"], "Should ask user to confirm rules"
        assert "מחיר מקסימלי" in conf_msg["text"], "Should mention price max rule"
        assert "5\\,000" in conf_msg["text"] or "5000" in conf_msg["text"], "Should display the price limit"
        assert conf_msg["reply_markup"] is not None, "Should attach inline keyboard for confirmation"
        
        # Ensure pending rules are saved in context
        assert "pending_rule_confirmation" in context.user_data, "Should store pending rules in context"
        pending = context.user_data["pending_rule_confirmation"]
        
        assert pending["user_id"] == telegram_id, "Should store the correct user ID"
        assert len(pending["all_pending_rules"]) >= 1, "Should have pending rules saved"
        
        # Check rule details
        price_rule = None
        for r in pending["all_pending_rules"]:
            if r.rule_type == RuleType.PRICE_MAX:
                price_rule = r
                
        assert price_rule is not None, "Should have a PRICE_MAX rule"
        assert price_rule.value == "5000", "Price max value should be '5000'"
        assert price_rule.original_text == "מחיר מקסימלי 5000₪" or "עד 5000 שח" in price_rule.original_text, "Original text should be set"
        
        safe_print("✅ MessageHandler full flow test passed successfully!")
        
    finally:
        # Clean up database connection
        await db_manager.close()


@pytest.mark.asyncio
async def test_message_handler_fallback_flow(ai_engine):
    """Tests that compound/ambiguous exact neighborhood definitions that the LLM misclassifies 
    as border_area correctly fall back to standard AREA rules and are not discarded.
    """
    # 1. Setup in-memory database
    db_manager = DatabaseManager(db_url="sqlite:///:memory:")
    await db_manager.initialize()
    
    try:
        user_repo = UserRepository(db_manager)
        
        # Create a test user in DB
        telegram_id = 987654321
        user_obj = User(
            telegram_id=telegram_id,
            chat_id=telegram_id,
            username="real_llm_tester",
            created_at=datetime.now(),
            is_active=True,
            persona="yekke"  # Yekke persona
        )
        await user_repo.create(user_obj)
        
        # 2. Instantiate message handler with the real AI engine
        handler = MessageHandler(ai_engine=ai_engine)
        
        # 3. Mock Telegram Update and Context
        update = MagicMock()
        update.effective_user.id = telegram_id
        update.effective_user.username = "real_llm_tester"
        update.effective_chat.id = telegram_id
        # Input has compound neighborhood name "לב תל אביב או כרם התימנים" which gets misclassified as border_area by LLM
        update.message.text = "אני רוצה בלב תל אביב או כרם התימנים"
        
        sent_messages = []
        async def mock_reply_text(text, parse_mode=None, reply_markup=None, **kwargs):
            sent_messages.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup
            })
            return MagicMock()
            
        update.message.reply_text = AsyncMock(side_effect=mock_reply_text)
        
        context = MagicMock()
        context.user_data = {}
        context.bot_data = {}
        
        # 4. Patch database lookup within MessageHandler to use our in-memory test database
        with patch("bot.handlers.message_handler.get_db", return_value=db_manager):
            safe_print(f"\n--- Testing MessageHandler Fallback flow with real LLM ---")
            await handler.handle_message(update, context)
            
        # 5. Assertions
        assert len(sent_messages) == 1, "Should send exactly one confirmation message"
        conf_msg = sent_messages[0]
        
        safe_print(f"MessageHandler Confirmation Message Sent:\n{conf_msg['text']}")
        
        # The confirmation message must contain the parsed neighborhood!
        assert "מיקום" in conf_msg["text"] or "אזור" in conf_msg["text"], "Confirmation should mention the location"
        assert "לב תל אביב" in conf_msg["text"] or "כרם" in conf_msg["text"], "Confirmation should display the matched location"
        
        # Ensure pending rules are saved in context
        assert "pending_rule_confirmation" in context.user_data, "Should store pending rules in context"
        pending = context.user_data["pending_rule_confirmation"]
        
        assert len(pending["all_pending_rules"]) >= 1, "Should have pending rules saved"
        
        # Verify the border_area rule fell back to RuleType.AREA
        area_rule = None
        for r in pending["all_pending_rules"]:
            if r.rule_type == RuleType.AREA:
                area_rule = r
                
        assert area_rule is not None, "The BORDER_AREA rule should have fallen back to an AREA rule!"
        assert "לב תל אביב" in area_rule.value or "כרם" in area_rule.value, "The fallback AREA rule should preserve the neighborhood names"
        
        safe_print("✅ MessageHandler fallback flow test passed successfully!")
        
    finally:
        await db_manager.close()
