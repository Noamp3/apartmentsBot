"""Quick test of enhanced Yad2 scraper data extraction."""
import asyncio
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.disable(logging.CRITICAL)

from scrapers import Yad2Scraper


async def main():
    scraper = Yad2Scraper(
        city_id="5000",  # Tel Aviv
        max_listings=1,
        max_price=8000,
        min_rooms=3
    )
    
    listings = await scraper.scrape()
    if listings:
        print("=== ENHANCED RAW TEXT ===")
        print(listings[0].raw_text)
        print("\n=== IMAGES ===")
        print(listings[0].images[:3])


if __name__ == "__main__":
    asyncio.run(main())
