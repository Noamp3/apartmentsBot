# tests/test_yad2_captcha_detection.py
"""Unit tests for Yad2 CAPTCHA detection."""

import pytest
from scrapers.yad2_scraper import Yad2Scraper


class TestYad2CaptchaDetection:
    """Test CAPTCHA detection in HTTP-based Yad2 scraper."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.scraper = Yad2Scraper()
    
    def test_detect_cloudflare_challenge(self):
        """Should detect Cloudflare challenge page."""
        html = """
        <html>
        <head><title>Just a moment...</title></head>
        <body>
            <div class="cf-challenge-running">
                <p>Checking your browser before accessing example.com</p>
            </div>
        </body>
        </html>
        """
        assert self.scraper._detect_captcha(html, 200) is True
    
    def test_detect_challenge_form(self):
        """Should detect challenge form."""
        html = """
        <html>
        <body>
            <form id="challenge-form" action="/cdn-cgi/challenge">
                <input type="submit" value="Continue" />
            </form>
        </body>
        </html>
        """
        assert self.scraper._detect_captcha(html, 200) is True
    
    def test_detect_403_status(self):
        """Should detect 403 forbidden status as potential CAPTCHA."""
        html = "<html><body>Access Denied</body></html>"
        assert self.scraper._detect_captcha(html, 403) is True
    
    def test_detect_429_status(self):
        """Should detect 429 rate limit status as potential CAPTCHA."""
        html = "<html><body>Too Many Requests</body></html>"
        assert self.scraper._detect_captcha(html, 429) is True
    
    def test_no_captcha_normal_page(self):
        """Should not detect CAPTCHA on normal Yad2 page."""
        html = """
        <html>
        <head><title>דירות להשכרה - יד2</title></head>
        <body>
            <script id="__NEXT_DATA__" type="application/json">
                {"props": {"pageProps": {"dehydratedState": {}}}}
            </script>
        </body>
        </html>
        """
        assert self.scraper._detect_captcha(html, 200) is False
    
    def test_no_captcha_200_status(self):
        """Should not detect CAPTCHA with 200 status and normal content."""
        html = "<html><body><h1>Welcome to Yad2</h1>" + "x" * 10000 + "</body></html>"
        assert self.scraper._detect_captcha(html, 200) is False
