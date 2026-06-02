# tests/test_border_rules.py
"""Test border-based geographic search rules."""

import sys
import os
import pytest
import asyncio
from unittest.mock import AsyncMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.israeli_locations import get_location_db
from bot.handlers.message_handler import MessageHandler


@pytest.mark.asyncio
async def test_border_parsing():
    """Test parsing of border constraints."""
    print("\n=== Testing Border Constraint Parsing ===\n")
    
    handler = MessageHandler()
    
    test_cases = [
        {
            "text": "מערב לאיילון צפונית ליפו ודרומית לארלוזורוב",
            "description": "West of Ayalon, north of Jaffa, south of Arlosoroff"
        },
        {
            "text": "מערב לאיילון וצפונית ליפו",
            "description": "West of Ayalon and north of Jaffa"
        },
        {
            "text": "דרומית לארלוזורוב מערבית לאיילון",
            "description": "South of Arlosoroff, west of Ayalon"
        },
        {
            "text": "מזרחית לים צפונה מיפו",
            "description": "East of sea, north of Jaffa"
        },
        {
            "text": "מערבית לאיילון, דרומית לארלוזרוב, צפונית לפלורנטין",
            "description": "User target query: West of Ayalon, south of Arlozrov (misspelled), north of Florentin (neighborhood)"
        }
    ]
    
    for test_case in test_cases:
        print(f"Test: {test_case['description']}")
        print(f"Input: {test_case['text']}")
        
        neighborhoods = await handler._parse_border_constraints(test_case['text'])
        print(f"Result: {len(neighborhoods)} neighborhoods")
        print(f"Neighborhoods: {', '.join(neighborhoods[:10])}{'...' if len(neighborhoods) > 10 else ''}")
        
        # Specific assertion for the user target query
        if "פלורנטין" in test_case['text']:
            assert len(neighborhoods) > 0, "Target query should resolve to central Tel Aviv neighborhoods"
            assert "אפקה" not in neighborhoods, "Afeka (אפקה) should be strictly excluded from central/south TLV"
            assert "לב העיר" in neighborhoods, "Lev HaIr should be included"
            
        print()


@pytest.mark.asyncio
async def test_llm_fallback():
    """Test the LLM fallback path when deterministic resolution yields no neighborhoods."""
    print("\n=== Testing LLM Fallback ===\n")
    
    # 1. Setup handler with mock AI engine
    mock_ai = AsyncMock()
    # Mocking resolve_neighborhoods_via_llm to return specific neighborhoods
    mock_ai.resolve_neighborhoods_via_llm.return_value = ["לב העיר", "רוטשילד", "חולון"] # חולון is not in TLV list, should be filtered out
    
    handler = MessageHandler(ai_engine=mock_ai)
    
    # Use a custom border text that won't match any deterministic predefined border
    custom_text = "צפונית לכיכר רבין"
    
    neighborhoods = await handler._parse_border_constraints(custom_text)
    
    print(f"Input: {custom_text}")
    print(f"Resolved via Mock LLM Fallback: {neighborhoods}")
    
    # Check that resolve_neighborhoods_via_llm was indeed called
    mock_ai.resolve_neighborhoods_via_llm.assert_called_once()
    
    # Check that returned neighborhoods were filtered to only supported ones ("חולון" removed)
    assert "לב העיר" in neighborhoods
    assert "רוטשילד" in neighborhoods
    assert "חולון" not in neighborhoods, "Unsupported neighborhoods returned by LLM should be filtered out"
    print("✓ LLM Fallback successfully called and filtered!")
    print()


def test_neighborhood_filtering():
    """Test location database border filtering."""
    print("\n=== Testing Neighborhood Filtering ===\n")
    
    location_db = get_location_db()
    
    test_cases = [
        {
            "constraints": {"west_of": "איילון", "north_of": "יפו", "south_of": "ארלוזורוב"},
            "description": "West of Ayalon, north of Jaffa, south of Arlosoroff"
        },
        {
            "constraints": {"west_of": "איילון"},
            "description": "West of Ayalon only"
        },
        {
            "constraints": {"north_of": "יפו"},
            "description": "North of Jaffa only"
        },
        {
            "constraints": {"east_of": "ים"},
            "description": "East of sea (everything in TLV)"
        },
        {
            "constraints": {"west_of": "איילון", "north_of": "פלורנטין", "south_of": "ארלוזרוב"},
            "description": "Target query: West of Ayalon, north of Florentin, south of Arlozrov (misspelled)"
        }
    ]
    
    for test_case in test_cases:
        print(f"Test: {test_case['description']}")
        print(f"Constraints: {test_case['constraints']}")
        
        neighborhoods = location_db.get_neighborhoods_within_borders(test_case['constraints'])
        print(f"Result: {len(neighborhoods)} neighborhoods")
        print(f"Neighborhoods: {', '.join(neighborhoods[:15])}")
        if len(neighborhoods) > 15:
            print(f"... and {len(neighborhoods) - 15} more")
            
        if "פלורנטין" in str(test_case['constraints']):
            assert "אפקה" not in neighborhoods, "Afeka (אפקה) should not be in the central/south TLV intersection"
            
        print()


