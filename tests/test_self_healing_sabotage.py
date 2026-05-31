# tests/test_self_healing_sabotage.py
"""Real integration test verifying selector self-healing on a sabotaged DOM."""

import os
import json
import pytest
from playwright.async_api import async_playwright
from scrapers.facebook_scraper import FacebookScraper
from core.ai_engine import create_ai_engine
from config import settings

# Apply skip if AI API credentials are not set in the environment
pytestmark = pytest.mark.skipif(
    not settings.active_api_key,
    reason="Skipping real LLM test: no active API key configured in environment."
)


@pytest.mark.asyncio
async def test_self_healing_sabotage_real_llm(tmp_path):
    """Real integration test for LLM-based selector self-healing.

    This test:
    1. Spins up a headless local browser page using Playwright.
    2. Injects a mock layout representing a modified Facebook structure (with class names different from defaults).
    3. Sabotages standard selectors.
    4. Calls the real configured LLM to heal the selectors.
    5. Verifies that healed selectors are correctly parsed, verified, saved, and successfully extract the listing.
    """
    temp_json = str(tmp_path / "healed_selectors.json")

    # Static sabotaged DOM layout representing an updated Facebook feed
    mock_dom_html = """
    <html>
      <body>
        <div class="custom-feed-layout">
          <!-- Sabotaged Post Container (no div[role='article'] wrapper) -->
          <div class="fb-card-wrapper" data-testid="fb-post">
             <div class="post-header-card">
                <span class="user-profile-name">Johnathan Doe</span>
                <!-- Sabotaged Timestamp / URL structure (no typical links) -->
                <a class="permalink-timestamp-link" href="https://www.facebook.com/groups/test/permalink/123456/">
                   <span class="date-label">2h</span>
                </a>
             </div>
             <!-- Sabotaged text container -->
             <div class="post-body-text">
                דירה מהממת להשכרה בתל אביב, 3 חדרים, 6000 ש"ח ברחוב דיזנגוף! ללא תיווך!
             </div>
          </div>
        </div>
      </body>
    </html>
    """

    async with async_playwright() as p:
        # Launch browser headlessly for fast verification
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Set the sabotaged page content
        await page.set_content(mock_dom_html)

        # Instantiate active LLM Engine
        ai_engine = create_ai_engine()

        # Create Facebook scraper with sabotaged healer configuration
        # Pass healer override persist path
        scraper = FacebookScraper(
            group_urls=["https://www.facebook.com/groups/test"],
            ai_engine=ai_engine,
            cookies_file=str(tmp_path / "fb_cookies.json"),
            storage_state_file=str(tmp_path / "fb_storage.json")
        )

        # Update scraper healer to write to our temporary json path
        scraper.healer.persist_path = temp_json

        # === STEP 1: SABOTAGE OVERRIDES ===
        # We inject sabotaged selectors to cache that will fail
        scraper.healer.healed_selectors["post_container"] = "div[role='article']"  # Doesn't exist in our DOM
        scraper.healer.healed_selectors["post_url"] = "a[href*='/posts/']"         # Doesn't exist in our DOM
        scraper.healer.healed_selectors["author"] = "strong"                      # Doesn't exist in our DOM
        scraper.healer.save_healed_selectors()

        # Check initial sabotaged selectors are active
        assert scraper.healer.get_selector("post_container") == "div[role='article']"

        # === STEP 2: TRIGGER CONTAINER HEALING ===
        print("\n[Sabotage Test] Activating post container self-healing...")
        healed_container = await scraper.healer.heal_post_container(page, "div[role='article']")

        # Verify LLM successfully synthesized a working container selector from the HTML
        assert healed_container is not None
        assert "fb-card-wrapper" in healed_container or "fb-post" in healed_container

        # The healer should have written the healed container selector to our cache
        assert scraper.healer.get_selector("post_container") == healed_container

        # === STEP 3: TRIGGER ATTRIBUTE HEALING ===
        # We query the healed post element
        post_element = await page.query_selector(healed_container)
        assert post_element is not None

        print("[Sabotage Test] Activating attribute URL self-healing...")
        healed_url = await scraper.healer.heal_attribute(page, post_element, "post_url", "a[href*='/posts/']")

        # Verify LLM successfully repaired the post URL selector
        assert healed_url is not None
        assert "permalink-timestamp-link" in healed_url or "permalink" in healed_url or "fb-post" in healed_url
        assert scraper.healer.get_selector("post_url") == healed_url

        print("[Sabotage Test] Activating attribute Author self-healing...")
        healed_author = await scraper.healer.heal_attribute(page, post_element, "author", "strong")

        # Verify LLM successfully repaired the Author selector
        assert healed_author is not None
        assert "user-profile-name" in healed_author or "profile" in healed_author or "fb-post" in healed_author
        assert scraper.healer.get_selector("author") == healed_author

        # === STEP 4: VERIFY SCARPER EXTRACTS SUCCESSFULLY USING HEALED SCHEMA ===
        print("[Sabotage Test] Running immediate extraction with healed schema...")

        # Now extraction will work at native speed using healed selectors!
        # 1. Extract URL using dynamic healed selector
        url_link = await post_element.query_selector(scraper.healer.get_selector("post_url"))
        extracted_url = await url_link.get_attribute("href") if url_link else ""
        assert "123456" in extracted_url

        # 2. Extract Author using dynamic healed selector
        author_element = await post_element.query_selector(scraper.healer.get_selector("author"))
        extracted_author = await author_element.inner_text() if author_element else ""
        assert "Johnathan" in extracted_author

        print(f"SUCCESS: Healed URL: '{extracted_url}', Healed Author: '{extracted_author}'")

        await browser.close()
