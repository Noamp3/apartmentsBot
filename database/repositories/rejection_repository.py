# database/repositories/rejection_repository.py
"""Repository for rejection log operations."""

import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from database.connection import DatabaseManager
from models.rejection_log import RejectionLog


class RejectionRepository:
    """Stores and queries rejection logs for verification."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def log_rejection(
        self,
        listing_id: str,
        user_id: int,
        failed_rules: List[str],
        reasons: List[str],
        listing_url: Optional[str] = None,
        listing_price: Optional[int] = None,
        listing_location: Optional[str] = None,
        match_method: str = "rule",
    ):
        """Log a rejection with full context."""
        await self.db.execute(
            """
            INSERT INTO rejection_logs 
            (listing_id, user_id, listing_url, listing_price, listing_location,
             failed_rules, reasons, match_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing_id,
                user_id,
                listing_url,
                listing_price,
                listing_location,
                json.dumps(failed_rules, ensure_ascii=False),
                json.dumps(reasons, ensure_ascii=False),
                match_method,
                datetime.now().isoformat(),
            )
        )
    
    async def log_many_rejections(self, rejections: List[dict]):
        """Log multiple rejections in a single transaction."""
        if not rejections:
            return
        
        async with self.db._lock:
            now_str = datetime.now().isoformat()
            data = [
                (
                    r["listing_id"],
                    r["user_id"],
                    r.get("listing_url"),
                    r.get("listing_price"),
                    r.get("listing_location"),
                    json.dumps(r["failed_rules"], ensure_ascii=False),
                    json.dumps(r["reasons"], ensure_ascii=False),
                    r.get("match_method", "rule"),
                    r.get("created_at", now_str),
                )
                for r in rejections
            ]
            await self.db.connection.executemany(
                """
                INSERT INTO rejection_logs 
                (listing_id, user_id, listing_url, listing_price, listing_location,
                 failed_rules, reasons, match_method, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                data
            )
            await self.db.connection.commit()
    
    async def get_user_rejections(
        self,
        user_id: int,
        limit: int = 20,
        since_days: int = 7,
    ) -> List[RejectionLog]:
        """Get recent rejections for a user to review."""
        since = datetime.now() - timedelta(days=since_days)
        
        rows = await self.db.fetch_all(
            """
            SELECT * FROM rejection_logs
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, since.isoformat(), limit)
        )
        
        return [self._row_to_rejection(row) for row in rows]
    
    async def get_rejection_stats(self, user_id: int, days: int = 7) -> Dict[str, Any]:
        """Get rejection statistics for a user."""
        since = datetime.now() - timedelta(days=days)
        
        # Total count
        count_row = await self.db.fetch_one(
            """
            SELECT COUNT(*) as total, COUNT(DISTINCT listing_id) as unique_listings
            FROM rejection_logs
            WHERE user_id = ? AND created_at >= ?
            """,
            (user_id, since.isoformat())
        )
        
        # By match method
        method_rows = await self.db.fetch_all(
            """
            SELECT match_method, COUNT(*) as count
            FROM rejection_logs
            WHERE user_id = ? AND created_at >= ?
            GROUP BY match_method
            """,
            (user_id, since.isoformat())
        )
        
        by_method = {row["match_method"]: row["count"] for row in method_rows}
        
        return {
            "total_rejections": count_row["total"] if count_row else 0,
            "unique_listings": count_row["unique_listings"] if count_row else 0,
            "by_method": by_method,
            "period_days": days,
        }
    
    async def delete_old_rejections(self, older_than_days: int = 30):
        """Clean up old rejection logs."""
        cutoff = datetime.now() - timedelta(days=older_than_days)
        await self.db.execute(
            "DELETE FROM rejection_logs WHERE created_at < ?",
            (cutoff.isoformat(),)
        )
    
    def _row_to_rejection(self, row) -> RejectionLog:
        """Convert a database row to RejectionLog."""
        return RejectionLog(
            listing_id=row["listing_id"],
            user_id=row["user_id"],
            rejected_rules=json.loads(row["failed_rules"]),
            reasons=json.loads(row["reasons"]),
            listing_url=row["listing_url"],
            listing_price=row["listing_price"],
            listing_location=row["listing_location"],
            match_method=row["match_method"] or "rule",
            timestamp=row["created_at"],
        )
