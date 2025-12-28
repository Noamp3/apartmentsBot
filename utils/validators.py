# utils/validators.py
"""Input validation utilities."""

import re
from typing import Optional, Tuple
from models.search_rule import RuleType


def validate_price(value: str) -> Tuple[bool, Optional[int], str]:
    """Validate and normalize a price value.
    
    Returns: (is_valid, normalized_value, error_message)
    """
    # Remove commas and whitespace
    clean = value.replace(",", "").replace(" ", "").strip()
    
    # Handle "k" suffix (thousands)
    if clean.lower().endswith("k"):
        try:
            num = float(clean[:-1]) * 1000
            return True, int(num), ""
        except ValueError:
            return False, None, "מספר לא תקין"
    
    try:
        num = int(float(clean))
        if num < 0:
            return False, None, "המחיר חייב להיות חיובי"
        if num > 100000:
            return False, None, "המחיר נראה גבוה מדי (מעל 100,000)"
        return True, num, ""
    except ValueError:
        return False, None, "מספר לא תקין"


def validate_bedrooms(value: str) -> Tuple[bool, Optional[int], str]:
    """Validate number of bedrooms.
    
    Returns: (is_valid, normalized_value, error_message)
    """
    clean = value.strip()
    
    try:
        num = float(clean)
        if num < 1:
            return False, None, "מספר חדרים חייב להיות לפחות 1"
        if num > 20:
            return False, None, "מספר חדרים נראה גבוה מדי"
        return True, int(num), ""
    except ValueError:
        return False, None, "מספר לא תקין"


def validate_location(value: str) -> Tuple[bool, str, str]:
    """Validate a location string.
    
    Returns: (is_valid, normalized_value, error_message)
    """
    clean = value.strip()
    
    if not clean:
        return False, "", "יש לציין מיקום"
    
    if len(clean) < 2:
        return False, "", "המיקום קצר מדי"
    
    if len(clean) > 100:
        return False, "", "המיקום ארוך מדי"
    
    return True, clean, ""


def validate_custom_rule(value: str) -> Tuple[bool, str, str]:
    """Validate a custom rule text.
    
    Returns: (is_valid, normalized_value, error_message)
    """
    clean = value.strip()
    
    if not clean:
        return False, "", "יש לציין דרישה"
    
    if len(clean) < 3:
        return False, "", "הדרישה קצרה מדי"
    
    if len(clean) > 500:
        return False, "", "הדרישה ארוכה מדי"
    
    return True, clean, ""


def parse_rule_input(text: str) -> Tuple[Optional[RuleType], Optional[str], str]:
    """Attempt to parse user input into a rule type and value.
    
    This is a quick pattern-based parser. The AI engine provides
    more sophisticated parsing for complex inputs.
    
    Returns: (rule_type, value, original_text)
    """
    text = text.strip()
    
    # Price patterns
    price_max_patterns = [
        r"(?:עד|מקסימום|מקס|לכל היותר)\s*(\d+(?:,\d+)*k?)\s*(?:ש[\"׳]?ח|שקל|₪)?",
        r"(\d+(?:,\d+)*k?)\s*(?:ש[\"׳]?ח|שקל|₪)?\s*(?:מקסימום|מקס|top)",
    ]
    
    for pattern in price_max_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            is_valid, value, _ = validate_price(match.group(1))
            if is_valid:
                return RuleType.PRICE_MAX, str(value), text
    
    # Price min patterns
    price_min_patterns = [
        r"(?:מינימום|מינ|לפחות)\s*(\d+(?:,\d+)*k?)\s*(?:ש[\"׳]?ח|שקל|₪)?",
    ]
    
    for pattern in price_min_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            is_valid, value, _ = validate_price(match.group(1))
            if is_valid:
                return RuleType.PRICE_MIN, str(value), text
    
    # Bedrooms patterns
    bedroom_patterns = [
        r"(?:לפחות|מינימום)\s*(\d+)\s*חדר",
        r"(\d+)\s*חדר(?:ים)?\s*(?:לפחות|מינימום|ומעלה)",
        r"(\d+)\s*חדר(?:ים)?",
    ]
    
    for pattern in bedroom_patterns:
        match = re.search(pattern, text)
        if match:
            is_valid, value, _ = validate_bedrooms(match.group(1))
            if is_valid:
                return RuleType.BEDROOMS_MIN, str(value), text
    
    # Location - let AI handle complex locations
    # Just detect simple city names
    simple_locations = [
        "תל אביב", "ת\"א", "ירושלים", "חיפה", "רמת גן", "גבעתיים",
        "הרצליה", "רעננה", "פתח תקווה", "ראשון לציון", "נתניה"
    ]
    
    for loc in simple_locations:
        if loc in text:
            # Check if this is the primary content
            if len(text) < len(loc) + 20:
                return RuleType.AREA, loc, text
    
    # Default to custom rule - let AI interpret
    return RuleType.CUSTOM, text, text


def is_valid_telegram_id(telegram_id: int) -> bool:
    """Check if a Telegram ID is valid."""
    return isinstance(telegram_id, int) and telegram_id > 0
