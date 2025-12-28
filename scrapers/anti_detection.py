# scrapers/anti_detection.py
"""Anti-detection utilities for web scraping."""

import random
import asyncio
from typing import Optional

from utils.logger import Loggers

log = Loggers.scraper()


# Real browser user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


class AntiDetectionModule:
    """Implements techniques to avoid bot detection."""
    
    def __init__(
        self, 
        min_delay: float = 1.0, 
        max_delay: float = 5.0
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.user_agents = USER_AGENTS
    
    def get_random_user_agent(self) -> str:
        """Get a random real browser user agent."""
        return random.choice(self.user_agents)
    
    async def human_like_delay(
        self, 
        min_sec: float = None, 
        max_sec: float = None
    ):
        """Random delay to mimic human behavior."""
        min_sec = min_sec or self.min_delay
        max_sec = max_sec or self.max_delay
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)
    
    def get_browser_headers(self) -> dict:
        """Get headers that look like a real browser."""
        return {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
    
    async def random_scroll_behavior(self, page) -> None:
        """Perform random scrolling like a human would (Playwright)."""
        try:
            # Scroll down randomly
            for _ in range(random.randint(2, 5)):
                scroll_amount = random.randint(100, 500)
                await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                await self.human_like_delay(0.3, 1.0)
            
            # Sometimes scroll back up a bit
            if random.random() > 0.7:
                scroll_up = random.randint(50, 200)
                await page.evaluate(f"window.scrollBy(0, -{scroll_up})")
                await self.human_like_delay(0.2, 0.5)
        except Exception as e:
            log.warning(f"Scroll behavior failed: {e}")
    
    async def random_mouse_movement(self, page) -> None:
        """Simulate random mouse movements (Playwright)."""
        try:
            # Move mouse to random positions
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                await page.mouse.move(x, y)
                await self.human_like_delay(0.1, 0.3)
        except Exception as e:
            log.warning(f"Mouse movement failed: {e}")
    
    def add_stealth_scripts(self) -> str:
        """JavaScript to inject for comprehensive stealth mode (2024 best practices).
        
        Based on: puppeteer-extra-plugin-stealth techniques
        """
        return """
        // ===== Core Detection Evasion =====
        
        // 1. Override webdriver property (CRITICAL - main detection flag)
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        delete navigator.__proto__.webdriver;
        
        // 2. Override plugins to look like real browser
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const plugins = [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin' }
                ];
                plugins.item = (i) => plugins[i];
                plugins.namedItem = (name) => plugins.find(p => p.name === name);
                plugins.refresh = () => {};
                return plugins;
            }
        });
        
        // 3. Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['he-IL', 'he', 'en-US', 'en']
        });
        
        // 4. Override permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
        );
        
        // 5. Chrome-specific overrides
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
        
        // ===== Advanced Fingerprinting Evasion =====
        
        // 6. WebGL Vendor/Renderer spoofing
        const getParameterProto = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return 'Intel Inc.';  // UNMASKED_VENDOR_WEBGL
            if (param === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
            return getParameterProto.call(this, param);
        };
        
        // 7. Canvas fingerprinting noise
        const toDataURLProto = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (type === 'image/png' && this.width > 16 && this.height > 16) {
                const ctx = this.getContext('2d');
                const imageData = ctx.getImageData(0, 0, this.width, this.height);
                for (let i = 0; i < imageData.data.length; i += 4) {
                    imageData.data[i] ^= (Math.random() * 2) & 1;  // Tiny noise
                }
                ctx.putImageData(imageData, 0, 0);
            }
            return toDataURLProto.apply(this, arguments);
        };
        
        // 8. Disable automation-related properties
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: () => 5  // Mobile device simulation
        });
        
        // 9. Override connection info to look real
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            })
        });
        
        // 10. Hide Playwright/automation traces
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Linux armv8l'  // Mobile platform
        });
        
        // 11. Battery API (if available)
        if (navigator.getBattery) {
            navigator.getBattery = () => Promise.resolve({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 0.85
            });
        }
        
        // 12. Device memory spoof
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 4
        });
        
        // 13. Hardware concurrency (CPU cores)
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 4
        });
        
        // 14. Remove Playwright-specific properties
        delete window.__playwright;
        delete window.__pw_manual;
        delete window.__PW_inspect;
        
        console.log('Stealth mode activated');
        """
    
    def get_proxy_config(self, proxy_url: str = None) -> dict:
        """Get proxy configuration for Playwright.
        
        Args:
            proxy_url: Format: protocol://user:pass@host:port
                       Example: http://user:pass@proxy.example.com:8080
        
        Returns:
            Dict for Playwright's proxy option
        """
        if not proxy_url:
            return None
        
        return {"server": proxy_url}

