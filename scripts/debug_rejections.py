
import asyncio
import sys
import os
import json

# Add project root to path
sys.path.append(os.getcwd())

from database import get_db

async def main():
    db = await get_db()
    
    # Get recent rejections
    rows = await db.fetch_all("""
        SELECT listing_id, listing_price, listing_location, failed_rules, reasons, created_at 
        FROM rejection_logs 
        ORDER BY id DESC LIMIT 10
    """)
    
    print("\n=== RECENT REJECTIONS ===")
    for row in rows:
        print(f"Listing: {row['listing_id']}")
        print(f"Price: {row['listing_price']}")
        print(f"Location: {row['listing_location']}")
        print(f"Time: {row['created_at']}")
        
        try:
            reasons = json.loads(row['reasons'])
            print("Reasons:")
            for r in reasons:
                print(f"  - {r}")
        except:
            print(f"Reasons (raw): {row['reasons']}")
            
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
