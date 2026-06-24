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
    last_scraped_count: int = 0
    name: Optional[str] = None
    skip_next: int = 0
    consecutive_zeroes: int = 0

    def __post_init__(self):
        """Ensure added_at is a datetime object."""
        if isinstance(self.added_at, str):
            try:
                self.added_at = datetime.fromisoformat(self.added_at)
            except ValueError:
                self.added_at = datetime.now()

    @property
    def label(self) -> str:
        """Get a human-readable label for the group."""
        if self.name:
            return self.name
        # Fallback to URL-based extraction
        try:
            url = self.url.rstrip('/')
            parts = url.split('/groups/')
            if len(parts) > 1:
                return parts[1].split('/')[0].split('?')[0]
        except Exception:
            pass
        return self.url[-40:]  # fallback: last 40 chars
