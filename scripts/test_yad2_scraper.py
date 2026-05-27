# scripts/test_yad2_scraper.py
"""Test script for Yad2 scraper (both HTTP and Playwright).

Usage:
    python scripts/test_yad2_scraper.py
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import settings
from scrapers import Yad2Scraper, AntiDetectionModule
from scrapers.yad2_playwright_scraper import Yad2PlaywrightScraper
from utils.logger import LoggerFactory, Loggers

# Initialize logging
LoggerFactory.initialize(debug=True)
log = Loggers.scraper()


async def test_http_scraper():
    """Test the HTTP-based Yad2 scraper."""
    log.info("=" * 60)
    log.info("Testing HTTP-based Yad2 scraper")
    log.info("=" * 60)
    
    anti_detection = AntiDetectionModule()
    scraper = Yad2Scraper(
        anti_detection=anti_detection,
        max_pages=1,  # Just test one page
        max_listings=10
    )
    
    listings = await scraper.scrape()
    
    log.info(f"HTTP scraper returned {len(listings)} listings")
    
    if listings:
        log.info("Sample listing:")
        sample = listings[0]
        log.info(f"  Title: {sample.title}")
        log.info(f"  Location: {sample.location}")
        log.info(f"  Price: {sample.price}")
        log.info(f"  URL: {sample.url}")
    
    return listings


async def test_playwright_scraper():
    """Test the Playwright-based Yad2 scraper."""
    log.info("=" * 60)
    log.info("Testing Playwright-based Yad2 scraper")
    log.info("=" * 60)
    
    anti_detection = AntiDetectionModule()
    scraper = Yad2PlaywrightScraper(
        anti_detection=anti_detection,
        max_pages=1,  # Just test one page
        max_listings=10
    )
    
    listings = await scraper.scrape()
    
    log.info(f"Playwright scraper returned {len(listings)} listings")
    
    if listings:
        log.info("Sample listing:")
        sample = listings[0]
        log.info(f"  Title: {sample.title}")
        log.info(f"  Location: {sample.location}")
        log.info(f"  Price: {sample.price}")
        log.info(f"  URL: {sample.url}")
    
    return listings


async def main():
    """Main test function."""
    print("🏠 Testing Yad2 Scrapers")
    print("=" * 60)
    
    # Test based on configuration
    if settings.YAD2_USE_PLAYWRIGHT:
        print(f"Configuration: YAD2_USE_PLAYWRIGHT = {settings.YAD2_USE_PLAYWRIGHT}")
        print("Testing Playwright scraper (current configuration)...")
        listings = await test_playwright_scraper()
    else:
        print(f"Configuration: YAD2_USE_PLAYWRIGHT = {settings.YAD2_USE_PLAYWRIGHT}")
        print("Testing HTTP scraper (current configuration)...")
        listings = await test_http_scraper()
    
    print("=" * 60)
    if listings:
        print(f"✅ Success! Retrieved {len(listings)} listings")
    else:
        print("⚠️ Warning: No listings retrieved. Check logs for details.")
    
    print("\nTo test the other scraper, change YAD2_USE_PLAYWRIGHT in .env file")


if __name__ == "__main__":
    asyncio.run(main())
