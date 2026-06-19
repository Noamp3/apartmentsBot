# models/facebook_group.py
"""Facebook group model."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FacebookGroup:
    """Represents a Facebook group to be scraped."""
    
    url: str
    id: Optional[int] = None
    added_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Ensure added_at is a datetime object."""
        if isinstance(self.added_at, str):
            try:
                self.added_at = datetime.fromisoformat(self.added_at)
            except ValueError:
                self.added_at = datetime.now()
