# core/matcher.py
"""Listing matching logic with rule-based and AI-powered matching."""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

from models.listing import EnrichedListing
from models.search_rule import SearchRule, RuleType
from utils.israeli_locations import get_location_db
from utils.logger import Loggers

log = Loggers.matcher()


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
        failed_rules = []
        
        for rule in rules:
            if not rule.is_active:
                continue
                
            if rule.rule_type == RuleType.PRICE_MAX:
                # Use effective price which includes broker fee if applicable
                effective_price = enriched.effective_monthly_price
                
                # STRICT VALIDATION: If price is missing, we can't ensure it's below max -> FAIL
                if effective_price is None:
                     failed_rules.append(f"חסר מחיר בדירה (לא ניתן לוודא מקסימום {int(rule.value):,}₪)")
                elif effective_price > int(rule.value):
                    if enriched.has_broker_fee:
                        failed_rules.append(
                            f"מחיר אפקטיבי {effective_price:,}₪ > מקסימום {int(rule.value):,}₪ "
                            f"(שכ\"ד {enriched.extracted_price:,}₪ + תיווך מפורס)"
                        )
                    else:
                        failed_rules.append(
                            f"מחיר {effective_price:,}₪ > מקסימום {int(rule.value):,}₪"
                        )
            
            elif rule.rule_type == RuleType.PRICE_MIN:
                # For min price, use base price (no broker fee consideration)
                price = enriched.extracted_price
                
                # STRICT VALIDATION: If price is missing, we can't ensure it's above min -> FAIL
                if price is None:
                    failed_rules.append(f"חסר מחיר בדירה (לא ניתן לוודא מינימום {int(rule.value):,}₪)")
                elif price < int(rule.value):
                    failed_rules.append(f"מחיר {price:,}₪ < מינימום {int(rule.value):,}₪")
            
            elif rule.rule_type == RuleType.BEDROOMS_MIN:
                bedrooms = enriched.extracted_bedrooms
                if bedrooms and bedrooms < int(rule.value):
                    failed_rules.append(f"חדרים {bedrooms} < מינימום {rule.value}")
            
            elif rule.rule_type == RuleType.BEDROOMS_MAX:
                bedrooms = enriched.extracted_bedrooms
                if bedrooms and bedrooms > int(rule.value):
                    failed_rules.append(f"חדרים {bedrooms} > מקסימום {rule.value}")
        
        if failed_rules:
            log.debug(f"Hard rules failed for {enriched.listing.title[:30]}...: {failed_rules}")
        
        return len(failed_rules) == 0, failed_rules


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
        rules: List[SearchRule]
    ) -> Tuple[bool, List[str]]:
        """Evaluate a single enriched listing against user rules.
        
        Uses ONLY pre-computed data - no AI calls.
        Returns: (is_match, rejection_reasons)
        """
        rejection_reasons = []
        
        log.debug(f"Evaluating listing {enriched.listing.id} against {len(rules)} rules")
        
        # Safety check: Matcher should not process old listings (older than 1 day)
        if enriched.listing.posted_at:
             age = datetime.now() - enriched.listing.posted_at
             if age.days >= 1:
                 return False, [f"דירה ישנה מדי (פורסמה לפני {age.days} ימים)"]
        
        # Phase 1: Check hard rules (price, bedrooms)
        passes_hard, hard_failures = self.pre_filter.passes_hard_rules(enriched, rules)
        rejection_reasons.extend(hard_failures)
        
        # Phase 2: Check soft rules (area, custom)
        for rule in rules:
            if not rule.is_active:
                continue
            
            if rule.rule_type == RuleType.AREA:
                area_match = self._check_area_match(enriched, rule.value)
                if not area_match[0]:
                    rejection_reasons.append(
                        f"מיקום {enriched.extracted_location or enriched.listing.location} לא תואם {rule.value}"
                    )
            
            elif rule.rule_type == RuleType.CUSTOM:
                custom_match = self._check_custom_rule(enriched, rule)
                if not custom_match[0]:
                    rejection_reasons.append(custom_match[1])
        
        return len(rejection_reasons) == 0, rejection_reasons
    
    def _check_area_match(
        self, 
        enriched: EnrichedListing, 
        target_area: str
    ) -> Tuple[bool, str]:
        """Check if listing location matches target area."""
        target_lower = target_area.strip().lower()
        
        # Check pre-computed area matches
        if enriched.area_matches:
            for area in enriched.area_matches:
                if target_lower in area.lower():
                    return True, ""
        
        # Check bordering areas
        if enriched.bordering_areas:
            for border_area in enriched.bordering_areas:
                if target_lower in border_area.lower():
                    return True, enriched.bordering_areas[border_area]
        
        # Use location database for matching
        listing_loc = enriched.extracted_location or enriched.listing.location
        is_match, match_type, _ = self.location_db.is_location_match(
            listing_loc, target_area
        )
        
        return is_match, ""
    
    def _check_custom_rule(
        self, 
        enriched: EnrichedListing, 
        rule: SearchRule
    ) -> Tuple[bool, str]:
        """Check custom rule against pre-computed attributes.
        
        Uses attribute matching where possible, otherwise assumes match
        (benefit of the doubt to avoid false negatives).
        """
        rule_text = rule.value.lower()
        attrs = enriched.attributes or {}
        
        # Try attribute-based matching
        for keyword, attr_name in self.keyword_to_attr.items():
            if keyword in rule_text:
                attr_value = attrs.get(attr_name)
                
                is_negation = any(neg in rule_text for neg in ["לא", "ללא", "בלי"])
                
                if attr_value is not None:
                    if is_negation and attr_value is True:
                        return False, f"הדירה כוללת {keyword}"
                    elif not is_negation and attr_value is False:
                        return False, f"הדירה לא כוללת {keyword}"
                
                # Known requirement, give benefit of doubt if uncertain
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


