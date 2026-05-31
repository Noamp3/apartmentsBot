# models/user.py
"""User model for Telegram users."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class User:
    """Represents a Telegram user with their search profile."""
    
    telegram_id: int
    chat_id: int
    username: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    first_notified_at: Optional[datetime] = None  # When user first received a listing
    persona: str = "barakush"
    is_admin: bool = False
    
    @property
    def is_new_user(self) -> bool:
        """Check if user has never received notifications yet."""
        return self.first_notified_at is None
    
    def __post_init__(self):
        """Ensure created_at is a datetime object."""
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
