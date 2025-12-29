# scripts/test_scraper.py
"""Standalone script to test scraping and saving to database."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from utils.logger import LoggerFactory
from scrapers import FacebookScraper, Yad2Scraper, AntiDetectionModule
from database.connection import get_db
from database.repositories import SeenListingsRepository


async def test_yad2_scraper(save_to_db: bool = False):
    """Test Yad2 scraper."""
    print("\n" + "="*50)
    print("🔍 Testing Yad2 Scraper")
    print("="*50)
    
    scraper = Yad2Scraper(
        city_id="5000",  # Tel Aviv
        max_listings=20,
        max_price=8000,
        min_rooms=3,
        max_rooms=5
    )
    
    try:
        listings = await scraper.scrape()
        print(f"\n✅ Found {len(listings)} listings from Yad2")
        
        for i, listing in enumerate(listings[:5], 1):
            print(f"\n--- Listing {i} ---")
            print(f"  ID: {listing.id}")
            print(f"  Title: {listing.title[:50]}...")
            print(f"  Price: {listing.price:,} ₪" if listing.price else "  Price: N/A")
            print(f"  Bedrooms: {listing.bedrooms}" if listing.bedrooms else "  Bedrooms: N/A")
            print(f"  Location: {listing.location}")
            print(f"  URL: {listing.url}")
        
        if len(listings) > 5:
            print(f"\n... and {len(listings) - 5} more")
        
        # Save to database if requested
        if save_to_db and listings:
            await save_listings_to_db(listings, "Yad2")
            
        return listings
        
    except Exception as e:
        print(f"\n❌ Yad2 scraper failed: {e}")
        import traceback
        traceback.print_exc()
        return []


async def test_facebook_scraper(save_to_db: bool = False):
    """Test Facebook scraper."""
    print("\n" + "="*50)
    print("🔍 Testing Facebook Scraper")
    print("="*50)
    
    if not settings.facebook_groups:
        print("⚠️ No Facebook group URLs configured in .env")
        print("   Set FACEBOOK_GROUP_URLS to test Facebook scraping")
        return []
    
    anti_detection = AntiDetectionModule(
        min_delay=settings.MIN_DELAY_SECONDS,
        max_delay=settings.MAX_DELAY_SECONDS
    )
    
    scraper = FacebookScraper(
        group_urls=settings.facebook_groups,
        anti_detection=anti_detection
    )
    
    try:
        listings = await scraper.scrape()
        print(f"\n✅ Found {len(listings)} listings from Facebook")
        
        for i, listing in enumerate(listings[:10], 1): # Show more for verification
            print(f"\n--- Listing {i} ---")
            print(f"  ID: {listing.id}")
            print(f"  Title: {listing.title[:50]}...")
            print(f"  Price: {listing.price:,} ₪" if listing.price else "  Price: N/A")
            print(f"  Bedrooms: {listing.bedrooms}" if listing.bedrooms else "  Bedrooms: N/A")
            print(f"  Location: {listing.location or 'N/A'}")
            print(f"  Phone: {listing.phone or 'N/A'}")
            print(f"  Posted: {listing.posted_at.strftime('%Y-%m-%d %H:%M') if listing.posted_at else 'N/A'}")
            print(f"  URL: {listing.url}")
            
            print(f"  Full Text:\n{'-'*20}\n{listing.description[:200]}...\n{'-'*20}")
        
        # Save to database if requested
        if save_to_db and listings:
            await save_listings_to_db(listings, "Facebook")
            
        return listings
        
    except Exception as e:
        print(f"\n❌ Facebook scraper failed: {e}")
        return []


async def save_listings_to_db(listings, source_name: str):
    """Save listings to database (both seen_listings and enriched_listings)."""
    from models.listing import EnrichedListing
    from database.repositories import ListingRepository
    
    print(f"\n💾 Saving {len(listings)} {source_name} listings to database...")
    
    try:
        db = await get_db()
        seen_repo = SeenListingsRepository(db)
        listing_repo = ListingRepository(db)
        
        # Filter for new listings only
        new_listings = await seen_repo.filter_new(listings)
        
        if not new_listings:
            print(f"   ℹ️ All {len(listings)} listings already in database")
            return
        
        # Mark new listings as seen (for deduplication)
        await seen_repo.mark_many_seen(new_listings)
        print(f"   ✅ Marked {len(new_listings)} as seen (dedup)")
        
        # Save full listing data to enriched_listings
        # (Basic enrichment from scraped data - no AI yet)
        saved_count = 0
        for listing in new_listings:
            # Create basic EnrichedListing from scraped data
            enriched = EnrichedListing(
                listing=listing,
                extracted_price=listing.price,
                extracted_bedrooms=listing.bedrooms,
                extracted_location=listing.location,
                extracted_neighborhood="",  # Would be AI-extracted
                has_broker_fee=False,  # Would be AI-detected
                attributes={},
                area_matches={},
                bordering_areas={},
            )
            await listing_repo.save_enriched(enriched)
            saved_count += 1
        
        print(f"   ✅ Saved {saved_count} enriched listings (with full data)")
        print(f"   ℹ️ {len(listings) - len(new_listings)} were already seen")
        
        # Show database stats
        all_seen = await seen_repo.get_seen_ids()
        print(f"   📊 Total in seen_listings: {len(all_seen)}")
        
    except Exception as e:
        print(f"   ❌ Database save failed: {e}")
        import traceback
        traceback.print_exc()


async def print_database_contents():
    """Print entries from enriched_listings table (full listing data)."""
    print("\n" + "="*60)
    print("🗄️ Database Contents (enriched_listings - full data)")
    print("="*60)
    
    try:
        db = await get_db()
        
        # Fetch enriched listings with full data
        rows = await db.fetch_all(
            """
            SELECT listing_id, source, url, title, location, 
                   extracted_price, extracted_bedrooms, scraped_at
            FROM enriched_listings 
            ORDER BY enriched_at DESC
            LIMIT 15
            """
        )
        
        if not rows:
            print("  (empty - no enriched listings yet)")
            return
        
        # Get total count
        count_row = await db.fetch_one("SELECT COUNT(*) as cnt FROM enriched_listings")
        total_count = count_row["cnt"] if count_row else len(rows)
        
        print(f"  Total enriched listings: {total_count}\n")
        
        for i, row in enumerate(rows, 1):
            listing_id = row["listing_id"][:12]
            source = row["source"]
            title = row["title"][:40] if row["title"] else "N/A"
            location = row["location"][:35] if row["location"] else "N/A"
            price = f"{row['extracted_price']:,}₪" if row["extracted_price"] else "N/A"
            bedrooms = row["extracted_bedrooms"] or "N/A"
            
            print(f"  {i:2}. [{source}] {title}...")
            print(f"      📍 Location: {location}")
            print(f"      💰 Price: {price}  |  🛏️ Bedrooms: {bedrooms}")
            print(f"      🔗 {row['url']}")
            print()
            
            # Limit display
            if i >= 10:
                remaining = total_count - 10
                if remaining > 0:
                    print(f"  ... and {remaining} more listings in database")
                break
                
    except Exception as e:
        print(f"  ❌ Failed to read database: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Run scraper tests with optional database saving."""
    LoggerFactory.initialize(debug=True)
    
    # Check command line args for --save flag
    save_to_db = "--save" in sys.argv
    
    print("\n🏠 Apartment Bot - Scraper Test")
    print("================================")
    if save_to_db:
        print("💾 Database saving: ENABLED")
    else:
        print("💾 Database saving: DISABLED (use --save to enable)")
    print()
    
    # Test Yad2
    #yad2_listings = await test_yad2_scraper(save_to_db)
    yad2_listings = []
    
    # Test Facebook (if configured)
    fb_listings = await test_facebook_scraper(save_to_db)
    
    # Summary
    print("\n" + "="*50)
    print("📊 Summary")
    print("="*50)
    print(f"  Yad2 listings: {len(yad2_listings)} (SKIPPED)")
    print(f"  Facebook listings: {len(fb_listings)}")
    print(f"  Total: {len(yad2_listings) + len(fb_listings)}")
    
    # Print database contents if saving was enabled
    if save_to_db:
        await print_database_contents()


if __name__ == "__main__":
    print("Starting scraper test...")
    asyncio.run(main())
