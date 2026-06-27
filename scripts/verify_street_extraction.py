
import asyncio
import os
import sys

# Ensure UTF-8 output for Windows console
sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.listing import Listing
from core.ai_engine import ListingEnricher, GeminiAIEngine
from bot.formatters.listing_formatter import ListingFormatter
from config import settings

class MockAIEngine(GeminiAIEngine):
    """Mock AI engine to avoid real API calls and test parsing logic."""
    async def generate_content(self, prompt: str, max_retries: int = 3) -> str:
        # Simulate AI response with street extracted
        return """
        ```json
        {
            "listings": [
                {
                    "listing_num": 1,
                    "price": 5000,
                    "bedrooms": 2,
                    "location": "Tel Aviv",
                    "city": "Tel Aviv",
                    "neighborhood": "Florentin",
                    "street": "Herzl",
                    "has_broker": false,
                    "attributes": {},
                    "all_mentioned_areas": ["Tel Aviv", "Florentin"]
                }
            ]
        }
        ```
        """

async def run_verification():
    print("Verifying street extraction...")
    
    # 1. Setup
    ai_engine = MockAIEngine()
    enricher = ListingEnricher(ai_engine)
    
    # 2. Create raw listing
    raw_listing = Listing(
        id="test_1",
        source="facebook",
        url="http://test.com",
        title="דירה מהממת בפלורנטין",
        description="דירת 2 חדרים ברחוב הרצל, פלורנטין. 5000 שח.",
        location="Tel Aviv",
        raw_text="דירת 2 חדרים ברחוב הרצל, פלורנטין. 5000 שח."
    )
    
    # 3. Enrich
    print(f"Enriching listing: {raw_listing.title}")
    enriched_list = await enricher.enrich_listings([raw_listing])
    
    if not enriched_list:
        print("❌ Failed to enrich listing")
        return
        
    enriched = enriched_list[0]
    
    # 4. Verify data extraction
    print(f"Extracted Neighborhood: {enriched.extracted_neighborhood}")
    print(f"Extracted Street: {enriched.extracted_street}")
    print(f"Extracted City: {enriched.extracted_city}")
    
    if enriched.extracted_street == "Herzl":
        print("✅ Street extracted correctly")
    else:
        print(f"❌ Street extraction failed. Got: {enriched.extracted_street}")
        
    if enriched.extracted_neighborhood == "Florentin":
        print("✅ Neighborhood extracted correctly")
    else:
        print(f"❌ Neighborhood extraction failed. Got: {enriched.extracted_neighborhood}")
        
    if enriched.extracted_city == "Tel Aviv":
        print("✅ City extracted correctly")
    else:
        print(f"❌ City extraction failed. Got: {enriched.extracted_city}")
        
    # 5. Verify Formatting
    formatted_msg = ListingFormatter.format_listing(enriched)
    print("\nFormatted Notification Snippet:")
    print("-" * 40)
    print(formatted_msg)
    print("-" * 40)
    
    expected_loc_line = "📍 *מיקום:* Florentin, Herzl"
    if expected_loc_line in formatted_msg:
         print("✅ Notification format looks correct (contains neighborhood and street)")
    else:
         print("❌ Notification format missing expected location line")
         print(f"Expected to find: {expected_loc_line}")

if __name__ == "__main__":
    asyncio.run(run_verification())
