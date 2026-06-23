# utils/israeli_locations.py
"""Israeli location database with neighborhood relationships."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import re
import os
import json
import asyncio

from utils.logger import Loggers

log = Loggers.db()


@dataclass
class Neighborhood:
    """Represents a neighborhood with its relationships."""
    name: str
    city: str
    aliases: List[str]
    bordering: List[str]
    area_type: str  # "central", "north", "south", "east", "jaffa", "coast"
    streets: List[str] = field(default_factory=list)


@dataclass
class Border:
    """Represents a geographic border in a city."""
    name: str
    city: str
    aliases: List[str]
    neighborhoods_west: List[str]  # Neighborhoods to the west of this border
    neighborhoods_east: List[str]  # Neighborhoods to the east of this border
    neighborhoods_north: List[str]  # Neighborhoods to the north of this border
    neighborhoods_south: List[str]  # Neighborhoods to the south of this border
    border_type: str  # "street", "highway", "natural" (beach/sea)


# Backward-compatible alias
TelAvivBorder = Border


class IsraeliLocationDatabase:
    """Database of Israeli cities and neighborhoods with relationships.
    
    Used for smart location matching without AI calls.
    """
    
    def __init__(self, schema_path: Optional[str] = None):
        if schema_path is None:
            # Default to locations.json in the same directory as this file
            schema_path = os.path.join(os.path.dirname(__file__), "locations.json")
        self.schema_path = schema_path
        self.custom_schema_path = os.path.join(os.path.dirname(schema_path), "locations_custom.json")
        self._lock = asyncio.Lock()
        self._normalize_cache = {}
        self._match_cache = {}
        self._load_database()
        
    def _load_database(self):
        self._normalize_cache = {}
        self._match_cache = {}
        with open(self.schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Merge custom locations if the file exists
        custom_schema_path = getattr(self, "custom_schema_path", None)
        if custom_schema_path and os.path.exists(custom_schema_path):
            try:
                with open(custom_schema_path, "r", encoding="utf-8") as f:
                    custom_data = json.load(f)
                
                # Create a map of existing neighborhoods in base data for quick lookup
                base_neighborhoods = {nb["name"]: nb for nb in data.get("neighborhoods", [])}
                
                for cust_nb in custom_data.get("neighborhoods", []):
                    nb_name = cust_nb.get("name")
                    if not nb_name:
                        continue
                    
                    if nb_name in base_neighborhoods:
                        # Merge custom streets and aliases into existing neighborhood
                        base_nb = base_neighborhoods[nb_name]
                        for field_name in ("streets", "aliases", "bordering"):
                            existing = base_nb.setdefault(field_name, [])
                            for val in cust_nb.get(field_name, []):
                                if val not in existing:
                                    existing.append(val)
                    else:
                        # Append completely new neighborhood
                        data.setdefault("neighborhoods", []).append(cust_nb)
            except Exception as e:
                log.error(f"Failed to merge custom locations from {custom_schema_path}: {e}")
            
        # City aliases (common variations)
        self.city_aliases: Dict[str, List[str]] = {}
        self.city_coords: Dict[str, Tuple[float, float]] = {}
        for city, city_info in data.get("cities", {}).items():
            self.city_aliases[city] = city_info.get("aliases", [])
            lat = city_info.get("latitude")
            lon = city_info.get("longitude")
            if lat is not None and lon is not None:
                self.city_coords[city] = (lat, lon)
            
        # Tel Aviv neighborhoods - COMPREHENSIVE LIST
        self.tel_aviv_neighborhoods: Dict[str, Neighborhood] = {}
        for n_data in data.get("neighborhoods", []):
            name = n_data["name"]
            self.tel_aviv_neighborhoods[name] = Neighborhood(
                name=name,
                city=n_data["city"],
                aliases=n_data.get("aliases", []),
                bordering=n_data.get("bordering", []),
                area_type=n_data.get("area_type", ""),
                streets=n_data.get("streets", [])
            )
            
        # Area groupings (for "אזור" type searches)
        self.area_groups: Dict[str, List[str]] = data.get("area_groups", {})
        
        # Tel Aviv geographic borders
        self.tel_aviv_borders: Dict[str, Border] = {}
        for b_data in data.get("borders", []):
            name = b_data["name"]
            self.tel_aviv_borders[name] = Border(
                name=name,
                city=b_data.get("city", "תל אביב"),
                aliases=b_data.get("aliases", []),
                neighborhoods_west=b_data.get("neighborhoods_west", []),
                neighborhoods_east=b_data.get("neighborhoods_east", []),
                neighborhoods_north=b_data.get("neighborhoods_north", []),
                neighborhoods_south=b_data.get("neighborhoods_south", []),
                border_type=b_data.get("border_type", "")
            )
            
        # Build reverse lookup maps
        self._build_lookups()
    
    @property
    def neighborhoods(self) -> Dict[str, Neighborhood]:
        """Expose neighborhoods for future expansions."""
        return self.tel_aviv_neighborhoods
        
    @property
    def borders(self) -> Dict[str, Border]:
        """Expose borders for future expansions."""
        return self.tel_aviv_borders
    
    def _build_lookups(self):
        """Build efficient lookup structures."""
        # Neighborhood by any name, sorted by length descending to prevent substring shadowing
        raw_lookup = {}
        for n in self.tel_aviv_neighborhoods.values():
            raw_lookup[n.name.lower()] = n
            for alias in n.aliases:
                raw_lookup[alias.lower()] = n
            for street in n.streets:
                raw_lookup[street.lower()] = n
        self.neighborhood_lookup = {k: raw_lookup[k] for k in sorted(raw_lookup.keys(), key=len, reverse=True)}
        
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
        if not raw_location:
            return {"city": None, "neighborhood": None, "normalized": ""}
            
        location = raw_location.strip().lower()
        if hasattr(self, "_normalize_cache") and location in self._normalize_cache:
            return self._normalize_cache[location]
            
        # Try to find neighborhood
        neighborhood = None
        for name in self.neighborhood_lookup:
            if name in location:
                # Fast check passed, now verify word boundaries to prevent substring matching bugs (e.g. matching 'שיר' in 'לשירותכם')
                pattern = rf"(?<![a-zA-Z0-9\u05d0-\u05ea\u05f3\u05f4'])[בהולכמש]{{0,2}}{re.escape(name)}(?![a-zA-Z0-9\u05d0-\u05ea\u05f3\u05f4'])"
                if re.search(pattern, location):
                    neighborhood = self.neighborhood_lookup[name]
                    break
        
        # Try to find city
        city = None
        for name, c in self.city_lookup.items():
            if name in location:
                # Fast check passed, now verify word boundaries to prevent substring matching bugs
                pattern = rf"(?<![a-zA-Z0-9\u05d0-\u05ea\u05f3\u05f4'])[בהולכמש]{{0,2}}{re.escape(name)}(?![a-zA-Z0-9\u05d0-\u05ea\u05f3\u05f4'])"
                if re.search(pattern, location):
                    city = c
                    break
        
        # If neighborhood found, check if a different city was explicitly mentioned in the location.
        # If a different city was found, then the neighborhood is a false positive (since our neighborhood list is for Tel Aviv/specific cities).
        if neighborhood and city and neighborhood.city != city:
            neighborhood = None

        # If neighborhood found but no city, use neighborhood's city
        if neighborhood and not city:
            city = neighborhood.city
        
        res = {
            "city": city,
            "neighborhood": neighborhood.name if neighborhood else None,
            "normalized": f"{neighborhood.name if neighborhood else ''}, {city if city else raw_location}".strip(", ")
        }
        if hasattr(self, "_normalize_cache"):
            self._normalize_cache[location] = res
        return res

    def is_city_mismatch(self, listing_city: str, target_city: str) -> bool:
        """Check if listing_city is explicitly a different city than target_city.
        
        Returns True if listing_city is a non-empty string and does not match target_city or its aliases,
        accounting for Hebrew prefixes (ב/מ/ה).
        """
        if not listing_city:
            return False
            
        listing_city_lower = listing_city.strip().lower()
        target_city_lower = target_city.strip().lower()
        
        # Get target city and all its aliases
        target_names = [target_city_lower]
        if target_city_lower in self.city_aliases:
            target_names.extend([a.lower() for a in self.city_aliases[target_city_lower]])
        elif target_city in self.city_aliases:
            target_names.extend([a.lower() for a in self.city_aliases[target_city]])
            
        # Check if the listing city is exactly one of the target city names/aliases
        if listing_city_lower in target_names:
            return False
            
        # Check if target city or its aliases are a substring of listing_city (longer aliases only)
        for target_name in target_names:
            if len(target_name) > 3 and target_name in listing_city_lower:
                return False
                
        # Check word boundaries for short aliases
        import re
        words = re.split(r'[\s\-\,\"\']+', listing_city_lower)
        for target_name in target_names:
            if target_name in words:
                return False
            # Check for Hebrew prefixes (ב/מ/ה) before the target name
            if f"ב{target_name}" in words or f"מ{target_name}" in words or f"ה{target_name}" in words:
                return False
            if listing_city_lower in (f"ב{target_name}", f"מ{target_name}", f"ה{target_name}"):
                return False
                
        # If listing_city is not empty but does not match any target name, it's a mismatch!
        return True

    
    def is_location_match(
        self, 
        listing_location: str, 
        target_location: str,
        allow_bordering: bool = True,
        listing_neighborhood_specified: bool = False
    ) -> Tuple[bool, str, str]:
        """Check if listing location matches target with smart logic.
        
        Returns: (is_match, match_type, explanation)
        match_type: "exact" | "contains" | "bordering" | "area_group" | "none"
        """
        cache_key = (
            listing_location.strip().lower() if listing_location else "", 
            target_location.strip().lower() if target_location else "", 
            allow_bordering, 
            listing_neighborhood_specified
        )
        if hasattr(self, "_match_cache") and cache_key in self._match_cache:
            return self._match_cache[cache_key]
            
        listing_norm = self.normalize_location(listing_location)
        target_norm = self.normalize_location(target_location)
        
        listing_city = listing_norm["city"]
        listing_neighborhood = listing_norm["neighborhood"]
        target_city = target_norm["city"]
        target_neighborhood = target_norm["neighborhood"]
        
        # Case 1: Exact neighborhood match
        if target_neighborhood and listing_neighborhood:
            if target_neighborhood == listing_neighborhood:
                res = (True, "exact", f"התאמה מדויקת: {target_neighborhood}")
                if hasattr(self, "_match_cache"):
                    self._match_cache[cache_key] = res
                return res
        
        # Case 2: Target is a city, listing is in that city
        if target_city and not target_neighborhood:
            if listing_city == target_city:
                res = (True, "contains", f"הדירה ב{listing_city}")
                if hasattr(self, "_match_cache"):
                    self._match_cache[cache_key] = res
                return res
        
        # Case 3: Bordering neighborhoods (symmetric check)
        if allow_bordering and target_neighborhood and listing_neighborhood:
            target_n = self.neighborhood_lookup.get(target_neighborhood.lower())
            listing_n = self.neighborhood_lookup.get(listing_neighborhood.lower())
            
            is_bordering = False
            if target_n and listing_neighborhood in target_n.bordering:
                is_bordering = True
            elif listing_n and target_neighborhood in listing_n.bordering:
                is_bordering = True
                
            if is_bordering:
                res = (True, "bordering", f"{listing_neighborhood} גובל ב{target_neighborhood}")
                if hasattr(self, "_match_cache"):
                    self._match_cache[cache_key] = res
                return res
        
        # Case 4: Area group match (e.g., "גוש דן", "המרכז")
        target_lower = target_location.lower()
        for group_name, cities in self.area_groups.items():
            if group_name in target_lower:
                if listing_city and listing_city in cities:
                    res = (True, "area_group", f"{listing_city} באזור {group_name}")
                    if hasattr(self, "_match_cache"):
                        self._match_cache[cache_key] = res
                    return res
                if listing_neighborhood and listing_neighborhood in cities:
                    res = (True, "area_group", f"{listing_neighborhood} באזור {group_name}")
                    if hasattr(self, "_match_cache"):
                        self._match_cache[cache_key] = res
                    return res
        
        # Case 5: Target is within listing area (reverse containment)
        if target_neighborhood and listing_city and not listing_neighborhood and not listing_neighborhood_specified:
            # Check if listing_location has specific details/streets other than the city name itself.
            # If it contains specific details, it is not a generic city listing and should not trigger containment.
            city_aliases = [listing_city.lower()] + [a.lower() for a in self.city_aliases.get(listing_city, [])]
            
            import re
            raw_clean = re.sub(r'[\(\)\-\,\s]', ' ', listing_location.lower()).strip()
            for alias in city_aliases:
                raw_clean = raw_clean.replace(alias.lower(), ' ')
            raw_clean = ' '.join(raw_clean.split())
            
            if not raw_clean:
                target_n = self.neighborhood_lookup.get(target_neighborhood.lower())
                if target_n and target_n.city == listing_city:
                    res = (True, "contains", f"הדירה ב{listing_city} (שכונה לא צוינה)")
                    if hasattr(self, "_match_cache"):
                        self._match_cache[cache_key] = res
                    return res
        
        res = (False, "none", "מיקום לא תואם")
        if hasattr(self, "_match_cache"):
            self._match_cache[cache_key] = res
        return res
    
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
                log.warning(
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
    
    def _find_border(self, border_name: str) -> Optional[Border]:
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

    async def async_resolve_unknown_location(
        self, 
        raw_location: str, 
        listing_details: str, 
        ai_engine
    ) -> dict:
        """Resolve an unknown location using LLM and update schema.
        
        If resolved, appends the identified alias or street name to the matched neighborhood
        in locations.json, reloads the database, and returns the normalized info.
        """
        # First verify if it's already resolvable
        norm = self.normalize_location(raw_location)
        if norm["neighborhood"]:
            return norm
            
        # Determine city and coordinates for grounding
        city = norm["city"]
        if not city:
            # Try to extract city from raw_location or listing_details
            for c, aliases in self.city_aliases.items():
                all_names = [c] + aliases
                if any(name.lower() in raw_location.lower() or name.lower() in listing_details.lower() for name in all_names):
                    city = c
                    break
                    
        if not city:
            city = "תל אביב"
            
        if city not in self.city_coords:
            raise ValueError(f"Grounding coordinates for city '{city}' not found in locations.json schema configuration.")
            
        lat, lon = self.city_coords[city]
            
        # Group neighborhoods by city
        neighborhoods_by_city = {}
        for n in self.tel_aviv_neighborhoods.values():
            neighborhoods_by_city.setdefault(n.city, []).append(n.name)
            
        prompt = f"""
