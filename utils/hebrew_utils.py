# utils/hebrew_utils.py
"""Hebrew text processing utilities."""

import re
from typing import Optional, Tuple


# Hebrew number words
HEBREW_NUMBERS = {
    "אחד": 1, "אחת": 1,
    "שתיים": 2, "שניים": 2, "שני": 2,
    "שלוש": 3, "שלושה": 3,
    "ארבע": 4, "ארבעה": 4,
    "חמש": 5, "חמישה": 5,
    "שש": 6, "שישה": 6,
    "שבע": 7, "שבעה": 7,
    "שמונה": 8,
    "תשע": 9, "תשעה": 9,
    "עשר": 10, "עשרה": 10,
}

# Currency patterns
CURRENCY_PATTERNS = [
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:ש[\"׳]?ח|שקל|₪)",  # 5000 ש"ח or 5000 ₪
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:שקלים?)",  # 5000 שקלים
    r"(?:ש[\"׳]?ח|₪)\s*(\d+(?:,\d{3})*(?:\.\d+)?)",  # ₪5000
]

# Thousands patterns
THOUSANDS_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*(?:אלף|א)",  # 5 אלף or 5א
    r"(\d+(?:\.\d+)?)\s*k",  # 5k
]


def extract_price(text: str) -> Optional[int]:
    """Extract price in shekels from Hebrew text.
    
    Handles formats like:
    - 5000 ש"ח
    - 5,000 שקל
    - 5 אלף
    - ₪5000
    """
    if not text:
        return None
    
    text = text.replace(",", "")
    
    # Try thousands patterns first
    for pattern in THOUSANDS_PATTERNS:
        match = re.search(pattern, text)
        if match:
            num = float(match.group(1))
            return int(num * 1000)
    
    # Try currency patterns
    for pattern in CURRENCY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            num = match.group(1).replace(",", "")
            return int(float(num))
    
    # Try bare numbers (4+ digits likely to be price)
    match = re.search(r"\b(\d{4,})\b", text)
    if match:
        return int(match.group(1))
    
    return None


def extract_bedrooms(text: str) -> Optional[int]:
    """Extract number of bedrooms from Hebrew text.
    
    Handles formats like:
    - 3 חדרים
    - שלושה חדרים
    - 3.5 חדרים (returns 3)
    """
    if not text:
        return None
    
    # Numeric patterns
    patterns = [
        r"(\d+(?:\.\d)?)\s*חדר",  # 3 חדרים or 3.5 חדרים
        r"דירת\s*(\d+)",  # דירת 3
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            num = float(match.group(1))
            return int(num)  # Round down for .5 rooms
    
    # Hebrew word numbers
    for word, num in HEBREW_NUMBERS.items():
        if re.search(rf"\b{word}\s*חדר", text):
            return num
    
    return None


def extract_floor(text: str) -> Optional[int]:
    """Extract floor number from Hebrew text."""
    if not text:
        return None
    
    patterns = [
        r"קומה\s*(\d+)",  # קומה 5
        r"קומת\s+קרקע",  # קומת קרקע = 0
        r"(\d+)\s*קומה",  # 5 קומה
    ]
    
    # Ground floor
    if re.search(r"קומת\s+קרקע|קומה\s*0", text):
        return 0
    
    for pattern in patterns[:2]:  # Skip ground floor pattern
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    
    return None


def has_broker_fee(text: str) -> bool:
    """Check if text mentions broker fee (תיווך)."""
    patterns = [
        r"תיווך",
        r"דמי\s*תיווך",
        r"עמלת\s*תיווך",
        r"ע[\"׳]י\s*מתווך",
        r"דרך\s*מתווך",
    ]
    
    if is_direct_from_owner(text):
        return False

    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def is_direct_from_owner(text: str) -> bool:
    """Check if listing is directly from owner."""
    patterns = [
        r"ללא\s*(?:דמי\s*)?תיווך",
        r"בלי\s*(?:דמי\s*)?תיווך",
        r"ישירות\s*מ?הבעלים",
        r"ישירות\s*מ?בעל\s*הדירה",
        r"פרטי",
        r"לא\s*תיווך",
    ]
    
    return any(re.search(p, text) for p in patterns)


def normalize_hebrew_text(text: str) -> str:
    """Normalize Hebrew text for comparison.
    
    - Removes extra whitespace
    - Normalizes quotes
    - Lowercase
    """
    if not text:
        return ""
    
    # Normalize quotes
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace("'", "'").replace("'", "'")
    text = text.replace("״", '"').replace("׳", "'")
    
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    
    return text.strip().lower()


def extract_contact_info(text: str) -> dict:
    """Extract contact information from text."""
    info = {"phone": None, "email": None}
    
    # Phone patterns (Israeli format)
    phone_patterns = [
        r"0\d{1,2}[-\s]?\d{7}",  # 03-1234567
        r"0\d{2}[-\s]?\d{3}[-\s]?\d{4}",  # 050-123-4567
        r"\+972[-\s]?\d{1,2}[-\s]?\d{7}",  # +972-3-1234567
        r"0\d{2}\d{7}",  # 0503330031
    ]
    
    for pattern in phone_patterns:
        match = re.search(pattern, text)
        if match:
            info["phone"] = match.group(0)
            break
    
    # Email
    email_match = re.search(r"[\w.-]+@[\w.-]+\.\w+", text)
    if email_match:
        info["email"] = email_match.group(0)
    
    return info
