# tests/test_border_rules.py
"""Test border-based geographic search rules."""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.israeli_locations import get_location_db
from bot.handlers.message_handler import MessageHandler


def test_border_parsing():
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
        }
    ]
    
    for test_case in test_cases:
        print(f"Test: {test_case['description']}")
        print(f"Input: {test_case['text']}")
        
        neighborhoods = handler._parse_border_constraints(test_case['text'])
        print(f"Result: {len(neighborhoods)} neighborhoods")
        print(f"Neighborhoods: {', '.join(neighborhoods[:10])}{'...' if len(neighborhoods) > 10 else ''}")
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
        print()


def test_border_lookup():
    """Test border lookup by name and aliases."""
    print("\n=== Testing Border Lookup ===\n")
    
    location_db = get_location_db()
    
    test_borders = [
        "איילון",
        "ayalon",
        "יפו",
        "jaffa",
        "ארלוזורוב",
        "arlozorov",
        "דיזנגוף",
        "dizengoff",
        "ים",
        "sea"
    ]
    
    for border_name in test_borders:
        border = location_db._find_border(border_name)
        if border:
            print(f"✓ Found border '{border_name}' → {border.name} ({border.border_type})")
        else:
            print(f"✗ Border '{border_name}' not found")
    print()


def main():
    """Run all tests."""
    print("="*60)
    print("Border-Based Geographic Search Rules - Test Suite")
    print("="*60)
    
    try:
        test_border_lookup()
        test_neighborhood_filtering()
        test_border_parsing()
        
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
