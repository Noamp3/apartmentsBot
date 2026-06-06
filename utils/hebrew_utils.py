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
    r"(\d+(?:,\d{3})*)ש\"ח",  # 5000ש"ח (no space)
    r"(\d+(?:,\d{3})*)\s*(?:לחודש|לח)",  # 5000 לחודש
    r"(\d+(?:,\d{3})*)\s*NIS",  # 5000 NIS
    r"(?:מחיר|שכ\"ד|שכירות)[:\s]+(\d+(?:,\d{3})*)",  # מחיר: 5000 or שכ"ד 5000
]

# Thousands patterns
THOUSANDS_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*(?:אלף|א')",  # 5 אלף or 5א'
    r"(\d+(?:\.\d+)?)\s*k",  # 5k
    r"(\d+(?:\.\d+)?)\s*אלפים",  # 5 אלפים
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
    
    # NOTE: We intentionally do NOT fall back to bare numbers here.
    # Phone numbers like 0522505694 would be incorrectly parsed as prices.
    # Only extract price when currency indicators are present.
    
    return None


def extract_bedrooms(text: str) -> Optional[int]:
    """Extract number of bedrooms from Hebrew text.
    
    Handles formats like:
    - 3 חדרים
    - שלושה חדרים
    - 3.5 חדרים (returns 3)
    - 3 וחצי חדרים (returns 3)
    - סטודיו (returns 1)
    """
    if not text:
        return None
    
    # Studio = 1 room
    if re.search(r"סטודיו|studio", text, re.IGNORECASE):
        return 1
    
    # Numeric patterns
    patterns = [
        r"(\d+)\s*וחצי\s*חדר",  # 3 וחצי חדרים
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
    
    # Ground floor patterns
    if re.search(r"קומת\s+קרקע|קומה\s*0|קומה\s+ראשונה|ground\s*floor", text, re.IGNORECASE):
        return 0
    
    # Penthouse = high floor indicator (return None, let AI determine)
    if re.search(r"פנטהאוז|penthouse|גג", text, re.IGNORECASE):
        return None  # Can't determine exact floor
    
    # Hebrew word floor numbers
    floor_words = {
        "שנייה": 2, "שניה": 2,
        "שלישית": 3,
        "רביעית": 4,
        "חמישית": 5,
        "שישית": 6,
        "שביעית": 7,
        "שמינית": 8,
        "תשיעית": 9,
        "עשירית": 10,
    }
    
    for word, floor_num in floor_words.items():
        if re.search(rf"קומה\s+{word}", text):
            return floor_num
    
    # Numeric patterns
    patterns = [
        r"קומה\s*(\d+)",  # קומה 5
        r"(\d+)\s*קומה",  # 5 קומה
        r"floor\s*(\d+)",  # floor 5
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
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
        r"0%?\s*תיווך",  # 0% תיווך or 0 תיווך
        r"תיווך\s*0%?",  # תיווך 0%
        r"ללא\s*עמלה",   # no commission
        r"ללא\s*דמי",    # no fees
        r"חינם",          # free (no fees)
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


def extract_sqm(text: str) -> Optional[int]:
    """Extract apartment size in square meters from text."""
    if not text:
        return None
    
    patterns = [
        r"(\d+)\s*(?:מ\"ר|מטר|מ׳|sqm|m2|מ\"מ)",  # 80 מ"ר
        r"(\d+)\s*(?:מטרים?\s*רבועים?)",  # 80 מטרים רבועים
        r"שטח[:\s]+(\d+)",  # שטח: 80
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            sqm = int(match.group(1))
            # Sanity check: apartments are typically 20-500 sqm
            if 15 <= sqm <= 500:
                return sqm
    
    return None


def has_immediate_entry(text: str) -> bool:
    """Check if listing offers immediate entry/availability."""
    patterns = [
        r"כניסה\s*מיידית",
        r"פנוי\s*(?:מיד|עכשיו|להיום)",
        r"פנויה\s*(?:מיד|עכשיו|להיום)",
        r"available\s*(?:now|immediately)",
        r"מיידי",
        r"פנוי\s*לאלתר",
    ]
    
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def is_looking_for_roomie(text: str) -> bool:
    """Check if the text indicates looking for a roommate/flatmate.
    
    Returns True if the listing is looking for a roommate (e.g. renting a room,
    looking for a flatmate), but False if it just says 'suitable for roommates'
    (מתאים לשותפים) without indicating a search for a roommate.
    """
    if not text:
        return False
        
    text_normalized = text.lower().strip()
    
    # 1. Look for patterns indicating we are looking/searching for a roommate
    # E.g., מחפש שותף, מחפשת שותפה, דרוש שותף, מחפשים שותפים, מחפש/ת שותף/ה
    search_patterns = [
        r"מחפש\s*(?:/|ות|ים|ה)?\s*שות[פף]",
        r"מחפש\s*שות[פף]",
        r"מחפשת\s*שות[פף]",
        r"מחפשים\s*שות[פף]",
        r"מחפש/ת\s*שות[פף]",
        r"דרוש\s*(?:/|ות|ים|ה)?\s*שות[פף]",
        r"דרוש\s*שות[פף]",
        r"דרושה\s*שות[פף]",
        r"דרושים\s*שות[פף]",
        r"שות[פף]/ה",
        r"שות[פף]ים/ות",
        r"שותפות\s*בדירה",
        r"להיכנס\s+לשותפות",
        r"להשתלב\s+בדירת\s+שות[פף]ים",
        r"מחפש\s*להיכנס\s*לדירה",
        r"נכנס/ת\s*שות[פף]",
        r"שות[פף]\s*נוסף",
        r"שות[פף]ה\s*נוספת",
        r"שות[פף]\s*שלישי",
        r"שות[פף]ה\s*שלישית",
    ]
    
    # 2. Look for patterns indicating renting out a single room in an apartment (which implies roommates)
    # E.g., חדר בדירת שותפים, חדר להשכרה בדירה, להשכרה חדר בדירה
    room_patterns = [
        r"חדר\s*(?:פנוי\s*)?בדירת\s*שות[פף]ים",
        r"להשכרה\s*חדר\s*בדירת\s*שות[פף]ים",
        r"חדר\s*בדירה\s*שות[פף]ים",
        r"חדר\s*בדירת\s*שותפות",
        r"להשכרה\s*חדר\s*בדירה",
        r"חדר\s*להשכרה\s*בדירה",
        r"חדר\s*להשכרה\s*(?:ב)?פלורנטין",
        r"חדר\s*פנוי\s*(?:ב)?דירה",
        r"סאבלט\s*של\s*חדר",
        r"חדר\s*בסאבלט",
    ]
    
    # Check if any room pattern matches
    if any(re.search(p, text_normalized) for p in room_patterns):
        return True
        
    # Check if any search pattern matches
    if any(re.search(p, text_normalized) for p in search_patterns):
        # We found roommate-related words. However, we must ensure that these are not 
        # solely in the context of suitability (e.g. "מתאים לשותפים").
        
        # Let's count how many times "שותף/שותפה/שותפים" appears in the text, allowing prefix prepositions
        all_roomie_mentions = re.findall(r"\b[בלהמווכ]?שות[פף][א-ת]*/?[א-ת]*\b", text_normalized)
        
        # Find all occurrences of "suitability for roommates"
        # E.g., מתאים לשותפים, מתאימה לשותפים, מעולה לשותפים, סבבה לשותפים, מתאימים לשותפים, מתאימות לשותפים
        suitability_patterns = [
            r"מתאים\s*(?:גם\s*)?לשות[פף]",
            r"מתאימה\s*(?:גם\s*)?לשות[פף]",
            r"מתאימים\s*(?:גם\s*)?לשות[פף]",
            r"מתאימות\s*(?:גם\s*)?לשות[פף]",
            r"סבבה\s*לשות[פף]",
            r"מעולה\s*לשות[פף]",
            r"טוב\s*לשות[פף]",
            r"מושלם\s*לשות[פף]",
            r"מושלמת\s*לשות[פף]",
            r"פחות\s*מתאים\s*לשות[פף]",
            r"לא\s*מתאים\s*לשות[פף]",
        ]
        
        suitability_matches = []
        for p in suitability_patterns:
            suitability_matches.extend(re.findall(p, text_normalized))
            
        # If the number of suitability mentions is equal to or greater than the total number of
        # roommate mentions, it means every roommate mention is just a suitability claim.
        if len(suitability_matches) >= len(all_roomie_mentions):
            return False
            
        return True
        
    return False

