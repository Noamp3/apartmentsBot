"""Migration script to add images column to enriched_listings table."""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite
from config import settings


async def main():
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    db = await aiosqlite.connect(db_path)
    try:
        await db.execute("ALTER TABLE enriched_listings ADD COLUMN images TEXT")
        await db.commit()
        print("✅ Added images column successfully")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("ℹ️ Column already exists")
        else:
            print(f"❌ Error: {e}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
