# database/repositories/notification_repository.py
"""Repository for notification tracking."""

from typing import Set, List
from database.connection import DatabaseManager
from utils.logger import Loggers

log = Loggers.db()


class NotificationRepository:
    """Tracks which listings have been notified to which users."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def has_sent(self, user_id: int, listing_id: str) -> bool:
        """Check if a notification has already been sent."""
        row = await self.db.fetch_one(
            "SELECT 1 FROM sent_notifications WHERE user_id = ? AND listing_id = ?",
            (user_id, listing_id)
        )
        return row is not None
    
    async def mark_sent(self, user_id: int, listing_id: str):
        """Mark a notification as sent."""
        await self.db.execute(
            """
            INSERT OR IGNORE INTO sent_notifications (user_id, listing_id)
            VALUES (?, ?)
            """,
            (user_id, listing_id)
        )
    
    async def mark_many_sent(self, user_id: int, listing_ids: List[str]):
        """Mark multiple notifications as sent."""
        for listing_id in listing_ids:
            await self.mark_sent(user_id, listing_id)
            
    async def get_user_sent_ids(self, user_id: int) -> Set[str]:
        """Get all listing IDs sent to a user."""
        rows = await self.db.fetch_all(
            "SELECT listing_id FROM sent_notifications WHERE user_id = ?",
            (user_id,)
        )
        return {row["listing_id"] for row in rows}
