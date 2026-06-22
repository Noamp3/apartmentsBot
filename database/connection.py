# database/connection.py
"""Database connection and schema management."""

import asyncio
import aiosqlite
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from config import settings


# SQL Schema
SCHEMA = """
-- Users table
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    username TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    first_notified_at TIMESTAMP,
    persona TEXT DEFAULT 'barakush',
    is_admin BOOLEAN DEFAULT FALSE,
    allow_bordering_neighborhoods BOOLEAN DEFAULT TRUE,
    allow_roomies BOOLEAN DEFAULT TRUE,
    allow_sublets BOOLEAN DEFAULT FALSE
);

-- Search rules table
CREATE TABLE IF NOT EXISTS search_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL,
    value TEXT NOT NULL,
    original_text TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- Seen listings (for deduplication)
CREATE TABLE IF NOT EXISTS seen_listings (
    listing_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cached enriched listings
CREATE TABLE IF NOT EXISTS enriched_listings (
    listing_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    location TEXT,
    raw_text TEXT,
    images TEXT,  -- JSON array of image URLs
    screenshots TEXT,  -- JSON
    extracted_price INTEGER,
    extracted_bedrooms INTEGER,
    extracted_location TEXT,
    extracted_neighborhood TEXT,
    extracted_street TEXT,
    has_broker_fee BOOLEAN DEFAULT FALSE,
    roomies BOOLEAN DEFAULT FALSE,
    is_sublet BOOLEAN DEFAULT FALSE,
    sublet_duration TEXT,
    sublet_dates TEXT,
    attributes TEXT,  -- JSON
    area_matches TEXT,  -- JSON
    bordering_areas TEXT,  -- JSON
    posted_at TIMESTAMP,
    scraped_at TIMESTAMP,
    enriched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Rejection logs
CREATE TABLE IF NOT EXISTS rejection_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    listing_url TEXT,
    listing_price INTEGER,
    listing_location TEXT,
    failed_rules TEXT NOT NULL,  -- JSON array
    reasons TEXT NOT NULL,       -- JSON array
    match_method TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- AI Cache for persisting generated content
CREATE TABLE IF NOT EXISTS ai_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_type TEXT NOT NULL,  -- 'welcome' or 'sass'
    persona TEXT NOT NULL DEFAULT 'barakush',
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Facebook groups table
CREATE TABLE IF NOT EXISTS facebook_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scraped_count INTEGER DEFAULT 0,
    name TEXT DEFAULT NULL
);

-- Sent notifications (for preventing duplicates)
CREATE TABLE IF NOT EXISTS sent_notifications (
    user_id INTEGER NOT NULL,
    listing_id TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, listing_id),
    FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- Listing fingerprints (for cross-source duplicate detection)
CREATE TABLE IF NOT EXISTS listing_fingerprints (
    listing_id TEXT PRIMARY KEY,
    author TEXT,
    phone TEXT,
    price INTEGER,
    bedrooms INTEGER,
    street TEXT,
    neighborhood TEXT,
    source TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (listing_id) REFERENCES seen_listings(listing_id) ON DELETE CASCADE
);

-- System settings table
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scraping runs table
CREATE TABLE IF NOT EXISTS scraping_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds REAL,
    fb_total INTEGER DEFAULT 0,
    fb_new INTEGER DEFAULT 0,
    fb_failed BOOLEAN DEFAULT FALSE,
    yad2_total INTEGER DEFAULT 0,
    yad2_new INTEGER DEFAULT 0,
    yad2_failed BOOLEAN DEFAULT FALSE,
    status TEXT DEFAULT 'running', -- 'completed', 'failed', 'running'
    error_message TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_rules_user ON search_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_rules_active ON search_rules(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_rejections_user ON rejection_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_rejections_listing ON rejection_logs(listing_id);
CREATE INDEX IF NOT EXISTS idx_rejections_time ON rejection_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_cache_type ON ai_cache(cache_type);
CREATE INDEX IF NOT EXISTS idx_fingerprint_phone ON listing_fingerprints(phone);
CREATE INDEX IF NOT EXISTS idx_fingerprint_price ON listing_fingerprints(price);
CREATE INDEX IF NOT EXISTS idx_fingerprint_street ON listing_fingerprints(street);
CREATE INDEX IF NOT EXISTS idx_fingerprint_author ON listing_fingerprints(author);
"""


