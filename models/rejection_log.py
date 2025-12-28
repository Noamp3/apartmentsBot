# models/rejection_log.py
"""Rejection log model for tracking filtered listings."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class RejectionLog:
    """Log entry for a rejected listing, explaining why it was filtered out."""
    
    listing_id: str
    user_id: int
    rejected_rules: List[str]  # Which rules failed
    reasons: List[str]  # Human-readable explanations in Hebrew
    
    # Additional context
    listing_url: Optional[str] = None
    listing_price: Optional[int] = None
    listing_location: Optional[str] = None
    match_method: str = "rule"  # "rule", "ai", "smart_default", "benefit_of_doubt"
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Handle type conversions."""
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
    
    @property
    def rejection_summary(self) -> str:
        """Generate a Hebrew summary of why the listing was rejected."""
        if not self.reasons:
            return "נפסל ללא סיבה מפורטת"
        
        if len(self.reasons) == 1:
            return f"❌ {self.reasons[0]}"
        
        lines = ["❌ נפסל מהסיבות הבאות:"]
        for reason in self.reasons:
            lines.append(f"  • {reason}")
        
        return "\n".join(lines)
