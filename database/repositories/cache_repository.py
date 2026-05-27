# database/repositories/cache_repository.py
"""Repository for AI-generated content cache."""

from typing import List, Optional
from database.connection import DatabaseManager


class CacheRepository:
    """Manages AI cache for persisting generated content across restarts."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def get_cached_items(self, cache_type: str, persona: str = "barakush") -> List[str]:
        """Get all cached items of a specific type and persona."""
        rows = await self.db.fetch_all(
            "SELECT content FROM ai_cache WHERE cache_type = ? AND persona = ? ORDER BY created_at",
            (cache_type, persona)
        )
        return [row["content"] for row in rows]
    
    async def add_cached_items(self, cache_type: str, items: List[str], persona: str = "barakush"):
        """Add multiple items to the cache for a specific persona."""
        for item in items:
            await self.db.execute(
                "INSERT INTO ai_cache (cache_type, persona, content) VALUES (?, ?, ?)",
                (cache_type, persona, item)
            )
    
    async def pop_cached_item(self, cache_type: str, persona: str = "barakush") -> Optional[str]:
        """Pop the oldest item from cache for a specific persona (retrieve and delete)."""
        row = await self.db.fetch_one(
            "SELECT id, content FROM ai_cache WHERE cache_type = ? AND persona = ? ORDER BY created_at LIMIT 1",
            (cache_type, persona)
        )
        if row:
            await self.db.execute("DELETE FROM ai_cache WHERE id = ?", (row["id"],))
            return row["content"]
        return None
    
    async def get_cache_count(self, cache_type: str, persona: str = "barakush") -> int:
        """Get number of cached items of a specific type and persona."""
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as count FROM ai_cache WHERE cache_type = ? AND persona = ?",
            (cache_type, persona)
        )
        return row["count"] if row else 0
    
    async def clear_cache(self, cache_type: str = None, persona: str = None):
        """Clear cache. If cache_type/persona is provided, clears only matches."""
        if cache_type and persona:
            await self.db.execute("DELETE FROM ai_cache WHERE cache_type = ? AND persona = ?", (cache_type, persona))
        elif cache_type:
            await self.db.execute("DELETE FROM ai_cache WHERE cache_type = ?", (cache_type,))
        elif persona:
            await self.db.execute("DELETE FROM ai_cache WHERE persona = ?", (persona,))
        else:
            await self.db.execute("DELETE FROM ai_cache")