def test_border_lookup():
    """Test border lookup by name and aliases."""
    print("\n=== Testing Border Lookup ===\n")
    
    location_db = get_location_db()
    
    test_borders = [
        "איילון",
        "ayalon",
        "אילון", # new alias
        "יפו",
        "jaffa",
        "ארלוזורוב",
        "arlozorov",
        "ארלוזרוב", # misspelled
        "ארלוזורוף", # misspelled
        "דיזנגוף",
        "dizengoff",
        "דיזנגופ", # misspelled
        "ים",
        "sea",
        "ירקון", # new border
        "פלורנטין", # new border
        "רוטשילד" # new border
    ]
    
    for border_name in test_borders:
        border = location_db._find_border(border_name)
        if border:
            print(f"✓ Found border '{border_name}' → {border.name} ({border.border_type})")
            assert border.name in ["איילון", "יפו", "ארלוזורוב", "דיזנגוף", "ים", "ירקון", "פלורנטין", "אלנבי", "רוטשילד"]
        else:
            print(f"✗ Border '{border_name}' not found")
            raise AssertionError(f"Border '{border_name}' should have been resolved!")
    print()


@pytest.mark.asyncio
async def test_conversational_rule_modification():
    """Test that users can reply to modify the pending rules by adding/removing neighborhoods."""
    print("\n=== Testing Conversational Rule Modification ===\n")
    
    # 1. Setup a pending rules state in a mock context
    from models.search_rule import SearchRule, RuleType
    
    pending_rule = SearchRule(
        user_id=123,
        rule_type=RuleType.BORDER_AREA,
        value="בבלי,הצפון הישן,לב העיר",
        original_text="מערבית לאיילון"
    )
    
    mock_context = AsyncMock()
    mock_context.bot_data = {}
    mock_context.user_data = {
        'pending_rule_confirmation': {
            'user_id': 123,
            'all_pending_rules': [pending_rule],
            'border_rules_data': []
        }
    }
    
    # 2. Setup a mock update for the message text "בלי בבלי ותוסיף את פלורנטין"
    mock_update = AsyncMock()
    mock_update.effective_user.id = 123
    mock_update.effective_user.username = "testuser"
    mock_update.effective_chat.id = 123
    mock_update.message.text = "בלי בבלי ותוסיף את פלורנטין"
    
    # Pre-register user in DB without onboarding_step
    from database import get_db
    from database.repositories import UserRepository
    from models.user import User
    db = await get_db()
    user_repo = UserRepository(db)
    await user_repo.create(User(telegram_id=123, chat_id=123, username="testuser", onboarding_step=None))
    
    # Mock safe_reply_text
    handler = MessageHandler()
    handler._safe_reply_text = AsyncMock()
    
    # 3. Call handle_message
    await handler.handle_message(mock_update, mock_context)
    
    # 4. Assertions
    # Verify the pending rule in context was modified:
    # "בבלי" should be removed, "פלורנטין" should be added.
    updated_rules = mock_context.user_data['pending_rule_confirmation']['all_pending_rules']
    assert len(updated_rules) == 1
    updated_rule = updated_rules[0]
    
    current_neighborhoods = updated_rule.value.split(",")
    assert "בבלי" not in current_neighborhoods, "Bavli should have been removed"
    assert "פלורנטין" in current_neighborhoods, "Florentin should have been added"
    assert "לב העיר" in current_neighborhoods, "Lev HaIr should have been kept"
    
    # Check that safe_reply_text was called with the modified confirmation
    handler._safe_reply_text.assert_called_once()
    call_args = handler._safe_reply_text.call_args[0]
    reply_text = call_args[1]
    
    assert "עדכנתי את האזור לבקשתך" in reply_text
    assert "הסרתי את: בבלי" in reply_text
    assert "הוספתי את: פלורנטין" in reply_text
    
    print("✓ Conversational rule modification test passed successfully!")
    print()