You are an expert geographical matching assistant for Israeli cities and neighborhoods.
We have a listing with the following information:
- Raw location string: "{raw_location}"
- Listing details: "{listing_details}"

We could not match this raw location to a known neighborhood in our database.
Here is a list of known cities and their neighborhoods in our database:
{json.dumps(neighborhoods_by_city, ensure_ascii=False, indent=2)}

Your task:
1. Use your active Google Maps grounding search tool to look up the location, street, and landmarks mentioned in the raw location and listing details.
2. Identify the precise neighborhood in the target city where this location/street/landmark is situated.
3. If this neighborhood is in our list of known neighborhoods for that city, match it to that neighborhood name (must be exactly one of the names from the list above).
4. If this neighborhood is NOT in our list of known neighborhoods, specify the correct neighborhood name (in Hebrew, e.g. "יפו ג'") in the `matched_neighborhood` field, and we will dynamically add it to our database.
5. If you cannot confidently map it to any neighborhood, return null for matched_neighborhood.

In the JSON output:
- "matched_neighborhood" must be the name of the matched neighborhood (e.g. "הצפון הישן").
- "name_to_add" MUST NOT be null if we are mapping a specific street or alias that is not currently listed under this neighborhood. You MUST specify the exact street name (e.g. "ירמיהו" or "יהודה המכבי" or "שלמה המלך" or "סירקין") or neighborhood alias from the raw location or details to add. Only return null if the raw location itself is simply the exact name of the neighborhood and does not specify a street or landmark. CRITICAL: Strip any relational prepositions or prefixes such as "מול", "ליד", "בקרבת", "צמוד ל", "ליד ה", "ב", "מ" from the landmark/street name (e.g., if the raw location is "מול קאנטרי העלייה", the name_to_add should be "קאנטרי העלייה").
- "type" MUST be "street" if the name_to_add is a street name, or "alias" if it is a neighborhood alias/name variation. It MUST NOT be null if name_to_add is not null.

