
import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from database import get_db
from database.repositories import RuleRepository
from models.search_rule import RuleType

async def main():
    db = await get_db()
    repo = RuleRepository(db)
    
    # Get all rules
    rows = await db.fetch_all("SELECT * FROM search_rules ORDER BY id DESC LIMIT 20")
    
    print("\n=== RECENT RULES ===")
    for row in rows:
        print(f"ID: {row['id']}")
        print(f"User ID: {row['user_id']}")
        print(f"Type: {row['rule_type']}")
        print(f"Value: {row['value'][:200]}") # Truncate value if too long
        print(f"Original Text: {row['original_text']}")
        print(f"Active: {row['is_active']}")
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
