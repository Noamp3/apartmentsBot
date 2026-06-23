# tests/test_location_priority.py
"""Unit tests to verify that location resolution prioritizes street names/junctions over neighborhood names."""

import json
import pytest
from utils.israeli_locations import IsraeliLocationDatabase


@pytest.fixture
def custom_locations_schema(tmp_path):
    """Create a temporary locations.json file where street and neighborhood belong to different neighborhoods."""
    schema = {
        "cities": {
            "תל אביב": {
                "aliases": ["תל-אביב", "ת\"א"],
                "latitude": 32.0853,
                "longitude": 34.7818
            }
        },
        "neighborhoods": [
            {
                "name": "פלורנטין",
                "city": "תל אביב",
                "aliases": [],
                "streets": ["העליה"],
                "bordering": [],
                "area_type": "south"
            },
            {
                "name": "נווה צדק",
                "city": "תל אביב",
                "aliases": [],
                "streets": ["שלוש"],
                "bordering": [],
                "area_type": "south"
            }
        ],
        "borders": [],
        "area_groups": {}
    }
    
    schema_file = tmp_path / "locations.json"
    with open(schema_file, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        
    return str(schema_file)


def test_street_prioritization_over_neighborhood(custom_locations_schema):
    """Verify that when both street and neighborhood are extracted, street has higher priority."""
    db = IsraeliLocationDatabase(schema_path=custom_locations_schema)
    
    # Street is "העליה" (belongs to "פלורנטין"), but neighborhood is "נווה צדק" (different neighborhood)
    extracted_street = "העליה"
    extracted_neighborhood = "נווה צדק"
    
    # Mimic the prioritization block from main.py
    norm = None
    
    # 1. Try to normalize explicitly extracted street directly first
    if extracted_street:
        norm_st = db.normalize_location(extracted_street)
        if norm_st["neighborhood"]:
            norm = norm_st
            
    # 2. Try to normalize explicitly extracted neighborhood directly next
    if not norm and extracted_neighborhood:
        norm_nb = db.normalize_location(extracted_neighborhood)
        if norm_nb["neighborhood"]:
            norm = norm_nb
            
    assert norm is not None
    # Must prioritize street's neighborhood ("פלורנטין") over neighborhood ("נווה צדק")
    assert norm["neighborhood"] == "פלורנטין"
    assert norm["city"] == "תל אביב"


def test_fallback_neighborhood_when_street_unmapped(custom_locations_schema):
    """Verify that if the street doesn't map to a neighborhood, we fallback to the neighborhood name."""
    db = IsraeliLocationDatabase(schema_path=custom_locations_schema)
    
    # Street is "רחוב כלשהו" (not mapped), but neighborhood is "נווה צדק"
    extracted_street = "רחוב כלשהו"
    extracted_neighborhood = "נווה צדק"
    
    norm = None
    
    # 1. Try to normalize explicitly extracted street directly first
    if extracted_street:
        norm_st = db.normalize_location(extracted_street)
        if norm_st["neighborhood"]:
            norm = norm_st
            
    # 2. Try to normalize explicitly extracted neighborhood directly next
    if not norm and extracted_neighborhood:
        norm_nb = db.normalize_location(extracted_neighborhood)
        if norm_nb["neighborhood"]:
            norm = norm_nb
            
    assert norm is not None
    # Must fallback to the neighborhood ("נווה צדק") since street is unmapped
    assert norm["neighborhood"] == "נווה צדק"
