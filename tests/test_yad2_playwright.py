# tests/test_yad2_playwright.py
"""Integration tests for Playwright-based Yad2 scraper."""

import pytest
import asyncio
from scrapers.yad2_playwright_scraper import Yad2PlaywrightScraper
from scrapers.anti_detection import AntiDetectionModule


@pytest.mark.asyncio
class TestYad2PlaywrightScraper:
    """Test Playwright-based Yad2 scraper initialization and basic functionality."""
    
    async def test_scraper_initialization(self):
        """Should initialize scraper successfully."""
        scraper = Yad2PlaywrightScraper(
            max_listings=5,
            max_pages=1
        )
        
        assert scraper.source_name == "yad2"
        assert scraper.max_listings == 5
        assert scraper.max_pages == 1
        assert scraper.anti_detection is not None
    
    async def test_build_url_params(self):
        """Should build correct URL parameters."""
        scraper = Yad2PlaywrightScraper(
            city_id="5000",
            min_price=3000,
            max_price=8000,
            min_rooms=2,
            max_rooms=4
        )
        
        params = scraper._build_url_params(page=1)
        
        assert params["page"] == 1
        assert params["city"] == "5000"
        assert params["minPrice"] == 3000
        assert params["maxPrice"] == 8000
        assert params["minRooms"] == 2
        assert params["maxRooms"] == 4
        assert params["topArea"] == 2
        assert params["area"] == 1
    
    async def test_valid_listing_check(self):
        """Should correctly validate listing items."""
        scraper = Yad2PlaywrightScraper()
        
        # Valid listing
        valid_item = {
            "token": "abc123",
            "adType": "private"
        }
        assert scraper._is_valid_listing(valid_item) is True
        
        # Missing token
        invalid_item_1 = {
            "adType": "private"
        }
        assert scraper._is_valid_listing(invalid_item_1) is False
        
        # Banner ad
        invalid_item_2 = {
            "token": "abc123",
            "adType": "banner"
        }
        assert scraper._is_valid_listing(invalid_item_2) is False
