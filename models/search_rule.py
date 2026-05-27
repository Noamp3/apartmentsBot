# models/search_rule.py
"""Search rule model with rule types."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RuleType(Enum):
    """Types of search rules.
    
    Hard rules (can be evaluated without AI):
    - PRICE_MAX, PRICE_MIN, BEDROOMS_MIN, BEDROOMS_MAX
    
    Soft rules (require AI judgment):
    - AREA, BORDER_AREA, CUSTOM
    """
    # Hard rules
    PRICE_MAX = "price_max"
    PRICE_MIN = "price_min"
    BEDROOMS_MIN = "bedrooms_min"
    BEDROOMS_MAX = "bedrooms_max"
    
    # Soft rules
    AREA = "area"
    BORDER_AREA = "border_area"  # Geographic border-based area (e.g., "west of Ayalon, north of Jaffa")
    CUSTOM = "custom"  # Catch-all for ANY user requirement


@dataclass
class SearchRule:
    """A single search rule for filtering apartment listings."""
    
    id: Optional[int] = None
    user_id: int = 0
    rule_type: RuleType = RuleType.CUSTOM
    value: str = ""  # For CUSTOM: stores the original Hebrew text as-is
    original_text: str = ""  # User's exact words for context
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Handle type conversions."""
        if isinstance(self.rule_type, str):
            self.rule_type = RuleType(self.rule_type)
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
    
    @property
    def is_hard_rule(self) -> bool:
        """Check if this rule can be evaluated without AI."""
        return self.rule_type in {
            RuleType.PRICE_MAX,
            RuleType.PRICE_MIN,
            RuleType.BEDROOMS_MIN,
            RuleType.BEDROOMS_MAX,
        }
    
    @property
    def is_soft_rule(self) -> bool:
        """Check if this rule requires AI judgment."""
        return self.rule_type in {RuleType.AREA, RuleType.BORDER_AREA, RuleType.CUSTOM}
