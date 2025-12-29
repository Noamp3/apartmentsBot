# database/repositories/cache_repository.py
"""Repository for AI-generated content cache."""

from typing import List, Optional
from database.connection import DatabaseManager


class CacheRepository:
    """Manages AI cache for persisting generated content across restarts."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def get_cached_items(self, cache_type: str) -> List[str]:
        """Get all cached items of a specific type."""
        rows = await self.db.fetch_all(
            "SELECT content FROM ai_cache WHERE cache_type = ? ORDER BY created_at",
            (cache_type,)
        )
        return [row["content"] for row in rows]
    
    async def add_cached_items(self, cache_type: str, items: List[str]):
        """Add multiple items to the cache."""
        for item in items:
            await self.db.execute(
                "INSERT INTO ai_cache (cache_type, content) VALUES (?, ?)",
                (cache_type, item)
            )
    
    async def pop_cached_item(self, cache_type: str) -> Optional[str]:
        """Pop the oldest item from cache (retrieve and delete)."""
        row = await self.db.fetch_one(
            "SELECT id, content FROM ai_cache WHERE cache_type = ? ORDER BY created_at LIMIT 1",
            (cache_type,)
        )
        if row:
            await self.db.execute("DELETE FROM ai_cache WHERE id = ?", (row["id"],))
            return row["content"]
        return None
    
    async def get_cache_count(self, cache_type: str) -> int:
        """Get number of cached items of a specific type."""
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as count FROM ai_cache WHERE cache_type = ?",
            (cache_type,)
        )
        return row["count"] if row else 0
    
    async def clear_cache(self, cache_type: str = None):
        """Clear cache. If cache_type is None, clears all cache."""
        if cache_type:
            await self.db.execute("DELETE FROM ai_cache WHERE cache_type = ?", (cache_type,))
        else:
            await self.db.execute("DELETE FROM ai_cache")
