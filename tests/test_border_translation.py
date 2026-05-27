# tests/test_border_translation.py
"""Test that border rules are translated to neighborhoods."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.handlers.message_handler import MessageHandler


def test_border_translation():
    """Test border constraint parsing and neighborhood translation."""
    handler = MessageHandler()
    
    # Test case: "west of Ayalon, north of Jaffa, south of Arlosoroff"
    border_text = "מערב לאיילון צפונית ליפו ודרומית לארלוזורוב"
    
    print(f"Input: {border_text}\n")
    
    neighborhoods = handler._parse_border_constraints(border_text)
    
    print(f"Translated to {len(neighborhoods)} neighborhoods:")
    for i, n in enumerate(neighborhoods, 1):
        print(f"  {i}. {n}")
    
    # Verify neighborhoods were found
    assert len(neighborhoods) > 0, "No neighborhoods found!"
    
    assert "לב העיר" in neighborhoods, "לב העיר should be included"
    assert "רוטשילד" in neighborhoods, "רוטשילד should be included"
    
    # Should NOT include northern neighborhoods
    assert "רמת אביב" not in neighborhoods, "רמת אביב is north of Arlosoroff and should be excluded"
    
    print(f"\n✅ Test passed! Border text correctly translated to {len(neighborhoods)} neighborhoods")
    

if __name__ == "__main__":
    test_border_translation()
