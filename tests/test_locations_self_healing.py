# tests/test_locations_self_healing.py
"""Unit tests for location schema loading and AI self-healing."""

import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from utils.israeli_locations import IsraeliLocationDatabase, Neighborhood


@pytest.fixture
def temp_locations_schema(tmp_path):
    """Create a temporary locations.json file for isolated testing."""
    schema = {
        "cities": {
            "תל אביב": {
                "aliases": ["תל-אביב", "ת\"א"],
                "latitude": 32.0853,
                "longitude": 34.7818
            },
            "ירושלים": {
                "aliases": ["י-ם", "jerusalem"],
                "latitude": 31.7683,
                "longitude": 35.2137
            },
            "חיפה": {
                "aliases": ["haifa"]
            }
        },
        "neighborhoods": [
            {
                "name": "פלורנטין",
                "city": "תל אביב",
                "aliases": ["florentin"],
                "streets": ["העליה"],
                "bordering": ["נווה צדק"],
                "area_type": "south"
            },
            {
                "name": "נווה צדק",
                "city": "תל אביב",
                "aliases": ["neve tzedek"],
                "streets": [],
                "bordering": ["פלורנטין"],
                "area_type": "south"
            }
        ],
        "borders": [
            {
                "name": "איילון",
                "city": "תל אביב",
                "aliases": ["ayalon"],
                "neighborhoods_west": ["פלורנטין"],
                "neighborhoods_east": [],
                "neighborhoods_north": [],
                "neighborhoods_south": [],
                "border_type": "highway"
            }
        ],
        "area_groups": {
            "דרום תל אביב": ["פלורנטין"]
        }
    }
    
    schema_file = tmp_path / "locations.json"
    with open(schema_file, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        
    return str(schema_file)
 
 
def test_schema_loading(temp_locations_schema):
    """Test that the database loads correctly from the JSON schema file."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    assert "תל אביב" in db.city_aliases
    assert "תל-אביב" in db.city_aliases["תל אביב"]
    
    assert "פלורנטין" in db.tel_aviv_neighborhoods
    assert db.tel_aviv_neighborhoods["פלורנטין"].city == "תל אביב"
    assert "florentin" in db.tel_aviv_neighborhoods["פלורנטין"].aliases
    assert "העליה" in db.tel_aviv_neighborhoods["פלורנטין"].streets
    
    assert "איילון" in db.tel_aviv_borders
    assert db.tel_aviv_borders["איילון"].border_type == "highway"
    
    assert "דרום תל אביב" in db.area_groups
    
    # Check Tel Aviv coordinates are loaded, Haifa has none
    assert db.city_coords["תל אביב"] == (32.0853, 34.7818)
    assert "חיפה" not in db.city_coords


def test_street_normalization(temp_locations_schema):
    """Test that street names successfully resolve to their corresponding neighborhood."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    norm = db.normalize_location("העליה 30")
    assert norm["neighborhood"] == "פלורנטין"
    assert norm["city"] == "תל אביב"


@pytest.mark.asyncio
async def test_location_self_healing_street_success(temp_locations_schema):
    """Test successful self-healing of an unknown street name using a mocked AI engine."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    # Verify that "סלמה" is initially unresolved
    norm_before = db.normalize_location("סלמה")
    assert norm_before["neighborhood"] is None
    
    # Mock AI Engine response indicating a street match
    mock_ai = AsyncMock()
    mock_ai.generate_content.return_value = '{"matched_neighborhood": "פלורנטין", "name_to_add": "סלמה", "type": "street"}'
    mock_ai._parse_json_response = lambda text: json.loads(text)
    
    # Call self-healing
    healed_norm = await db.async_resolve_unknown_location(
        raw_location="סלמה",
        listing_details="דירת שותפים מדהימה ברחוב סלמה ליד פלורנטין",
        ai_engine=mock_ai
    )
    
    # Assert self-healing resolved the neighborhood
    assert healed_norm["neighborhood"] == "פלורנטין"
    assert healed_norm["city"] == "תל אביב"
    
    # Verify that "סלמה" is added to the temporary custom JSON file under 'streets'
    with open(db.custom_schema_path, "r", encoding="utf-8") as f:
        schema_data = json.load(f)
        
    flor_nb = next(nb for nb in schema_data["neighborhoods"] if nb["name"] == "פלורנטין")
    assert "סלמה" in flor_nb["streets"]
    assert "סלמה" not in flor_nb["aliases"]
    
    # Verify that a subsequent deterministic normalization resolves "סלמה" directly without AI
    norm_after = db.normalize_location("סלמה")
    assert norm_after["neighborhood"] == "פלורנטין"
    assert norm_after["city"] == "תל אביב"


@pytest.mark.asyncio
async def test_location_self_healing_alias_success(temp_locations_schema):
    """Test successful self-healing of an unknown neighborhood alias."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    # Mock AI Engine response indicating a neighborhood alias match
    mock_ai = AsyncMock()
    mock_ai.generate_content.return_value = '{"matched_neighborhood": "פלורנטין", "name_to_add": "שכונת פלורה", "type": "alias"}'
    mock_ai._parse_json_response = lambda text: json.loads(text)
    
    # Call self-healing
    healed_norm = await db.async_resolve_unknown_location(
        raw_location="שכונת פלורה",
        listing_details="דירה בשכונת פלורה",
        ai_engine=mock_ai
    )
    
    # Assert self-healing resolved the neighborhood
    assert healed_norm["neighborhood"] == "פלורנטין"
    assert healed_norm["city"] == "תל אביב"
    
    # Verify that "שכונת פלורה" is added to the temporary custom JSON file under 'aliases'
    with open(db.custom_schema_path, "r", encoding="utf-8") as f:
        schema_data = json.load(f)
        
    flor_nb = next(nb for nb in schema_data["neighborhoods"] if nb["name"] == "פלורנטין")
    assert "שכונת פלורה" in flor_nb["aliases"]
    assert "שכונת פלורה" not in flor_nb.get("streets", [])


@pytest.mark.asyncio
async def test_location_self_healing_missing_city_coordinates(temp_locations_schema):
    """Test that self-healing raises ValueError when coordinates for the city are missing."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    # Mock AI Engine
    mock_ai = AsyncMock()
    
    # חיפה exists but has no coordinates configured
    with pytest.raises(ValueError) as excinfo:
        await db.async_resolve_unknown_location(
            raw_location="חיפה",
            listing_details="דירה בחיפה",
            ai_engine=mock_ai
        )
    assert "Grounding coordinates for city 'חיפה' not found in locations.json" in str(excinfo.value)


@pytest.mark.asyncio
async def test_location_self_healing_unmatched(temp_locations_schema):
    """Test that self-healing handles when the LLM returns no match gracefully."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    # Mock AI Engine returning null
    mock_ai = AsyncMock()
    mock_ai.generate_content.return_value = '{"matched_neighborhood": null, "name_to_add": null, "type": null}'
    mock_ai._parse_json_response = lambda text: json.loads(text)
    
    # Call self-healing
    healed_norm = await db.async_resolve_unknown_location(
        raw_location="מקום לא מוכר",
        listing_details="דירה במקום כלשהו",
        ai_engine=mock_ai
    )
    
    assert healed_norm["neighborhood"] is None
    
    # Verify custom schema file was NOT updated or created with the change
    if os.path.exists(db.custom_schema_path):
        with open(db.custom_schema_path, "r", encoding="utf-8") as f:
            schema_data = json.load(f)
        flor_nb = next((nb for nb in schema_data.get("neighborhoods", []) if nb["name"] == "פלורנטין"), None)
        if flor_nb:
            assert "סלמה" not in flor_nb.get("streets", [])
            assert "סלמה" not in flor_nb.get("aliases", [])


@pytest.mark.asyncio
async def test_location_self_healing_new_neighborhood_discovered(temp_locations_schema):
    """Test that self-healing dynamically creates a new neighborhood in the schema when discovered."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    # נווה גולן is not in our initial temp schema
    assert "נווה גולן" not in db.tel_aviv_neighborhoods
    
    # Mock AI returning a new neighborhood
    mock_ai = MagicMock()
    # Use AsyncMock for async method generate_content
    mock_ai.generate_content = AsyncMock(return_value='{"matched_neighborhood": "נווה גולן", "name_to_add": "רחוב חדש", "type": "street"}')
    mock_ai._parse_json_response = lambda text: json.loads(text)
    
    healed_norm = await db.async_resolve_unknown_location(
        raw_location="רחוב חדש",
        listing_details="דירה ברחוב חדש בשכונת נווה גולן",
        ai_engine=mock_ai
    )
    
    # The database should be updated and reloaded with the new neighborhood
    assert healed_norm["neighborhood"] == "נווה גולן"
    assert "נווה גולן" in db.tel_aviv_neighborhoods
    assert db.tel_aviv_neighborhoods["נווה גולן"].area_type == "unknown"
    assert "רחוב חדש" in db.tel_aviv_neighborhoods["נווה גולן"].streets
    
    # Verify the custom schema file was actually written with the new neighborhood
    with open(db.custom_schema_path, "r", encoding="utf-8") as f:
        schema_data = json.load(f)
        
    new_entry = next((nb for nb in schema_data["neighborhoods"] if nb["name"] == "נווה גולן"), None)
    assert new_entry is not None
    assert "רחוב חדש" in new_entry["streets"]
    assert new_entry["area_type"] == "unknown"


@pytest.mark.asyncio
async def test_location_self_healing_conflicting_cities(temp_locations_schema):
    """Test that self-healing returns matched neighborhood successfully even if raw_location has conflicting cities (e.g. 'פלורנטין, ירושלים')."""
    db = IsraeliLocationDatabase(schema_path=temp_locations_schema)
    
    mock_ai = AsyncMock()
    mock_ai.generate_content.return_value = '{"matched_neighborhood": "פלורנטין", "name_to_add": "רחוב העליה", "type": "street"}'
    mock_ai._parse_json_response = lambda text: json.loads(text)
    
    healed_norm = await db.async_resolve_unknown_location(
        raw_location="פלורנטין, ירושלים",
        listing_details="דירה ברחוב העליה בירושלים ותל אביב",
        ai_engine=mock_ai
    )
    
    # It should directly return the AI's resolved neighborhood and city
    assert healed_norm["neighborhood"] == "פלורנטין"
    assert healed_norm["city"] == "תל אביב"

