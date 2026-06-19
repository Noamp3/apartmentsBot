# core/matcher.py
"""Listing matching logic with rule-based and AI-powered matching."""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

from models.listing import EnrichedListing
from models.search_rule import SearchRule, RuleType
from utils.israeli_locations import get_location_db
from utils.logger import Loggers

log = Loggers.matcher()


def _parse_int_rule_value(value: str) -> int:
    """Safely parse a numeric rule value that might be float-formatted (e.g., '2.0')."""
    try:
        return int(float(value))
    except (ValueError, TypeError) as e:
        log.error(f"Failed to parse rule value '{value}' as numeric: {e}")
        raise


class RejectionReasons(list):
    """Subclass of list to hold failed rules info while maintaining backward compatibility."""
    def __init__(self, reasons, failed_rules=None):
        super().__init__(reasons)
        self.failed_rules = failed_rules or []


class RulePreFilter:
    """Filter listings using deterministic rules BEFORE calling AI."""
    
    @staticmethod
    def passes_hard_rules(
        enriched: EnrichedListing, 
        rules: List[SearchRule]
    ) -> Tuple[bool, List[str]]:
        """Check rules that don't require AI judgment.
        
        Uses effective_monthly_price which includes amortized broker fee.
        Returns (passes, list_of_failed_rules)
        """
        reasons = []
        failed_rules_names = []
        
        for rule in rules:
            if not rule.is_active:
                continue
                
            if rule.rule_type == RuleType.PRICE_MAX:
                # Use effective price which includes broker fee if applicable
                effective_price = enriched.effective_monthly_price
                
                # STRICT VALIDATION: If price is missing, we can't ensure it's below max -> FAIL
                if effective_price is None:
                     reasons.append(f"חסר מחיר בדירה (לא ניתן לוודא מקסימום {_parse_int_rule_value(rule.value):,}₪)")
                     failed_rules_names.append(f"מחיר מקסימלי: {rule.value}")
                elif effective_price > _parse_int_rule_value(rule.value):
                    failed_rules_names.append(f"מחיר מקסימלי: {rule.value}")
                    if enriched.has_broker_fee:
                        reasons.append(
                            f"מחיר אפקטיבי {effective_price:,}₪ > מקסימום {_parse_int_rule_value(rule.value):,}₪ "
                            f"(שכ\"ד {enriched.extracted_price:,}₪ + תיווך מפורס)"
                        )
                    else:
                        reasons.append(
                            f"מחיר {effective_price:,}₪ > מקסימום {_parse_int_rule_value(rule.value):,}₪"
                        )
            
            elif rule.rule_type == RuleType.PRICE_MIN:
                # For min price, use base price (no broker fee consideration)
                price = enriched.extracted_price
                
                # STRICT VALIDATION: If price is missing, we can't ensure it's above min -> FAIL
                if price is None:
                    reasons.append(f"חסר מחיר בדירה (לא ניתן לוודא מינימום {_parse_int_rule_value(rule.value):,}₪)")
                    failed_rules_names.append(f"מחיר מינימלי: {rule.value}")
                elif price < _parse_int_rule_value(rule.value):
                    reasons.append(f"מחיר {price:,}₪ < מינימום {_parse_int_rule_value(rule.value):,}₪")
                    failed_rules_names.append(f"מחיר מינימלי: {rule.value}")
            
            elif rule.rule_type == RuleType.BEDROOMS_MIN:
                bedrooms = enriched.extracted_bedrooms
                if bedrooms is not None and bedrooms < _parse_int_rule_value(rule.value):
                    reasons.append(f"חדרים {bedrooms} < מינימום {_parse_int_rule_value(rule.value)}")
                    failed_rules_names.append(f"מינימום חדרים: {rule.value}")
            
            elif rule.rule_type == RuleType.BEDROOMS_MAX:
                bedrooms = enriched.extracted_bedrooms
                if bedrooms is not None and bedrooms > _parse_int_rule_value(rule.value):
                    reasons.append(f"חדרים {bedrooms} > מקסימום {_parse_int_rule_value(rule.value)}")
                    failed_rules_names.append(f"מקסימום חדרים: {rule.value}")
        
        if reasons:
            log.debug(f"Hard rules failed for {enriched.listing.title[:30]}...: {reasons}")
        
        return len(reasons) == 0, RejectionReasons(reasons, failed_rules_names)


