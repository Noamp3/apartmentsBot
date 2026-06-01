# utils/israeli_locations.py
"""Israeli location database with neighborhood relationships."""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import re


@dataclass
class Neighborhood:
    """Represents a neighborhood with its relationships."""
    name: str
    city: str
    aliases: List[str]
    bordering: List[str]
    area_type: str  # "central", "north", "south", "east", "jaffa", "coast"


@dataclass
class TelAvivBorder:
    """Represents a geographic border in Tel Aviv."""
    name: str
    aliases: List[str]
    neighborhoods_west: List[str]  # Neighborhoods to the west of this border
    neighborhoods_east: List[str]  # Neighborhoods to the east of this border
    neighborhoods_north: List[str]  # Neighborhoods to the north of this border
    neighborhoods_south: List[str]  # Neighborhoods to the south of this border
    border_type: str  # "street", "highway", "natural" (beach/sea)


class IsraeliLocationDatabase:
    """Database of Israeli cities and neighborhoods with relationships.
    
    Used for smart location matching without AI calls.
    """
    
    def __init__(self):
        self._build_database()
    
    def _build_database(self):
        # City aliases (common variations)
        self.city_aliases: Dict[str, List[str]] = {
            "תל אביב": ["תל-אביב", "ת\"א", "תא", "תל אביב יפו", "תל-אביב-יפו", "tel aviv"],
            "ירושלים": ["י-ם", "ירושלים עיר", "jerusalem"],
            "חיפה": ["haifa"],
            "רמת גן": ["רמת-גן", "ר\"ג", "ramat gan"],
            "גבעתיים": ["גבעתים", "givatayim"],
            "הרצליה": ["herzliya"],
            "רעננה": ["raanana"],
            "פתח תקווה": ["פ\"ת", "פתח-תקווה", "petah tikva"],
            "ראשון לציון": ["ראשל\"צ", "ראשון-לציון", "rishon"],
            "הוד השרון": ["hod hasharon"],
            "כפר סבא": ["kfar saba"],
            "נתניה": ["netanya"],
            "באר שבע": ["ב\"ש", "beer sheva"],
            "חולון": ["holon"],
            "בת ים": ["bat yam"],
            "בני ברק": ["bnei brak"],
        }
        
        # Tel Aviv neighborhoods - COMPREHENSIVE LIST
        self.tel_aviv_neighborhoods: Dict[str, Neighborhood] = {
            # === SOUTH TEL AVIV ===
            "פלורנטין": Neighborhood(
                name="פלורנטין", city="תל אביב",
                aliases=["florentin", "שכונת פלורנטין"],
                bordering=["נווה צדק", "שפירא", "מונטיפיורי", "לב העיר", "נחלת בנימין"],
                area_type="south"
            ),
            "נווה צדק": Neighborhood(
                name="נווה צדק", city="תל אביב",
                aliases=["neve tzedek", "נוה צדק", "neveh tzedek"],
                bordering=["פלורנטין", "לב העיר", "כרם התימנים", "יפו"],
                area_type="south"
            ),
            "שפירא": Neighborhood(
                name="שפירא", city="תל אביב",
                aliases=["shapira", "שכונת שפירא"],
                bordering=["פלורנטין", "התקווה", "נווה שאנן", "כפר שלם"],
                area_type="south"
            ),
            "התקווה": Neighborhood(
                name="התקווה", city="תל אביב",
                aliases=["שכונת התקווה", "hatikva", "hatikvah"],
                bordering=["שפירא", "יד אליהו", "כפר שלם", "עזרא"],
                area_type="south"
            ),
            "נווה שאנן": Neighborhood(
                name="נווה שאנן", city="תל אביב",
                aliases=["neve shaanan", "נוה שאנן"],
                bordering=["שפירא", "פלורנטין"],
                area_type="south"
            ),
            "כפר שלם": Neighborhood(
                name="כפר שלם", city="תל אביב",
                aliases=["kfar shalem"],
                bordering=["התקווה", "שפירא", "יד אליהו"],
                area_type="south"
            ),
            "עזרא": Neighborhood(
                name="עזרא", city="תל אביב",
                aliases=["ezra"],
                bordering=["התקווה", "יד אליהו"],
                area_type="south"
            ),
            
            # === JAFFA / יפו ===
            "יפו": Neighborhood(
                name="יפו", city="תל אביב",
                aliases=["jaffa", "yafo", "יפו העתיקה"],
                bordering=["נווה צדק", "עג'מי", "יפו ג'", "יפו ד'"],
                area_type="jaffa"
            ),
            "עג'מי": Neighborhood(
                name="עג'מי", city="תל אביב",
                aliases=["ajami", "עגמי"],
                bordering=["יפו", "יפו ג'", "בת ים"],
                area_type="jaffa"
            ),
            "יפו ג'": Neighborhood(
                name="יפו ג'", city="תל אביב",
                aliases=["jaffa c", "יפו ג"],
                bordering=["יפו", "עג'מי", "יפו ד'"],
                area_type="jaffa"
            ),
            "יפו ד'": Neighborhood(
                name="יפו ד'", city="תל אביב",
                aliases=["jaffa d", "יפו ד"],
                bordering=["יפו", "יפו ג'", "גבעת עלייה"],
                area_type="jaffa"
            ),
            "גבעת עלייה": Neighborhood(
                name="גבעת עלייה", city="תל אביב",
                aliases=["givat aliya"],
                bordering=["יפו ד'", "חולון"],
                area_type="jaffa"
            ),
            
            # === CENTRAL TEL AVIV ===
            "לב העיר": Neighborhood(
                name="לב העיר", city="תל אביב",
                aliases=["מרכז העיר", "center", "city center", "downtown"],
                bordering=["פלורנטין", "נווה צדק", "רוטשילד", "הבימה", "כרם התימנים", "מונטיפיורי", "נחלת בנימין"],
                area_type="central"
            ),
            "רוטשילד": Neighborhood(
                name="רוטשילד", city="תל אביב",
                aliases=["שדרות רוטשילד", "rothschild", "רוטשילד בולבארד"],
                bordering=["לב העיר", "נווה צדק", "הבימה", "אחוזת בית"],
                area_type="central"
            ),
            "הבימה": Neighborhood(
                name="הבימה", city="תל אביב",
                aliases=["כיכר הבימה", "habima", "ליד הבימה"],
                bordering=["רוטשילד", "לב העיר", "הצפון הישן", "כרם התימנים"],
                area_type="central"
            ),
            "כרם התימנים": Neighborhood(
                name="כרם התימנים", city="תל אביב",
                aliases=["kerem hateimanim", "כרם", "the kerem"],
                bordering=["נווה צדק", "לב העיר", "הבימה", "שוק הכרמל"],
                area_type="central"
            ),
            "מונטיפיורי": Neighborhood(
                name="מונטיפיורי", city="תל אביב",
                aliases=["montefiore", "מונטיפיורה"],
                bordering=["פלורנטין", "לב העיר", "נחלת בנימין"],
                area_type="central"
            ),
            "נחלת בנימין": Neighborhood(
                name="נחלת בנימין", city="תל אביב",
                aliases=["nachalat binyamin", "נחלת בנימן"],
                bordering=["לב העיר", "פלורנטין", "מונטיפיורי", "שוק הכרמל"],
                area_type="central"
            ),
            "אחוזת בית": Neighborhood(
                name="אחוזת בית", city="תל אביב",
                aliases=["ahuzat bait", "אחוזת-בית"],
                bordering=["רוטשילד", "לב העיר"],
                area_type="central"
            ),
            "שוק הכרמל": Neighborhood(
                name="שוק הכרמל", city="תל אביב",
                aliases=["carmel market", "הכרמל"],
                bordering=["כרם התימנים", "נחלת בנימין", "לב העיר"],
                area_type="central"
            ),
            "דיזנגוף": Neighborhood(
                name="דיזנגוף", city="תל אביב",
                aliases=["dizengoff", "כיכר דיזנגוף", "דיזינגוף"],
                bordering=["בן יהודה", "הצפון הישן", "לב העיר"],
                area_type="central"
            ),
            "בן יהודה": Neighborhood(
                name="בן יהודה", city="תל אביב",
                aliases=["ben yehuda", "רחוב בן יהודה"],
                bordering=["לב העיר", "בוגרשוב", "דיזנגוף"],
                area_type="central"
            ),
            "אלנבי": Neighborhood(
                name="אלנבי", city="תל אביב",
                aliases=["allenby", "רחוב אלנבי"],
                bordering=["לב העיר", "נווה צדק", "כרם התימנים"],
                area_type="central"
            ),
            
            # === NORTH TEL AVIV ===
            "הצפון הישן": Neighborhood(
                name="הצפון הישן", city="תל אביב",
                aliases=["צפון ישן", "old north", "הצפון הישן תל אביב"],
                bordering=["הצפון החדש", "לב העיר", "הבימה", "בבלי", "דיזנגוף"],
                area_type="north"
            ),
            "הצפון החדש": Neighborhood(
                name="הצפון החדש", city="תל אביב",
                aliases=["צפון חדש", "new north"],
                bordering=["הצפון הישן", "רמת אביב", "בבלי", "כוכב הצפון", "נמל תל אביב"],
                area_type="north"
            ),
            "בבלי": Neighborhood(
                name="בבלי", city="תל אביב",
                aliases=["bavli"],
                bordering=["הצפון הישן", "הצפון החדש", "קרית שאול"],
                area_type="north"
            ),
            "כוכב הצפון": Neighborhood(
                name="כוכב הצפון", city="תל אביב",
                aliases=["kochav hatzafon", "star of the north"],
                bordering=["הצפון החדש", "רמת אביב"],
                area_type="north"
            ),
            "רמת אביב": Neighborhood(
                name="רמת אביב", city="תל אביב",
                aliases=["ramat aviv"],
                bordering=["הצפון החדש", "רמת אביב ג'", "נווה אביבים", "כוכב הצפון"],
                area_type="north"
            ),
            "רמת אביב ג'": Neighborhood(
                name="רמת אביב ג'", city="תל אביב",
                aliases=["ramat aviv gimel", "רמת אביב ג"],
                bordering=["רמת אביב", "נווה אביבים", "אפקה"],
                area_type="north"
            ),
            "נווה אביבים": Neighborhood(
                name="נווה אביבים", city="תל אביב",
                aliases=["neve avivim", "נוה אביבים"],
                bordering=["רמת אביב", "רמת אביב ג'", "אפקה"],
                area_type="north"
            ),
            "אפקה": Neighborhood(
                name="אפקה", city="תל אביב",
                aliases=["afeka"],
                bordering=["רמת אביב ג'", "נווה אביבים", "רמת החייל"],
                area_type="north"
            ),
            "רמת החייל": Neighborhood(
                name="רמת החייל", city="תל אביב",
                aliases=["ramat hachayal", "רמת החיל"],
                bordering=["אפקה", "תל ברוך", "רמת גן"],
                area_type="north"
            ),
            "תל ברוך": Neighborhood(
                name="תל ברוך", city="תל אביב",
                aliases=["tel baruch"],
                bordering=["רמת החייל", "תל ברוך צפון"],
                area_type="north"
            ),
            "תל ברוך צפון": Neighborhood(
                name="תל ברוך צפון", city="תל אביב",
                aliases=["tel baruch north"],
                bordering=["תל ברוך", "הרצליה"],
                area_type="north"
            ),
            
            # === EAST TEL AVIV ===
            "יד אליהו": Neighborhood(
                name="יד אליהו", city="תל אביב",
                aliases=["yad eliyahu"],
                bordering=["התקווה", "עזרא", "נווה שרת", "הארגזים"],
                area_type="east"
            ),
            "נווה שרת": Neighborhood(
                name="נווה שרת", city="תל אביב",
                aliases=["neve sharet", "נוה שרת"],
                bordering=["יד אליהו", "קריית שלום", "גבעתיים"],
                area_type="east"
            ),
            "קריית שלום": Neighborhood(
                name="קריית שלום", city="תל אביב",
                aliases=["kiryat shalom"],
                bordering=["נווה שרת", "חולון"],
                area_type="east"
            ),
            "הארגזים": Neighborhood(
                name="הארגזים", city="תל אביב",
                aliases=["haargazim"],
                bordering=["יד אליהו"],
                area_type="east"
            ),
            "קרית שאול": Neighborhood(
                name="קרית שאול", city="תל אביב",
                aliases=["kiryat shaul", "קריית שאול"],
                bordering=["בבלי", "רמת גן"],
                area_type="east"
            ),
            
            # === BEACH / COAST ===
            "נמל תל אביב": Neighborhood(
                name="נמל תל אביב", city="תל אביב",
                aliases=["tel aviv port", "הנמל", "namal", "port"],
                bordering=["הצפון החדש", "הירקון"],
                area_type="coast"
            ),
            "הירקון": Neighborhood(
                name="הירקון", city="תל אביב",
                aliases=["hayarkon", "רחוב הירקון"],
                bordering=["נמל תל אביב", "הצפון הישן", "לב העיר", "גורדון"],
                area_type="coast"
            ),
            "גורדון": Neighborhood(
                name="גורדון", city="תל אביב",
                aliases=["gordon", "חוף גורדון"],
                bordering=["הירקון", "הצפון הישן", "פרישמן"],
                area_type="coast"
            ),
            "פרישמן": Neighborhood(
                name="פרישמן", city="תל אביב",
                aliases=["frishman", "חוף פרישמן"],
                bordering=["גורדון", "לב העיר", "בוגרשוב"],
                area_type="coast"
            ),
            "בוגרשוב": Neighborhood(
                name="בוגרשוב", city="תל אביב",
                aliases=["bogrshov", "בוגרשוב סנטר"],
                bordering=["פרישמן", "לב העיר", "בן יהודה"],
                area_type="coast"
            ),
        }
        
        # Area groupings (for "אזור" type searches)
        self.area_groups: Dict[str, List[str]] = {
            "גוש דן": ["תל אביב", "רמת גן", "גבעתיים", "בני ברק", "חולון", "בת ים", "אור יהודה", "קרית אונו"],
            "המרכז": ["תל אביב", "רמת גן", "גבעתיים", "הרצליה", "רעננה", "כפר סבא", "הוד השרון", "פתח תקווה", "ראשון לציון", "חולון", "בת ים"],
            "השרון": ["הרצליה", "רעננה", "כפר סבא", "הוד השרון", "נתניה", "רמת השרון"],
            
            # Tel Aviv sub-areas
            "צפון תל אביב": ["הצפון הישן", "הצפון החדש", "רמת אביב", "רמת אביב ג'", "אפקה", "נווה אביבים", "רמת החייל", "תל ברוך", "כוכב הצפון", "בבלי"],
            "דרום תל אביב": ["פלורנטין", "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא"],
            "מרכז תל אביב": ["לב העיר", "רוטשילד", "הבימה", "כרם התימנים", "נווה צדק", "מונטיפיורי", "נחלת בנימין", "אחוזת בית", "שוק הכרמל", "דיזנגוף", "בן יהודה", "אלנבי"],
            "יפו": ["יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה"],
            "קו החוף": ["נמל תל אביב", "הירקון", "גורדון", "פרישמן", "בוגרשוב"],
            "מזרח תל אביב": ["יד אליהו", "נווה שרת", "קריית שלום", "הארגזים", "קרית שאול"],
        }
        
        # Tel Aviv geographic borders
        self.tel_aviv_borders: Dict[str, TelAvivBorder] = {
            "איילון": TelAvivBorder(
                name="איילון",
                aliases=["ayalon", "כביש איילון", "נהר איילון", "אילון"],
                neighborhoods_west=[
                    # Central/West TLV
                    "לב העיר", "רוטשילד", "הבימה", "כרם התימנים", "נווה צדק",
                    "פלורנטין", "מונטיפיורי", "נחלת בנימין", "אחוזת בית", "שוק הכרמל",
                    "דיזנגוף", "בן יהודה", "אלנבי", "הצפון הישן", "הצפון החדש",
                    "בבלי", "כוכב הצפון", "רמת אביב", "רמת אביב ג'", "נווה אביבים",
                    "אפקה", "נמל תל אביב", "הירקון", "גורדון", "פרישמן", "בוגרשוב",
                    # South TLV
                    "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא",
                    # Jaffa
                    "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה"
                ],
                neighborhoods_east=[
                    "רמת החייל", "תל ברוך", "יד אליהו", "נווה שרת",
                    "קריית שלום", "הארגזים", "קרית שאול", "תל ברוך צפון"
                ],
                neighborhoods_north=[],  # Not really a N/S divider
                neighborhoods_south=[],
                border_type="highway"
            ),
            "יפו": TelAvivBorder(
                name="יפו",
                aliases=["jaffa", "רחוב יפו", "יפו הישנה"],
                neighborhoods_west=[],  # Sea/Jaffa area to the west
                neighborhoods_east=[],
                neighborhoods_north=[
                    # Everything north of Jaffa street
                    "לב העיר", "רוטשילד", "הבימה", "כרם התימנים", "נווה צדק",
                    "מונטיפיורי", "נחלת בנימין", "אחוזת בית", "שוק הכרמל",
                    "דיזנגוף", "בן יהודה", "אלנבי", "הצפון הישן", "הצפון החדש",
                    "בבלי", "כוכב הצפון", "רמת אביב", "רמת אביב ג'", "נווה אביבים",
                    "אפקה", "רמת החייל", "תל ברוך", "נמל תל אביב", "הירקון",
                    "גורדון", "פרישמן", "בוגרשוב", "יד אליהו", "נווה שרת",
                    "קרית שאול", "תל ברוך צפון", "פלורנטין"
                ],
                neighborhoods_south=[
                    # Jaffa and southern areas
                    "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה",
                    "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא",
                    "קריית שלום", "הארגזים"
                ],
                border_type="street"
            ),
            "ארלוזורוב": TelAvivBorder(
                name="ארלוזורוב",
                aliases=["arlozorov", "ארלוזורוב סנטר", "רחוב ארלוזורוב", "ארלוזרוב", "ארלוזרוף", "ארלוזורוף"],
                neighborhoods_west=[],
                neighborhoods_east=[],
                neighborhoods_north=[
                    "רמת אביב", "רמת אביב ג'", "נווה אביבים", "אפקה",
                    "רמת החייל", "תל ברוך", "תל ברוך צפון", "נמל תל אביב",
                    "כוכב הצפון", "הצפון החדש"
                ],
                neighborhoods_south=[
                    "לב העיר", "רוטשילד", "הבימה", "כרם התימנים", "נווה צדק",
                    "פלורנטין", "מונטיפיורי", "נחלת בנימין", "אחוזת בית", "שוק הכרמל",
                    "דיזנגוף", "בן יהודה", "אלנבי", "הצפון הישן", "בבלי",
                    "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא",
                    "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה",
                    "יד אליהו", "נווה שרת", "קריית שלום", "הארגזים",
                    "קרית שאול", "הירקון", "גורדון", "פרישמן", "בוגרשוב"
                ],
                border_type="street"
            ),
            "דיזנגוף": TelAvivBorder(
                name="דיזנגוף",
                aliases=["dizengoff", "רחוב דיזנגוף", "דיזינגוף"],
                neighborhoods_west=[
                    "נמל תל אביב", "הירקון", "גורדון", "פרישמן", "בוגרשוב",
                    "בן יהודה"
                ],
                neighborhoods_east=[
                    "הצפון הישן", "הצפון החדש", "בבלי", "לב העיר",
                    "רמת אביב", "כוכב הצפון"
                ],
                neighborhoods_north=[],
                neighborhoods_south=[],
                border_type="street"
            ),
            "ים": TelAvivBorder(
                name="ים",
                aliases=["sea", "beach", "חוף", "הים", "ים התיכון"],
                neighborhoods_west=[],  # Open sea
                neighborhoods_east=[
                    # Everything is east of the sea
                    "נמל תל אביב", "הירקון", "גורדון", "פרישמן", "בוגרשוב",
                    "בן יהודה", "הצפון הישן", "הצפון החדש", "לב העיר",
                    "נווה צדק", "יפו", "עג'מי"
                ],
                neighborhoods_north=[],
                neighborhoods_south=[],
                border_type="natural"
            ),
            "ירקון": TelAvivBorder(
                name="ירקון",
                aliases=["hayarkon", "נחל הירקון", "הירקון", "ירקון"],
                neighborhoods_west=[],
                neighborhoods_east=[],
                neighborhoods_north=[
                    "רמת אביב", "רמת אביב ג'", "נווה אביבים", "אפקה",
                    "רמת החייל", "תל ברוך", "תל ברוך צפון", "כוכב הצפון", "קרית שאול"
                ],
                neighborhoods_south=[
                    "הצפון הישן", "הצפון החדש", "בבלי", "לב העיר", "רוטשילד",
                    "הבימה", "כרם התימנים", "נווה צדק", "פלורנטין", "מונטיפיורי",
                    "נחלת בנימין", "אחוזת בית", "שוק הכרמל", "דיזנגוף", "בן יהודה",
                    "אלנבי", "נמל תל אביב", "הירקון", "גורדון", "פרישמן",
                    "בוגרשוב", "יד אליהו", "נווה שרת", "קריית שלום", "הארגזים",
                    "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא",
                    "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה"
                ],
                border_type="natural"
            ),
            "פלורנטין": TelAvivBorder(
                name="פלורנטין",
                aliases=["florentin", "שכונת פלורנטין"],
                neighborhoods_west=["נווה צדק", "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה"],
                neighborhoods_east=["יד אליהו", "נווה שרת", "קריית שלום", "הארגזים", "קרית שאול"],
                neighborhoods_north=[
                    "לב העיר", "רוטשילד", "הבימה", "כרם התימנים", "מונטיפיורי",
                    "נחלת בנימין", "אחוזת בית", "שוק הכרמל", "דיזנגוף", "בן יהודה",
                    "אלנבי", "הצפון הישן", "הצפון החדש", "בבלי", "כוכב הצפון",
                    "רמת אביב", "רמת אביב ג'", "נווה אביבים", "אפקה", "רמת החייל",
                    "תל ברוך", "תל ברוך צפון", "נמל תל אביב", "הירקון", "גורדון",
                    "פרישמן", "בוגרשוב", "יד אליהו", "נווה שרת", "קרית שאול"
                ],
                neighborhoods_south=[
                    "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא",
                    "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה",
                    "קריית שלום", "הארגזים"
                ],
                border_type="street"
            ),
            "אלנבי": TelAvivBorder(
                name="אלנבי",
                aliases=["allenby", "רחוב אלנבי", "אלנבי סנטר"],
                neighborhoods_west=["נווה צדק", "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה", "כרם התימנים", "שוק הכרמל"],
                neighborhoods_east=["מונטיפיורי", "נחלת בנימין", "יד אליהו", "נווה שרת", "קריית שלום", "הארגזים", "קרית שאול", "שפירא", "התקווה", "נווה שאנן", "כפר שלם", "עזרא"],
                neighborhoods_north=[
                    "לב העיר", "רוטשילד", "הבימה", "דיזנגוף", "בן יהודה",
                    "הצפון הישן", "הצפון החדש", "בבלי", "כוכב הצפון", "רמת אביב",
                    "רמת אביב ג'", "נווה אביבים", "אפקה", "רמת החייל", "תל ברוך",
                    "תל ברוך צפון", "נמל תל אביב", "הירקון", "גורדון", "פרישמן",
                    "בוגרשוב", "יד אליהו", "נווה שרת", "קרית שאול", "מונטיפיורי",
                    "נחלת בנימין"
                ],
                neighborhoods_south=[
                    "פלורנטין", "שפירא", "התקווה", "נווה שאנן", "כפר שלם",
                    "עזרא", "יפו", "עג'מי", "יפו ג'", "יפו ד'", "גבעת עלייה",
                    "קריית שלום", "הארגזים", "נווה צדק", "אחוזת בית"
                ],
                border_type="street"
            ),
            "רוטשילד": TelAvivBorder(
                name="רוטשילד",
                aliases=["rothschild", "שדרות רוטשילד", "רוטשילד בולבארד"],
                neighborhoods_west=["נווה צדק", "כרם התימנים", "שוק הכרמל", "ים", "גורדון", "פרישמן", "בוגרשוב", "בן יהודה", "יפו", "עג'מי"],
                neighborhoods_east=["מונטיפיורי", "נחלת בנימין", "לב העיר", "שפירא", "התקווה", "יד אליהו", "נווה שרת", "קריית שלום", "הארגזים", "קרית שאול", "כפר שלם", "עזרא"],
                neighborhoods_north=[
                    "לב העיר", "הבימה", "דיזנגוף", "בן יהודה", "הצפון הישן",
                    "הצפון החדש", "בבלי", "כוכב הצפון", "רמת אביב", "רמת אביב ג'",
                    "נווה אביבים", "אפקה", "רמת החייל", "תל ברוך", "תל ברוך צפון",
                    "נמל תל אביב", "הירקון", "גורדון", "פרישמן", "בוגרשוב",
                    "יד אליהו", "נווה שרת", "קרית שאול", "מונטיפיורי"
                ],
                neighborhoods_south=[
                    "נווה צדק", "פלורנטין", "שפירא", "התקווה", "נווה שאנן",
                    "כפר שלם", "עזרא", "יפו", "עג'מי", "יפו ג'", "יפו ד'",
                    "גבעת עלייה", "קריית שלום", "הארגזים", "אחוזת בית"
                ],
                border_type="street"
            ),
        }
        
        # Build reverse lookup maps
        self._build_lookups()
    
    def _build_lookups(self):
        """Build efficient lookup structures."""
        # Neighborhood by any name
        self.neighborhood_lookup: Dict[str, Neighborhood] = {}
        for n in self.tel_aviv_neighborhoods.values():
            self.neighborhood_lookup[n.name.lower()] = n
            for alias in n.aliases:
                self.neighborhood_lookup[alias.lower()] = n
        
        # City by any name
        self.city_lookup: Dict[str, str] = {}
        for city, aliases in self.city_aliases.items():
            self.city_lookup[city.lower()] = city
            for alias in aliases:
                self.city_lookup[alias.lower()] = city
    
    def normalize_location(self, raw_location: str) -> dict:
        """Normalize a raw location string to structured data.
        
        Returns: {"city": str, "neighborhood": str, "normalized": str}
        """
        location = raw_location.strip().lower()
        
        # Try to find neighborhood
        neighborhood = None
        for name in self.neighborhood_lookup:
            if name in location:
                neighborhood = self.neighborhood_lookup[name]
                break
        
        # Try to find city
        city = None
        for name, c in self.city_lookup.items():
            if name in location:
                city = c
                break
        
        # If neighborhood found but no city, use neighborhood's city
        if neighborhood and not city:
            city = neighborhood.city
        
        return {
            "city": city,
            "neighborhood": neighborhood.name if neighborhood else None,
            "normalized": f"{neighborhood.name if neighborhood else ''}, {city if city else raw_location}".strip(", ")
        }
    
    def is_location_match(
        self, 
        listing_location: str, 
        target_location: str,
        allow_bordering: bool = True
    ) -> Tuple[bool, str, str]:
        """Check if listing location matches target with smart logic.
        
        Returns: (is_match, match_type, explanation)
        match_type: "exact" | "contains" | "bordering" | "area_group" | "none"
        """
        listing_norm = self.normalize_location(listing_location)
        target_norm = self.normalize_location(target_location)
        
        listing_city = listing_norm["city"]
        listing_neighborhood = listing_norm["neighborhood"]
        target_city = target_norm["city"]
        target_neighborhood = target_norm["neighborhood"]
        
        # Case 1: Exact neighborhood match
        if target_neighborhood and listing_neighborhood:
            if target_neighborhood == listing_neighborhood:
                return True, "exact", f"התאמה מדויקת: {target_neighborhood}"
        
        # Case 2: Target is a city, listing is in that city
        if target_city and not target_neighborhood:
            if listing_city == target_city:
                return True, "contains", f"הדירה ב{listing_city}"
        
        # Case 3: Bordering neighborhoods
        if allow_bordering and target_neighborhood and listing_neighborhood:
            target_n = self.neighborhood_lookup.get(target_neighborhood.lower())
            if target_n and listing_neighborhood in target_n.bordering:
                return True, "bordering", f"{listing_neighborhood} גובל ב{target_neighborhood}"
        
        # Case 4: Area group match (e.g., "גוש דן", "המרכז")
        target_lower = target_location.lower()
        for group_name, cities in self.area_groups.items():
            if group_name in target_lower:
                if listing_city and listing_city in cities:
                    return True, "area_group", f"{listing_city} באזור {group_name}"
                if listing_neighborhood and listing_neighborhood in cities:
                    return True, "area_group", f"{listing_neighborhood} באזור {group_name}"
        
        # Case 5: Target is within listing area (reverse containment)
        if target_neighborhood and listing_city and not listing_neighborhood:
            target_n = self.neighborhood_lookup.get(target_neighborhood.lower())
            if target_n and target_n.city == listing_city:
                return True, "contains", f"הדירה ב{listing_city} (שכונה לא צוינה)"
        
        return False, "none", "מיקום לא תואם"
    
    def get_bordering_neighborhoods(self, neighborhood: str) -> List[str]:
        """Get list of neighborhoods that border the given one."""
        n = self.neighborhood_lookup.get(neighborhood.lower())
        return n.bordering if n else []
    
    def expand_area_search(self, target: str) -> List[str]:
        """Expand a search target to include all matching areas."""
        results = set()
        target_lower = target.lower()
        
        # Add exact match
        if target_lower in self.neighborhood_lookup:
            n = self.neighborhood_lookup[target_lower]
            results.add(n.name)
            results.update(n.bordering)
        
        if target_lower in self.city_lookup:
            city = self.city_lookup[target_lower]
            results.add(city)
            # Add all neighborhoods in that city
            for n in self.tel_aviv_neighborhoods.values():
                if n.city == city:
                    results.add(n.name)
        
        # Check area groups
        for group_name, cities in self.area_groups.items():
            if group_name in target_lower:
                results.update(cities)
        
        return list(results)
    
    def get_neighborhoods_within_borders(
        self,
        constraints: Dict[str, str]
    ) -> List[str]:
        """Get neighborhoods that satisfy all border constraints.
        
        Args:
            constraints: Dict with keys like 'west_of', 'east_of', 'north_of', 'south_of'
                        and values being border names (e.g., {'west_of': 'איילון', 'north_of': 'יפו'})
        
        Returns:
            List of neighborhood names that satisfy ALL constraints.
            Returns an empty list if any constraint border is not found (strict behavior).
        """
        # Start with all Tel Aviv neighborhoods
        all_neighborhoods = set(self.tel_aviv_neighborhoods.keys())
        
        # Apply each constraint
        for constraint_type, border_name in constraints.items():
            border = self._find_border(border_name)
            if not border:
                # If a border is not found, fail strictly by returning [] rather than ignoring it
                import logging
                logging.getLogger("apartments_bot").warning(
                    f"Border '{border_name}' in constraint '{constraint_type}' was not found. "
                    "Aborting geo border matching to prevent overly broad results."
                )
                return []
            
            if constraint_type == 'west_of':
                # Everything west of this border
                all_neighborhoods &= set(border.neighborhoods_west)
            elif constraint_type == 'east_of':
                # Everything east of this border
                all_neighborhoods &= set(border.neighborhoods_east)
            elif constraint_type == 'north_of':
                # Everything north of this border
                all_neighborhoods &= set(border.neighborhoods_north)
            elif constraint_type == 'south_of':
                # Everything south of this border
                all_neighborhoods &= set(border.neighborhoods_south)
        
        return list(all_neighborhoods)
    
    def _find_border(self, border_name: str) -> Optional[TelAvivBorder]:
        """Find a border by name or alias, supporting fuzzy matching and Hebrew prefix stripping."""
        border_lower = border_name.strip().lower()
        
        # Strip common Hebrew prefixes / articles
        for prefix in ["רחוב ", "כביש ", "נחל ", "שכונת "]:
            if border_lower.startswith(prefix):
                border_lower = border_lower[len(prefix):]
                break
                
        # Build lookup table of lowercased name & aliases
        border_possibilities = {}
        for border in self.tel_aviv_borders.values():
            border_possibilities[border.name.lower()] = border
            for alias in border.aliases:
                border_possibilities[alias.lower()] = border
                
        # 1. Direct exact match
        if border_lower in border_possibilities:
            return border_possibilities[border_lower]
            
        # 2. Exact match with leading 'ה' stripped (definite article)
        if border_lower.startswith("ה") and len(border_lower) > 2:
            stripped = border_lower[1:]
            if stripped in border_possibilities:
                return border_possibilities[stripped]
                
        # 3. Fuzzy match using difflib
        import difflib
        possibility_keys = list(border_possibilities.keys())
        close_matches = difflib.get_close_matches(border_lower, possibility_keys, n=1, cutoff=0.6)
        if close_matches:
            return border_possibilities[close_matches[0]]
            
        # 4. Fuzzy match with leading 'ה' stripped
        if border_lower.startswith("ה") and len(border_lower) > 2:
            stripped = border_lower[1:]
            close_matches = difflib.get_close_matches(stripped, possibility_keys, n=1, cutoff=0.6)
            if close_matches:
                return border_possibilities[close_matches[0]]
                
        return None


# Singleton instance
_location_db: Optional[IsraeliLocationDatabase] = None


def get_location_db() -> IsraeliLocationDatabase:
    """Get the singleton location database instance."""
    global _location_db
    if _location_db is None:
        _location_db = IsraeliLocationDatabase()
    return _location_db
