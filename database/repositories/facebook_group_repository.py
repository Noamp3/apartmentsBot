# database/repositories/facebook_group_repository.py
"""Repository for Facebook group operations."""

from datetime import datetime
from typing import List, Optional

from database.connection import DatabaseManager
from models.facebook_group import FacebookGroup


class FacebookGroupRepository:
    """Handles CRUD operations for Facebook groups."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        
    async def create(self, group: FacebookGroup) -> FacebookGroup:
        """Add a new Facebook group to the database."""
        group_id = await self.db.execute(
            """
            INSERT OR IGNORE INTO facebook_groups (url, added_at)
            VALUES (?, ?)
            """,
            (group.url, group.added_at.isoformat())
        )
        if group_id:
            group.id = group_id
        return group
        
    async def get_all_groups(self) -> List[FacebookGroup]:
        """Fetch all Facebook groups sorted dynamically by scraped counts."""
        rows = await self.db.fetch_all("SELECT * FROM facebook_groups ORDER BY COALESCE(last_scraped_count, 0) DESC, added_at ASC")
        return [self._row_to_group(row) for row in rows]
        
    async def get_by_id(self, group_id: int) -> Optional[FacebookGroup]:
        """Get a Facebook group by ID."""
        row = await self.db.fetch_one("SELECT * FROM facebook_groups WHERE id = ?", (group_id,))
        if row:
            return self._row_to_group(row)
        return None

    async def get_by_url(self, url: str) -> Optional[FacebookGroup]:
        """Get a Facebook group by URL."""
        row = await self.db.fetch_one("SELECT * FROM facebook_groups WHERE url = ?", (url.strip(),))
        if row:
            return self._row_to_group(row)
        return None
        
    async def delete(self, group_id: int):
        """Delete a Facebook group from the database."""
        await self.db.execute("DELETE FROM facebook_groups WHERE id = ?", (group_id,))

    async def delete_by_url(self, url: str):
        """Delete a Facebook group from the database by URL."""
        await self.db.execute("DELETE FROM facebook_groups WHERE url = ?", (url.strip(),))
        
    async def update_scraped_count(self, url: str, count: int):
        """Update the last scraped count for a group."""
        await self.db.execute(
            "UPDATE facebook_groups SET last_scraped_count = ? WHERE url = ?",
            (count, url.strip())
        )

    def _row_to_group(self, row) -> FacebookGroup:
        """Convert database row to FacebookGroup object."""
        try:
            last_scraped_count = row["last_scraped_count"]
        except (KeyError, IndexError):
            last_scraped_count = 0
            
        return FacebookGroup(
            id=row["id"],
            url=row["url"],
            added_at=row["added_at"],
            last_scraped_count=last_scraped_count
        )