class DatabaseManager:
    """Manages database connections and initialization."""
    
    def __init__(self, db_url: str = None):
        self.db_url = db_url or settings.DATABASE_URL
        self._db_path = self._parse_db_path()
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
    
    def _parse_db_path(self) -> str:
        """Parse SQLite path from connection URL."""
        if self.db_url.startswith("sqlite:///"):
            return self.db_url.replace("sqlite:///", "")
        return self.db_url
    
    async def initialize(self):
        """Initialize database connection and create schema."""
        self._connection = await aiosqlite.connect(self._db_path, timeout=10.0)
        self._connection.row_factory = aiosqlite.Row
        
        # Enable WAL mode and other optimizations for concurrent reads/writes
        try:
            await self._connection.execute("PRAGMA journal_mode=WAL")
            await self._connection.execute("PRAGMA synchronous=NORMAL")
            await self._connection.execute("PRAGMA busy_timeout=10000")
            await self._connection.execute("PRAGMA foreign_keys=ON")
        except aiosqlite.OperationalError as e:
            # If the database is locked (e.g. another process is running under rollback mode),
            # log a warning and continue using the existing journal mode.
            from utils.logger import Loggers
            Loggers.db().warning(f"Could not configure database performance PRAGMAs: {e}")
        
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        
        # Safe migration: Add 'persona' column if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE users ADD COLUMN persona TEXT DEFAULT 'barakush'")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'onboarding_step' column if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE users ADD COLUMN onboarding_step TEXT DEFAULT NULL")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'is_admin' column if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'allow_bordering_neighborhoods' column if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE users ADD COLUMN allow_bordering_neighborhoods BOOLEAN DEFAULT TRUE")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'allow_roomies' column to users if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE users ADD COLUMN allow_roomies BOOLEAN DEFAULT TRUE")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'roomies' column to enriched_listings if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE enriched_listings ADD COLUMN roomies BOOLEAN DEFAULT FALSE")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'allow_sublets' column to users if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE users ADD COLUMN allow_sublets BOOLEAN DEFAULT FALSE")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'is_sublet' column to enriched_listings if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE enriched_listings ADD COLUMN is_sublet BOOLEAN DEFAULT FALSE")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'sublet_duration' column to enriched_listings if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE enriched_listings ADD COLUMN sublet_duration TEXT DEFAULT NULL")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'sublet_dates' column to enriched_listings if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE enriched_listings ADD COLUMN sublet_dates TEXT DEFAULT NULL")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'extracted_street' column to enriched_listings if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE enriched_listings ADD COLUMN extracted_street TEXT DEFAULT NULL")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        # Safe migration: Add 'screenshots' column to enriched_listings if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE enriched_listings ADD COLUMN screenshots TEXT DEFAULT NULL")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        try:
            await self._connection.execute("ALTER TABLE ai_cache ADD COLUMN persona TEXT DEFAULT 'barakush'")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
            
        try:
            await self._connection.execute("CREATE INDEX IF NOT EXISTS idx_ai_cache_persona ON ai_cache(cache_type, persona)")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass

        # Safe migration: Add 'last_scraped_count' column to facebook_groups if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE facebook_groups ADD COLUMN last_scraped_count INTEGER DEFAULT 0")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass

        # Safe migration: Add 'name' column to facebook_groups if it doesn't exist
        try:
            await self._connection.execute("ALTER TABLE facebook_groups ADD COLUMN name TEXT DEFAULT NULL")
            await self._connection.commit()
        except aiosqlite.OperationalError:
            pass
    
    async def close(self):
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
    
    @property
    def connection(self) -> aiosqlite.Connection:
        """Get the active database connection."""
        if self._connection is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._connection
    
    async def execute(self, query: str, params: tuple = ()):
        """Execute a query and return lastrowid."""
        async with self._lock:
            cursor = await self.connection.execute(query, params)
            await self.connection.commit()
            return cursor.lastrowid
    
    async def fetch_one(self, query: str, params: tuple = ()):
        """Fetch a single row."""
        async with self._lock:
            cursor = await self.connection.execute(query, params)
            return await cursor.fetchone()
    
    async def fetch_all(self, query: str, params: tuple = ()):
        """Fetch all rows."""
        async with self._lock:
            cursor = await self.connection.execute(query, params)
            return await cursor.fetchall()


# Global database manager instance and lock
_db_manager: Optional[DatabaseManager] = None
_db_lock = asyncio.Lock()


async def get_db() -> DatabaseManager:
    """Get the global database manager, initializing if needed."""
    global _db_manager
    if _db_manager is None:
        async with _db_lock:
            if _db_manager is None:
                _db_manager = DatabaseManager()
                await _db_manager.initialize()
    return _db_manager


@asynccontextmanager
async def get_db_session():
    """Context manager for database access."""
    db = await get_db()
    try:
        yield db
    finally:
        pass  # Connection stays open for reuse
