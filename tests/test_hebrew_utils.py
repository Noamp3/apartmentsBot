# tests/test_hebrew_utils.py
"""Tests for Hebrew text utilities."""

import pytest
from utils.hebrew_utils import (
    extract_price,
    extract_bedrooms,
    extract_floor,
    has_broker_fee,
    is_direct_from_owner,
    is_looking_for_roomie,
    parse_relative_date,
    extract_yad2_posted_date
)


class TestPriceExtraction:
    """Test price extraction from Hebrew text."""
    
    def test_shekel_sign(self):
        assert extract_price("5000 ש\"ח") == 5000
    
    def test_shekel_word(self):
        assert extract_price("5000 שקל") == 5000
    
    def test_shekel_symbol(self):
        assert extract_price("₪5000") == 5000
    
    def test_thousands_word(self):
        assert extract_price("5 אלף") == 5000
    
    def test_with_commas(self):
        assert extract_price("5,000 ש\"ח") == 5000
    
    def test_k_suffix(self):
        assert extract_price("5k") == 5000
    
    def test_no_price(self):
        assert extract_price("דירה יפה") is None
    
    def test_phone_not_price(self):
        """Phone numbers should NOT be extracted as prices."""
        assert extract_price("התקשרו 0522505694") is None
        assert extract_price("טלפון 03-1234567") is None
        assert extract_price("call 0501234567 now") is None


class TestBedroomsExtraction:
    """Test bedroom extraction from Hebrew text."""
    
    def test_numeric_rooms(self):
        assert extract_bedrooms("3 חדרים") == 3
    
    def test_half_rooms(self):
        assert extract_bedrooms("3.5 חדרים") == 3
    
    def test_hebrew_word_number(self):
        assert extract_bedrooms("שלושה חדרים") == 3
    
    def test_dirat_format(self):
        assert extract_bedrooms("דירת 4") == 4


class TestFloorExtraction:
    """Test floor extraction from Hebrew text."""
    
    def test_floor_number(self):
        assert extract_floor("קומה 5") == 5
    
    def test_ground_floor(self):
        assert extract_floor("קומת קרקע") == 0


class TestBrokerFee:
    """Test broker fee detection."""
    
    def test_with_broker(self):
        assert has_broker_fee("דירה להשכרה, תיווך")
    
    def test_without_broker(self):
        assert not has_broker_fee("דירה להשכרה")
    
    def test_direct_from_owner(self):
        assert is_direct_from_owner("ללא תיווך, ישירות מהבעלים")
        assert is_direct_from_owner("דירה מהממת לא מתיווך")
        assert is_direct_from_owner("ללא מתווכים בבקשה")
        assert is_direct_from_owner("פרסום פרטי ללא מתווך")
        assert is_direct_from_owner("בלי מתווכים")
        assert is_direct_from_owner("ללא עמלת תיווך")
        assert is_direct_from_owner("בלי דמי תיווך")
        assert is_direct_from_owner("ללא מתווכת")
        assert is_direct_from_owner("ללא מתווכות")
        assert not has_broker_fee("דירה ללא עמלת תיווך")
        assert not has_broker_fee("דירה ללא תיווך")
        assert not has_broker_fee("דירה בלי מתווכים")
    
    def test_not_direct(self):
        assert not is_direct_from_owner("דירה להשכרה")
        assert not is_direct_from_owner("דירה מתיווך")


class TestRoomiesExtraction:
    """Test roomies/flatmate detection from Hebrew text."""
    
    def test_looking_for_roomie_male(self):
        assert is_looking_for_roomie("מחפש שותף לדירה מהממת בפלורנטין")
        
    def test_looking_for_roomie_female(self):
        assert is_looking_for_roomie("מחפשת שותפה לדירה")
        
    def test_looking_for_roomies_plural(self):
        assert is_looking_for_roomie("מחפשים שותפים לדירה")
        
    def test_roomie_needed(self):
        assert is_looking_for_roomie("דרושה שותפה לחדר")
        assert is_looking_for_roomie("דרוש שותף")
        
    def test_room_for_rent(self):
        assert is_looking_for_roomie("להשכרה חדר בדירת שותפים")
        assert is_looking_for_roomie("להשכרה חדר בדירה, שותף אחד בן 28")
        
    def test_suitable_for_roommates_only(self):
        """'Suitable for roommates' should NOT be detected as looking for roomies."""
        assert not is_looking_for_roomie("דירת 3 חדרים מהממת מתאימה לשותפים")
        assert not is_looking_for_roomie("דירה מעולה לשותפים, 3 חדרים גדולים")
        
    def test_mixed_suitability_and_search(self):
        """Should be True if looking for roomie, even if suitability is also mentioned."""
        assert is_looking_for_roomie("מחפשת שותפה לדירה מהממת. הדירה עצמה מאוד מתאימה לשותפים!")
        
    def test_empty_or_no_mentions(self):
        assert not is_looking_for_roomie("דירה להשכרה, 3 חדרים")
        assert not is_looking_for_roomie("")
        assert not is_looking_for_roomie(None)


class TestDateParsing:
    """Test parsing relative dates and Yad2 image URLs."""
    
    def test_parse_relative_date_hours(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 6, 8, 12, 0, 0)
        assert parse_relative_date("3 שעות", now) == now - timedelta(hours=3)
        assert parse_relative_date("שעה", now) == now - timedelta(hours=1)
        assert parse_relative_date("2h", now) == now - timedelta(hours=2)
        
    def test_parse_relative_date_minutes(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 6, 8, 12, 0, 0)
        assert parse_relative_date("5 דקות", now) == now - timedelta(minutes=5)
        assert parse_relative_date("10m", now) == now - timedelta(minutes=10)
        
    def test_parse_relative_date_days(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 6, 8, 12, 0, 0)
        assert parse_relative_date("2 ימים", now) == now - timedelta(days=2)
        assert parse_relative_date("יום", now) == now - timedelta(days=1)
        assert parse_relative_date("3d", now) == now - timedelta(days=3)
        
    def test_parse_relative_date_named(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 6, 8, 12, 0, 0)
        assert parse_relative_date("אתמול", now) == now - timedelta(days=1)
        assert parse_relative_date("עכשיו", now) == now
        assert parse_relative_date("just now", now) == now
        
    def test_extract_yad2_posted_date(self):
        from datetime import datetime
        images = [
            "https://img.yad2.co.il/Pic/202606/07/some_image.jpg",
            "https://img.yad2.co.il/Pic/202606/08/some_image.jpg"
        ]
        assert extract_yad2_posted_date(images) == datetime(2026, 6, 8)
