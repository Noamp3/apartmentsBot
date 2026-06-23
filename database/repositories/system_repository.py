# database/repositories/system_repository.py
"""Repository for system-wide settings and scraping runs performance telemetry."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from database.connection import DatabaseManager


class SystemRepository:
    """Handles persistence of bot configurations and scraping run telemetry."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Fetch a system setting by its key."""
        row = await self.db.fetch_one(
            "SELECT value FROM system_settings WHERE key = ?",
            (key,)
        )
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        """Set or update a system setting."""
        await self.db.execute(
            """
            INSERT OR REPLACE INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (key, str(value))
        )

    async def get_scrape_interval(self) -> Optional[int]:
        """Get the custom scraping interval in minutes."""
        val = await self.get_setting("scrape_interval_minutes")
        return int(val) if val is not None else None

    async def set_scrape_interval(self, minutes: int):
        """Set the custom scraping interval in minutes."""
        await self.set_setting("scrape_interval_minutes", str(minutes))

    async def get_auto_adjust_interval(self) -> bool:
        """Check if automatic interval adjustment based on quota limits is enabled."""
        val = await self.get_setting("auto_adjust_interval")
        return val == "True" if val is not None else True

    async def set_auto_adjust_interval(self, enable: bool):
        """Enable or disable automatic interval adjustment."""
        await self.set_setting("auto_adjust_interval", str(enable))

    async def get_ai_retries(self) -> Optional[int]:
        """Get the custom AI retries limit."""
        val = await self.get_setting("ai_retries")
        return int(val) if val is not None else None

    async def set_ai_retries(self, retries: int):
        """Set the custom AI retries limit."""
        await self.set_setting("ai_retries", str(retries))

    async def start_scraping_run(self) -> int:
        """Start a new scraping run record in the database. Returns the run's ID."""
        run_id = await self.db.execute(
            """
            INSERT INTO scraping_runs (start_time, status)
            VALUES (?, 'running')
            """,
            (datetime.now().isoformat(),)
        )
        return run_id

    async def complete_scraping_run(
        self,
        run_id: int,
        fb_total: int,
        fb_new: int,
        fb_failed: bool,
        yad2_total: int,
        yad2_new: int,
        yad2_failed: bool,
        status: str = "completed",
        duration_seconds: float = 0.0,
        error_message: Optional[str] = None
    ):
        """Complete a scraping run and update its metrics and status."""
        await self.db.execute(
            """
            UPDATE scraping_runs
            SET end_time = ?,
                duration_seconds = ?,
                fb_total = ?,
                fb_new = ?,
                fb_failed = ?,
                yad2_total = ?,
                yad2_new = ?,
                yad2_failed = ?,
                status = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(),
                duration_seconds,
                fb_total,
                fb_new,
                fb_failed,
                yad2_total,
                yad2_new,
                yad2_failed,
                status,
                error_message,
                run_id
            )
        )

    async def get_last_run(self) -> Optional[Dict[str, Any]]:
        """Get the most recent scraping run details."""
        row = await self.db.fetch_one(
            "SELECT * FROM scraping_runs ORDER BY start_time DESC LIMIT 1"
        )
        return dict(row) if row else None

    async def get_recent_runs(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent scraping runs."""
        rows = await self.db.fetch_all(
            "SELECT * FROM scraping_runs ORDER BY start_time DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in rows]

    async def get_next_scheduled_run_time(self) -> Optional[datetime]:
        """Get the next scheduled scraping run time."""
        val = await self.get_setting("next_scheduled_run_time")
        return datetime.fromisoformat(val) if val is not None else None

    async def set_next_scheduled_run_time(self, dt: datetime):
        """Set the next scheduled scraping run time."""
        await self.set_setting("next_scheduled_run_time", dt.isoformat())
