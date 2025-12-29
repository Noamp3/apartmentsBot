
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from scrapers.facebook_scraper import FacebookScraper
from models.listing import Listing

class TestFacebookEarlyTermination(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.group_urls = ["https://www.facebook.com/groups/test"]
        self.is_seen_mock = AsyncMock()
        self.scraper = FacebookScraper(
            group_urls=self.group_urls,
            is_seen_callback=self.is_seen_mock
        )
        # Mock browser stuff to avoid actual launches
        self.scraper._init_browser = AsyncMock()
        self.scraper._close_browser = AsyncMock()
        self.scraper._context = MagicMock()
        self.scraper._context.new_page = AsyncMock()

    @patch("scrapers.facebook_scraper.log")
    async def test_early_termination_all_seen(self, mock_log):
        # Mock page and post elements
        mock_page = AsyncMock()
        mock_post = AsyncMock()
        mock_post.bounding_box.return_value = {'height': 200, 'width': 500}
        mock_post.inner_text.side_effect = [f"Post text {i}" for i in range(10)]
        mock_page.query_selector_all.return_value = [mock_post] * 10
        
        # Mock extraction
        self.scraper._extract_post_data_immediate = AsyncMock()
        self.scraper._extract_post_data_immediate.side_effect = [
            {'text': f"Text {i}", 'url': f"url{i}"} for i in range(10)
        ]
        
        # Mock all posts as SEEN in DB
        self.is_seen_mock.return_value = True
        
        # We need to mock page.mouse.wheel and asyncio.sleep to avoid wait
        mock_page.mouse.wheel = AsyncMock()
        with patch("asyncio.sleep", return_value=None):
            result = await self.scraper._scroll_and_collect_posts(mock_page, scroll_count=5)
            
        # Should have stopped after 6 checks in the first scroll (since query_selector_all returns 10)
        # Actually it processes all 10 from the first query_selector_all call
        # But should return immediately when it hits the 6th seen post
        self.assertEqual(len(result), 6)
        self.is_seen_mock.assert_called()
        self.assertEqual(self.is_seen_mock.call_count, 6)
        mock_log.info.assert_any_call("Terminating search in group early: first 6 posts are already seen in database")

    @patch("scrapers.facebook_scraper.log")
    async def test_no_early_termination_if_new_found(self, mock_log):
        # Mock page and post elements
        mock_page = AsyncMock()
        mock_post = AsyncMock()
        mock_post.bounding_box.return_value = {'height': 200, 'width': 500}
        mock_post.inner_text.side_effect = [f"Unique text {i}" for i in range(20)]
        mock_page.query_selector_all.return_value = [mock_post]
        
        # Mock extraction
        self.scraper._extract_post_data_immediate = AsyncMock()
        self.scraper._extract_post_data_immediate.side_effect = [
            {'text': f"Unique {i}", 'url': f"url{i}"} for i in range(20)
        ]
        
        # One of the first 6 is NEW
        self.is_seen_mock.side_effect = [True, True, False, True, True, True, True]
        
        mock_page.mouse.wheel = AsyncMock()
        with patch("asyncio.sleep", return_value=None):
            # Run for 2 scrolls
            result = await self.scraper._scroll_and_collect_posts(mock_page, scroll_count=2)
            
        # Should NOT have terminated early because the 3rd one was NEW
        # total unique posts should be 2 (one per scroll)
        self.assertEqual(len(result), 2)
        # It only checks the first 6 NEW unique posts encountered
        # In this mock, it finds 1 per scroll. 
        # So after 2 scrolls, it has checked 2 posts.
        self.assertEqual(self.is_seen_mock.call_count, 2)
        
        # Verify log NOT called
        for call in mock_log.info.call_args_list:
            if "Terminating" in call[0][0]:
                self.fail("Early termination should not have occurred")

if __name__ == "__main__":
    unittest.main()
