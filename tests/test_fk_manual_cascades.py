import pytest
import aiosqlite
from database.connection import DatabaseManager
from database.repositories.user_repository import UserRepository
from database.repositories.listing_repository import SeenListingsRepository

@pytest.mark.asyncio
async def test_fk_constraints_without_db_cascade():
    # Setup standard SQLite DB in memory but create tables WITHOUT ON DELETE CASCADE.
    db = DatabaseManager(db_url="sqlite:///:memory:")
    # Initialize connection manually
    db._connection = await aiosqlite.connect(db._db_path)
    db._connection.row_factory = aiosqlite.Row
    
    # Enable foreign keys
    await db._connection.execute("PRAGMA foreign_keys=ON")
    
    # Create tables WITHOUT ON DELETE CASCADE
    await db._connection.execute("""
    CREATE TABLE users (
        telegram_id INTEGER PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        username TEXT,
        created_at TIMESTAMP,
        is_active BOOLEAN,
        first_notified_at TIMESTAMP,
        persona TEXT,
        is_admin BOOLEAN,
        allow_bordering_neighborhoods BOOLEAN,
        allow_roomies BOOLEAN
    )
    """)
    await db._connection.execute("""
    CREATE TABLE search_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        rule_type TEXT NOT NULL,
        value TEXT NOT NULL,
        original_text TEXT,
        is_active BOOLEAN,
        created_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(telegram_id)
    )
    """)
    await db._connection.execute("""
    CREATE TABLE rejection_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        listing_url TEXT,
        listing_price INTEGER,
        listing_location TEXT,
        failed_rules TEXT NOT NULL,
        reasons TEXT NOT NULL,
        match_method TEXT,
        created_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(telegram_id)
    )
    """)
    await db._connection.execute("""
    CREATE TABLE sent_notifications (
        user_id INTEGER NOT NULL,
        listing_id TEXT NOT NULL,
        sent_at TIMESTAMP,
        PRIMARY KEY (user_id, listing_id),
        FOREIGN KEY (user_id) REFERENCES users(telegram_id)
    )
    """)
    await db._connection.execute("""
    CREATE TABLE seen_listings (
        listing_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        url TEXT NOT NULL,
        first_seen_at TIMESTAMP
    )
    """)
    await db._connection.execute("""
    CREATE TABLE listing_fingerprints (
        listing_id TEXT PRIMARY KEY,
        author TEXT,
        phone TEXT,
        price INTEGER,
        bedrooms INTEGER,
        street TEXT,
        neighborhood TEXT,
        source TEXT NOT NULL,
        created_at TIMESTAMP,
        FOREIGN KEY (listing_id) REFERENCES seen_listings(listing_id)
    )
    """)
    await db._connection.commit()
    
    # Let's test seen_listings cleanup
    seen_repo = SeenListingsRepository(db)
    
    # Insert seen listing and its fingerprint
    listing_id = "listing_1"
    await db.execute(
        "INSERT INTO seen_listings (listing_id, source, url, first_seen_at) VALUES (?, ?, ?, ?)",
        (listing_id, "yad2", "http://yad2.co.il/1", "2020-01-01T00:00:00")
    )
    await db.execute(
        "INSERT INTO listing_fingerprints (listing_id, source) VALUES (?, ?)",
        (listing_id, "yad2")
    )
    
    # Verify they exist
    assert await db.fetch_one("SELECT 1 FROM seen_listings WHERE listing_id = ?", (listing_id,)) is not None
    assert await db.fetch_one("SELECT 1 FROM listing_fingerprints WHERE listing_id = ?", (listing_id,)) is not None
    
    # Run cleanup (which deletes older than 7 days, 2020 is definitely older than 7 days)
    await seen_repo.cleanup_old_entries(days_to_keep=7)
    
    # Verify deletion succeeded and listing is gone
    assert await db.fetch_one("SELECT 1 FROM seen_listings WHERE listing_id = ?", (listing_id,)) is None
    assert await db.fetch_one("SELECT 1 FROM listing_fingerprints WHERE listing_id = ?", (listing_id,)) is None

    # Let's test delete_user
    user_repo = UserRepository(db)
    
    # Insert user and child records
    user_id = 12345
    await db.execute(
        "INSERT INTO users (telegram_id, chat_id) VALUES (?, ?)",
        (user_id, user_id)
    )
    await db.execute(
        "INSERT INTO search_rules (user_id, rule_type, value) VALUES (?, ?, ?)",
        (user_id, "PRICE_MAX", "5000")
    )
    await db.execute(
        "INSERT INTO rejection_logs (listing_id, user_id, failed_rules, reasons) VALUES (?, ?, ?, ?)",
        ("listing_2", user_id, "[]", "[]")
    )
    await db.execute(
        "INSERT INTO sent_notifications (user_id, listing_id) VALUES (?, ?)",
        (user_id, "listing_2")
    )
    
    # Verify they exist
    assert await db.fetch_one("SELECT 1 FROM users WHERE telegram_id = ?", (user_id,)) is not None
    assert await db.fetch_one("SELECT 1 FROM search_rules WHERE user_id = ?", (user_id,)) is not None
    
    # Delete user
    await user_repo.delete_user(user_id)
    
    # Verify deletion succeeded and all are gone
    assert await db.fetch_one("SELECT 1 FROM users WHERE telegram_id = ?", (user_id,)) is None
    assert await db.fetch_one("SELECT 1 FROM search_rules WHERE user_id = ?", (user_id,)) is None
    assert await db.fetch_one("SELECT 1 FROM rejection_logs WHERE user_id = ?", (user_id,)) is None
    assert await db.fetch_one("SELECT 1 FROM sent_notifications WHERE user_id = ?", (user_id,)) is None
    
    await db.close()