@pytest.mark.asyncio
async def test_area_rule_modification_and_cleaning():
    """Test that standard AREA rules can be modified and original text is cleaned."""
    print("\n=== Testing Standard AREA Rule Modification and Text Cleaning ===\n")
    
    from bot.handlers.message_handler import clean_hebrew_location_text
    
    # 1. Test the clean function directly
    assert clean_hebrew_location_text("תוסיף את הצפון הישן") == "הצפון הישן"
    assert clean_hebrew_location_text("תוסיפי את פלורנטין") == "פלורנטין"
    assert clean_hebrew_location_text("בלי בבלי") == "בבלי"
    assert clean_hebrew_location_text("להסיר את כרם התימנים") == "כרם התימנים"
    print("✓ Location text cleaning logic verified!")
    
    # 2. Test modifying standard AREA rules conversational flow
    from models.search_rule import SearchRule, RuleType
    
    pending_rule = SearchRule(
        user_id=123,
        rule_type=RuleType.AREA,
        value="בבלי",
        original_text="בבלי"
    )
    
    mock_context = AsyncMock()
    mock_context.bot_data = {}
    mock_context.user_data = {
        'pending_rule_confirmation': {
            'user_id': 123,
            'all_pending_rules': [pending_rule],
            'border_rules_data': []
        }
    }
    
    mock_update = AsyncMock()
    mock_update.effective_user.id = 123
    mock_update.effective_user.username = "testuser"
    mock_update.effective_chat.id = 123
    mock_update.message.text = "בלי בבלי ותוסיף את הצפון הישן"
    
    handler = MessageHandler()
    handler._safe_reply_text = AsyncMock()
    
    # Call handle_message
    await handler.handle_message(mock_update, mock_context)
    
    # Assertions
    updated_rules = mock_context.user_data['pending_rule_confirmation']['all_pending_rules']
    
    # "בבלי" AREA rule should be removed, "הצפון הישן" AREA rule should be added
    rule_types = [r.rule_type for r in updated_rules]
    rule_values = [r.value for r in updated_rules]
    rule_texts = [r.original_text for r in updated_rules]
    
    assert RuleType.AREA in rule_types
    assert "בבלי" not in rule_values
    assert "הצפון הישן" in rule_values
    assert "הצפון הישן" in rule_texts  # Check that original text was cleaned!
    
    print("✓ Standard AREA rule modification and cleaning verified successfully!")
    print()


@pytest.mark.asyncio
async def test_custom_location_merging():
    """Test that custom locations are saved in locations_custom.json and merged on reload."""
    print("\n=== Testing Custom Location Merging and Decoupling ===\n")
    import tempfile
    import json
    
    # 1. Create a temporary schema locations.json
    with tempfile.TemporaryDirectory() as tmpdir:
        schema_path = os.path.join(tmpdir, "locations.json")
        custom_schema_path = os.path.join(tmpdir, "locations_custom.json")
        
        base_data = {
            "cities": {
                "תל אביב": {
                    "aliases": ["tel aviv"],
                    "latitude": 32.0853,
                    "longitude": 34.7818
                }
            },
            "neighborhoods": [
                {
                    "name": "לב העיר",
                    "city": "תל אביב",
                    "aliases": ["מרכז"],
                    "bordering": [],
                    "area_type": "central",
                    "streets": ["בוגרשוב"]
                }
            ]
        }
        
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(base_data, f, ensure_ascii=False, indent=2)
            
        # 2. Instantiate IsraeliLocationDatabase with this custom schema_path
        from utils.israeli_locations import IsraeliLocationDatabase
        db = IsraeliLocationDatabase(schema_path=schema_path)
        
        # Override custom_schema_path dynamically for the test instance
        db.custom_schema_path = custom_schema_path
        
        # 3. Simulate resolving a location with a new street
        mock_ai = AsyncMock()
        mock_ai.generate_content.return_value = '{"matched_neighborhood": "לב העיר", "name_to_add": "מלצ\'ט", "type": "street"}'
        
        # Mock _parse_json_response (since it's implemented on base AI engine)
        mock_ai._parse_json_response.return_value = {
            "matched_neighborhood": "לב העיר", 
            "name_to_add": "מלצ'ט", 
            "type": "street"
        }
        
        # Call resolution
        result = await db.async_resolve_unknown_location(
            raw_location="מלצ'ט",
            listing_details="מלצ'ט 5 לב העיר",
            ai_engine=mock_ai
        )
        
        # Assertions
        assert result["neighborhood"] == "לב העיר"
        
        # Verify custom file was created and contains the street
        assert os.path.exists(custom_schema_path)
        with open(custom_schema_path, "r", encoding="utf-8") as f:
            custom_data = json.load(f)
            
        custom_nb = next((n for n in custom_data["neighborhoods"] if n["name"] == "לב העיר"), None)
        assert custom_nb is not None
        assert "מלצ'ט" in custom_nb["streets"]
        
        # Verify that reload successfully merged it
        assert "מלצ'ט".lower() in db.neighborhood_lookup
        
        print("✓ Custom locations decoupled storage and loading verified successfully!")
        print()


def main():
    """Run all tests."""
    print("="*60)
    print("Border-Based Geographic Search Rules - Test Suite")
    print("="*60)
    
    try:
        test_border_lookup()
        test_neighborhood_filtering()
        
        # Run async tests
        asyncio.run(test_border_parsing())
        asyncio.run(test_llm_fallback())
        asyncio.run(test_conversational_rule_modification())
        asyncio.run(test_area_rule_modification_and_cleaning())
        asyncio.run(test_custom_location_merging())
        
        print("\n" + "="*60)
        print("All tests completed successfully!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
