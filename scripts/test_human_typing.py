import asyncio
from playwright.async_api import async_playwright
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.anti_detection import AntiDetectionModule

async def test_human_typing():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Go to a page with an input field
        await page.goto("https://www.google.com")
        
        anti_detection = AntiDetectionModule()
        
        # Find search box
        search_box = await page.wait_for_selector('textarea[name="q"], input[name="q"]')
        
        print("Starting human-like typing...")
        await anti_detection.human_like_typing(search_box, "Facebook scraping in 2025 with Playwright")
        print("Typing complete.")
        
        await asyncio.sleep(5)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_human_typing())