class ZeroAIUserMatcher:
    """Matches enriched listings to users WITHOUT any AI calls.
    
    All matching is done against pre-computed enriched data.
    """
    
    def __init__(self):
        self.pre_filter = RulePreFilter()
        self.location_db = get_location_db()
        
        # Known attribute mappings for custom rules
        self.keyword_to_attr = {
            "חניה": "has_parking",
            "מרפסת": "has_balcony",
            "מעלית": "has_elevator",
            "מזגן": "has_ac",
            "קומת קרקע": "is_ground_floor",
            "קומה גבוהה": "is_high_floor",
            "משופץ": "is_renovated",
            "חדש": "is_renovated",
            "חיות": "allows_pets",
            "כלב": "allows_pets",
            "חתול": "allows_pets",
            "שותפים": "suitable_for_roommates",
            "שותף": "roomies",
            "שותפה": "roomies",
            "שותפות": "roomies",
            "מחסן": "has_storage",
            "שומר": "has_security",
            "תחבורה": "near_public_transport",
            "אוטובוס": "near_public_transport",
            "רכבת": "near_public_transport",
            "ים": "near_beach",
            "מרוהטת": "is_furnished",
            "ריהוט": "is_furnished",
            "בעלים": "from_owner_direct",
        }
    
    def evaluate_listing(
        self, 
        enriched: EnrichedListing, 
        rules: List[SearchRule],
        allow_bordering: bool = True,
        allow_roomies: bool = True,
        allow_sublets: bool = False
    ) -> Tuple[bool, List[str]]:
        """Evaluate a single enriched listing against user rules.
        
        Uses ONLY pre-computed data - no AI calls.
        Returns: (is_match, rejection_reasons)
        """
        log.debug(f"Evaluating listing {enriched.listing.id} against {len(rules)} rules")
        
        # Safety check: Matcher should not process old listings (older than 1 day)
        if enriched.listing.posted_at:
             age = datetime.now() - enriched.listing.posted_at
             if age.days >= 1:
                  log.warning(f"Rejection safety: Old listing {enriched.listing.id} (age: {age.days} days)")
                  return False, RejectionReasons([f"דירה ישנה מדי (פורסמה לפני {age.days} ימים)"], ["דירה ישנה"])
        else:
             # If date is unknown, give benefit of the doubt and continue evaluation
             # Facebook date extraction often fails, and rejecting these loses too many valid listings
             log.debug(f"Unknown date for listing {enriched.listing.id} - accepting (benefit of doubt)")
        
        # Roomies check
        if not allow_roomies and enriched.roomies:
            return False, RejectionReasons(["דירת שותפים (קבלה מנוטרלת בהגדרות שלך)"], ["הגדרת שותפים"])
            
        # Sublet check
        if not allow_sublets and enriched.is_sublet:
            return False, RejectionReasons(["סאבלט (קבלה מנוטרלת בהגדרות שלך)"], ["הגדרת סאבלטים"])
        
        # Phase 1: Check hard rules (price, bedrooms)
        passes_hard, hard_failures = self.pre_filter.passes_hard_rules(enriched, rules)
        if not passes_hard:
            return False, hard_failures
 
        # Phase 2: Check soft rules (area, custom)
        area_rules = [r for r in rules if r.is_active and r.rule_type in (RuleType.AREA, RuleType.BORDER_AREA)]
        other_rules = [r for r in rules if r.is_active and r.rule_type not in (RuleType.AREA, RuleType.BORDER_AREA)]
        
        rejection_reasons = []
        failed_rule_names = []
        
        # Check area rules as an OR group (at least one must match if area rules exist)
        if area_rules:
            area_passes = False
            area_failures = []
            
            for rule in area_rules:
                if rule.rule_type == RuleType.AREA:
                    match_res = self._check_area_match(enriched, rule.value, allow_bordering)
                    if match_res[0]:
                        area_passes = True
                        break
                    else:
                        area_failures.append(rule.value)
                elif rule.rule_type == RuleType.BORDER_AREA:
                    match_res = self._check_border_area_match(enriched, rule.value)
                    if match_res[0]:
                        area_passes = True
                        break
                    else:
                        area_failures.append("אזור גיאוגרפי מוגדר")
                        #todo we should keep where the listing actualy is in db in scrapping phase instead of doing it here per user per listing, it's costly and we need it for rejection reason in case of border area failure
            
            if not area_passes:
                # Build detailed description of where the listing actually is
                actual_parts = []
                if enriched.extracted_neighborhood:
                    actual_parts.append(enriched.extracted_neighborhood)
                if enriched.extracted_street:
                    actual_parts.append(enriched.extracted_street)
                
                city_or_loc = enriched.extracted_location or enriched.listing.location
                if city_or_loc and city_or_loc not in actual_parts:
                    actual_parts.append(city_or_loc)
                
                actual_loc = ", ".join(actual_parts) if actual_parts else (enriched.extracted_location or enriched.listing.location or "לא ידוע")
                
                rejection_reasons.append(
                    f"מיקום {actual_loc} לא תואם אף אחד מהאזורים המבוקשים: {', '.join(area_failures)}"
                )
                failed_rule_names.append(f"אזור מגורים: {', '.join(area_failures)}")
        
        # Check other soft rules (AND logic)
        for rule in other_rules:
            if rule.rule_type == RuleType.CUSTOM:
                custom_match = self._check_custom_rule(enriched, rule)
                if not custom_match[0]:
                    rejection_reasons.append(custom_match[1])
                    failed_rule_names.append(f"דרישה מותאמת אישית: {rule.value}")
        
        return len(rejection_reasons) == 0, RejectionReasons(rejection_reasons, failed_rule_names)
    
    def _check_area_match(
        self, 
        enriched: EnrichedListing, 
        target_area: str,
        allow_bordering: bool = True
    ) -> Tuple[bool, str]:
        """Check if listing location matches target area."""
        # Use location database for matching
        # Build a composite listing location signal so the database can extract the neighborhood
        location_signals = []
        if enriched.extracted_neighborhood:
            location_signals.append(enriched.extracted_neighborhood)
        if enriched.extracted_street:
            location_signals.append(enriched.extracted_street)
        location_signals.append(enriched.extracted_location or enriched.listing.location)
        
        listing_loc = ", ".join(location_signals)
        
        is_match, match_type, _ = self.location_db.is_location_match(
            listing_loc, 
            target_area, 
            allow_bordering=allow_bordering,
            listing_neighborhood_specified=bool(enriched.extracted_neighborhood)
        )
        
        return is_match, ""
    
    def _check_border_area_match(
        self,
        enriched: EnrichedListing,
        neighborhoods_csv: str
    ) -> Tuple[bool, str]:
        """Check if listing location matches border-defined area (exact match only).
        
        Border-based rules do NOT include bordering neighborhoods by default.
        
        Args:
            enriched: Enriched listing
            neighborhoods_csv: Comma-separated list of neighborhood names
        
        Returns:
            (is_match, reason)
        """
        # Parse the neighborhood list
        allowed_neighborhoods = [n.strip() for n in neighborhoods_csv.split(",")]
        
        # Normalize listing location
        # Use all available signals: extracted neighborhood > street > location
        # We combine them so normalize_location can find the neighborhood in any of them
        location_signals = []
        if enriched.extracted_neighborhood:
            location_signals.append(enriched.extracted_neighborhood)
        if enriched.extracted_street:
            location_signals.append(enriched.extracted_street)
        
        location_signals.append(enriched.extracted_location or enriched.listing.location)
        
        composite_location = " ".join(location_signals)
        normalized = self.location_db.normalize_location(composite_location)
        
        # Check if listing neighborhood is in the allowed list
        if normalized["neighborhood"]:
            if normalized["neighborhood"] in allowed_neighborhoods:
                return True, ""
        
        # Also check if the raw location mentions any allowed neighborhood
        listing_lower = composite_location.lower()
        for allowed in allowed_neighborhoods:
            if allowed.lower() in listing_lower:
                return True, ""
        
        # RELAXED MATCHING: If the neighborhood is NOT identified (e.g. just "Tel Aviv"),
        # and the user asked not to filter based on missing data -> Pass it.
        # This prevents rejecting generic "Tel Aviv" listings when strict borders are on.
        if not normalized["neighborhood"]:
            return True, ""
            
        return False, f"השכונה לא באזור המוגדר"
    
    def _check_custom_rule(
        self, 
        enriched: EnrichedListing, 
        rule: SearchRule
    ) -> Tuple[bool, str]:
        """Check custom rule against pre-computed attributes.
        
        Uses attribute matching where possible, otherwise assumes match
        (benefit of the doubt for unknown rules to avoid false negatives).
        """
        rule_text = rule.value.lower()
        attrs = enriched.attributes or {}
        
        # Try attribute-based matching
        for keyword, attr_name in self.keyword_to_attr.items():
            if keyword in rule_text:
                attr_value = attrs.get(attr_name)
                is_negation = any(neg in rule_text for neg in ["לא", "ללא", "בלי"])
                
                if is_negation:
                    if attr_value is True:
                        return False, f"הדירה כוללת {keyword}"
                else:
                    if attr_value is not True:
                        return False, f"הדירה לא כוללת {keyword}"
                
                return True, ""
        
        # Unknown rule - give benefit of doubt
        return True, ""
    
    def match_listing_to_users(
        self,
        enriched: EnrichedListing,
        users_with_rules: Dict[int, List[SearchRule]]
    ) -> Dict[int, List[str]]:
        """Match a single listing to multiple users.
        
        Returns: {user_id: rejection_reasons} - empty list means match
        """
        results = {}
        
        for user_id, rules in users_with_rules.items():
            is_match, reasons = self.evaluate_listing(enriched, rules)
            results[user_id] = reasons  # Empty list = match
        
        return results