class HybridSmartMatcher:
    """Hybrid matcher that combines attribute matching with AI evaluation.
    
    Used for complex custom rules that can't be resolved by attributes alone.
    Budget-aware to respect Gemini free tier limits.
    """
    
    def __init__(
        self, 
        ai_engine: 'GeminiAIEngine',
        ai_calls_per_cycle_budget: int = None
    ):
        from core.ai_engine import GeminiAIEngine
        self.ai_engine = ai_engine
        self.ai_budget = ai_calls_per_cycle_budget or 5
        self.ai_calls_used = 0
        self.zero_ai_matcher = ZeroAIUserMatcher()
    
    async def evaluate_with_ai_fallback(
        self,
        enriched: EnrichedListing,
        rules: List[SearchRule]
    ) -> Tuple[bool, List[str], str]:
        """Evaluate listing with AI fallback for uncertain custom rules.
        
        Returns: (is_match, rejection_reasons, match_method)
        """
        # First try zero-AI matching
        is_match, reasons = self.zero_ai_matcher.evaluate_listing(enriched, rules)
        
        if is_match:
            return True, [], "attribute"
        
        # Check if any failures are from custom rules that could use AI
        custom_rules = [r for r in rules if r.rule_type == RuleType.CUSTOM]
        
        if custom_rules and self._can_use_ai():
            # Try AI evaluation for custom rules
            ai_match, ai_reasons = await self._ai_evaluate_customs(enriched, custom_rules)
            
            # Filter reasons - keep only non-custom failures + AI failures
            non_custom_reasons = [r for r in reasons if not any(
                cr.value.lower() in r.lower() for cr in custom_rules
            )]
            
            all_reasons = non_custom_reasons + ai_reasons
            return len(all_reasons) == 0, all_reasons, "ai"
        
        return is_match, reasons, "attribute"
    
    def _can_use_ai(self) -> bool:
        """Check if we have AI budget remaining for this cycle."""
        return self.ai_calls_used < self.ai_budget
    
    async def _ai_evaluate_customs(
        self,
        enriched: EnrichedListing,
        custom_rules: List[SearchRule]
    ) -> Tuple[bool, List[str]]:
        """Use AI to evaluate complex custom rules."""
        self.ai_calls_used += 1
        
        try:
            passes, reasons = await self.ai_engine.evaluate_custom_rules(
                enriched.listing, 
                [r.original_text or r.value for r in custom_rules]
            )
            return passes, reasons
        except Exception as e:
            log.warning(f"AI evaluation failed: {e}")
            return True, []  # Benefit of doubt on failure
    
    def reset_cycle_budget(self):
        """Reset AI budget for new processing cycle."""
        self.ai_calls_used = 0
