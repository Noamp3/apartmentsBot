# models/user_settings.py
"""User settings model for customizable preferences."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class UserSettings:
    """User-specific settings and preferences."""
    
    id: Optional[int] = None
    user_id: int = 0
    expand_bordering_neighborhoods: bool = False  # Whether to include bordering neighborhoods in matches
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Handle type conversions."""
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
        if isinstance(self.updated_at, str):
            self.updated_at = datetime.fromisoformat(self.updated_at)