Return a JSON object with this schema:
{{
    "matched_neighborhood": "Name of the neighborhood (string, match from the list or a newly discovered neighborhood name) or null",
    "name_to_add": "The specific street name or neighborhood alias (string) to add, or null",
    "type": "Either 'street' or 'alias' or null"
}}

CRITICAL: Return ONLY a valid, raw JSON block. Your entire response must start with '{' and end with '}' and be directly parsesable by json.loads(). Do NOT include any conversational preamble, markdown blocks, or explanation outside the JSON.
"""
        try:
            log.info(f"Invoking AI engine with grounding to resolve unknown location: '{raw_location}'")
            response = await ai_engine.generate_content(
                prompt, 
                enable_grounding=True, 
                latitude=lat, 
                longitude=lon
            )
            result = ai_engine._parse_json_response(response)
            
            matched_nb = result.get("matched_neighborhood")
            name_to_add = result.get("name_to_add")
            name_type = result.get("type")
            
            if matched_nb and name_to_add and name_type in ("street", "alias"):
                name_to_add = name_to_add.strip()
                matched_nb = matched_nb.strip()
                
                async with self._lock:
                    custom_data = {"neighborhoods": []}
                    if os.path.exists(self.custom_schema_path):
                        try:
                            with open(self.custom_schema_path, "r", encoding="utf-8") as f:
                                custom_data = json.load(f)
                        except Exception as e:
                            log.error(f"Failed to load custom locations file for updating: {e}")
                    
                    # Read base config to check if neighborhood exists in base schema
                    with open(self.schema_path, "r", encoding="utf-8") as f:
                        base_data = json.load(f)
                    
                    base_nb_names = {nb["name"] for nb in base_data.get("neighborhoods", [])}
                    
                    updated = False
                    
                    # Find neighborhood in custom schema
                    nb_entry = next((nb for nb in custom_data.get("neighborhoods", []) if nb["name"] == matched_nb), None)
                    
                    if nb_entry:
                        # Existing custom entry: add street/alias
                        if name_type == "street":
                            streets = nb_entry.setdefault("streets", [])
                            if name_to_add.lower() not in [s.lower() for s in streets]:
                                streets.append(name_to_add)
                                updated = True
                        else:
                            aliases = nb_entry.setdefault("aliases", [])
                            if name_to_add.lower() not in [a.lower() for a in aliases]:
                                aliases.append(name_to_add)
                                updated = True
                    elif matched_nb in base_nb_names:
                        # In base schema, but not yet in custom schema. Create custom entry to override/extend it.
                        new_nb = {
                            "name": matched_nb,
                            "city": city,
                            "aliases": [],
                            "bordering": [],
                            "area_type": "unknown",
                            "streets": []
                        }
                        if name_type == "street":
                            new_nb["streets"].append(name_to_add)
                        else:
                            new_nb["aliases"].append(name_to_add)
                        custom_data.setdefault("neighborhoods", []).append(new_nb)
                        updated = True
                    else:
                        # Completely new neighborhood discovered!
                        log.info(f"Discovered new neighborhood: '{matched_nb}' in city '{city}'! Adding to custom schema.")
                        new_nb = {
                            "name": matched_nb,
                            "city": city,
                            "aliases": [],
                            "bordering": [],
                            "area_type": "unknown",
                            "streets": []
                        }
                        if name_type == "street":
                            new_nb["streets"].append(name_to_add)
                        else:
                            new_nb["aliases"].append(name_to_add)
                        
                        custom_data.setdefault("neighborhoods", []).append(new_nb)
                        updated = True
                        
                    if updated:
                        with open(self.custom_schema_path, "w", encoding="utf-8") as f:
                            json.dump(custom_data, f, indent=2, ensure_ascii=False)
                        self._load_database()
                        log.info(
                            f"Self-healed location schema: added '{name_to_add}' as {name_type} for neighborhood '{matched_nb}' to custom schema"
                        )
                        return self.normalize_location(raw_location)
        except Exception as e:
            log.error(f"Error during AI location resolution: {e}")
            
        return self.normalize_location(raw_location)


# Singleton instance
_location_db: Optional[IsraeliLocationDatabase] = None


def get_location_db() -> IsraeliLocationDatabase:
    """Get the singleton location database instance."""
    global _location_db
    if _location_db is None:
        _location_db = IsraeliLocationDatabase()
    return _location_db
