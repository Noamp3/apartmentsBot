# scripts/test_facebook_self_healing_real.py
"""Test self-healing on a real Facebook group using gemma-4-31b-it."""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from utils.logger import Loggers
from scrapers import FacebookScraper, AntiDetectionModule
from core.ai_engine import GeminiAIEngine

log = Loggers.scraper()

async def run_real_sabotage_test():
    print("=" * 60)
    print("REAL FACEBOOK SELF-HEALING SABOTAGE TEST")
    print("=" * 60)
    
    if not settings.facebook_groups:
        print("Error: No Facebook group URLs configured in .env")
        return
        
    group_url = settings.facebook_groups[0]
    print(f"Target Group URL: {group_url}")
    
    # Initialize dynamic Gemini engine with the specific model
    model_name = "gemma-4-31b-it"
    print(f"Initializing Gemini Engine with model: {model_name}")
    ai_engine = GeminiAIEngine(model=model_name)
    
    # Instantiate scraper
    anti_detection = AntiDetectionModule(
        min_delay=settings.MIN_DELAY_SECONDS,
        max_delay=settings.MAX_DELAY_SECONDS
    )
    
    scraper = FacebookScraper(
        group_urls=[group_url],
        anti_detection=anti_detection,
        ai_engine=ai_engine
    )
    
    # Set healer to write to a distinct testing cache file
    test_cache_path = "data/healed_selectors_real_test.json"
    scraper.healer.persist_path = test_cache_path
    
    # === SABOTAGE SELECTORS ===
    print("\n[Test Setup] Sabotaging selectors in test cache...")
    scraper.healer.healed_selectors["post_container"] = "div.sabotaged-nonexistent-post-container"
    scraper.healer.healed_selectors["post_url"] = "a.sabotaged-nonexistent-url-link"
    scraper.healer.healed_selectors["author"] = "span.sabotaged-nonexistent-author-name"
    scraper.healer.save_healed_selectors()
    
    # === OPTIMIZATION MONKEYPATCHES ===
    # 1. Scroll only 1 time to keep execution fast
    original_scroll = scraper._scroll_and_collect_posts
    async def fast_scroll(page, scroll_count=10):
        print(f"[Test Monitor] Overriding scroll count from {scroll_count} to 1 for rapid verification.")
        return await original_scroll(page, scroll_count=1)
    scraper._scroll_and_collect_posts = fast_scroll
    
    # 2. Preset failures to 2 so the very first extraction failure triggers healing instantly
    scraper._url_failures = 2
    scraper._author_failures = 2
    
    # Ensure logs folder exists
    os.makedirs("logs", exist_ok=True)
    
    # Clean up previous test screenshots if any
    for path in ["logs/healing_post_container.png", "logs/healing_attribute_post_url.png", "logs/healing_attribute_author.png"]:
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"Removed old screenshot: {path}")
            except Exception as e:
                print(f"Could not remove old screenshot {path}: {e}")
                
    print("\n[Test Start] Executing scraper run...")
    try:
        listings = await scraper.scrape()
        print("\n" + "=" * 60)
        print("SCRAPER RUN COMPLETED")
        print("=" * 60)
        print(f"Total parsed listings: {len(listings)}")
        
        # Verify cache has been healed
        scraper.healer.load_healed_selectors()
        healed_container = scraper.healer.healed_selectors.get("post_container")
        healed_url = scraper.healer.healed_selectors.get("post_url")
        healed_author = scraper.healer.healed_selectors.get("author")
        
        print("\n[Cache Verification]")
        print(f"  Healed Post Container: '{healed_container}'")
        print(f"  Healed Post URL Link:  '{healed_url}'")
        print(f"  Healed Author Element: '{healed_author}'")
        
        # Verify screenshots were taken
        print("\n[Screenshot Verification]")
        for path in ["logs/healing_post_container.png", "logs/healing_attribute_post_url.png", "logs/healing_attribute_author.png"]:
            exists = os.path.exists(path)
            status = "FOUND" if exists else "NOT FOUND"
            size = f"({os.path.getsize(path)} bytes)" if exists else ""
            print(f"  {path}: {status} {size}")
            
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_real_sabotage_test())
