import asyncio
import os
import sys
import json
import random
import platform
import subprocess
import shutil
from pathlib import Path
from playwright.async_api import async_playwright

# Add project root to sys.path to allow importing local modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from scrapers.anti_detection import AntiDetectionModule
from playwright_stealth import Stealth

# Remote OCI instance SSH configurations
REMOTE_SSH_KEY = "C:/Users/noamp/.ssh/oci_llm_a1_fixed"
REMOTE_USER = "ubuntu"
REMOTE_HOST = "129.159.139.195"
REMOTE_PATH = "/home/ubuntu/apartmentsBot/"


async def main():
    print("====================================================")
    print("   Stealth Facebook Manual Login for apartmentsBot  ")
    print("====================================================")
    print("This script will open a HEADED browser on your local machine.")
    print("It uses the exact same anti-detection, locale, viewport,")
    print("and device fingerprinting configs that the scraping bot uses.")
    print("Please log in to Facebook, complete any 2FA/security checks,")
    print("and wait until you are fully logged in and on the home page.")
    print("====================================================\n")

    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    storage_state_path = "data/fb_storage_state.json"
    cookies_path = "data/fb_cookies.json"

    # Set up anti-detection
    anti_detection = AntiDetectionModule(
        min_delay=settings.MIN_DELAY_SECONDS,
        max_delay=settings.MAX_DELAY_SECONDS
    )

    async with async_playwright() as p:
        # Determine viewport
        viewports = [
            {'width': 1920, 'height': 1080},
            {'width': 1600, 'height': 900},
            {'width': 1536, 'height': 864},
            {'width': 1440, 'height': 900},
        ]
        viewport = random.choice(viewports)
        print(f"Using viewport: {viewport['width']}x{viewport['height']}")

        # Determine browser channel (Edge on Windows/Mac, Chromium on ARM Linux)
        is_arm = platform.machine().lower() in ['arm64', 'aarch64']
        is_linux = platform.system().lower() == 'linux'
        browser_channel = "msedge" if not (is_arm and is_linux) else None

        print("Launching headed browser...")
        browser = None
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel=browser_channel,
                slow_mo=random.randint(30, 70),
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--disable-infobars',
                    f'--window-size={viewport["width"]},{viewport["height"]}',
                    '--disable-features=Translate',
                    '--lang=he-IL',
                    '--disable-extensions',
                    '--disable-component-extensions-with-background-pages',
                    '--disable-default-apps',
                    '--mute-audio',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-hang-monitor',
                    '--metrics-recording-only',
                    '--disable-sync',
                    '--disable-domain-reliability',
                ]
            )
        except Exception as e:
            print(f"Failed to launch browser with channel {browser_channel}: {e}")
            print("Attempting fallback to standard headless=False Chromium...")
            try:
                browser = await p.chromium.launch(headless=False)
            except Exception as ex:
                print(f"Error launching fallback browser: {ex}")
                print("Make sure playwright is installed (run: playwright install)")
                return

        # Prepare context options matching FacebookSessionManager
        context_opts = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "viewport": viewport,
            "locale": 'he-IL',
            "timezone_id": 'Asia/Jerusalem',
            "geolocation": {'longitude': 34.7818, 'latitude': 32.0853},
            "permissions": ['geolocation'],
            "screen": {'width': viewport['width'], 'height': viewport['height']},
            "device_scale_factor": 1.0,
            "has_touch": False,
            "is_mobile": False,
            "color_scheme": 'light',
        }

        # Load existing state if it exists
        if os.path.exists(storage_state_path):
            print("Loading existing fb_storage_state.json context state...")
            context_opts["storage_state"] = storage_state_path

        context = await browser.new_context(**context_opts)

        # Apply playwright-stealth
        stealth = Stealth(
            navigator_languages_override=('he-IL', 'he', 'en-US', 'en'),
            init_scripts_only=False,
        )
        await stealth.apply_stealth_async(context)

        # Add anti-detection scripts
        await context.add_init_script(anti_detection.add_stealth_scripts())

        # Inject additional fingerprint protection matching the bot
        await context.add_init_script("""
            const originalGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(type, attributes) {
                const context = originalGetContext.apply(this, arguments);
                if (type === '2d' && context) {
                    const originalFillText = context.fillText;
                    context.fillText = function() {
                        arguments[1] += Math.random() * 0.001;
                        return originalFillText.apply(this, arguments);
                    };
                }
                return context;
            };
            
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            Object.defineProperty(navigator, 'mediaDevices', {
                get: () => undefined
            });
            
            const origAudioContext = window.AudioContext || window.webkitAudioContext;
            if (origAudioContext) {
                window.AudioContext = function() {
                    const ctx = new origAudioContext();
                    const orig = ctx.createOscillator;
                    ctx.createOscillator = function() {
                        const osc = orig.apply(ctx, arguments);
                        osc.frequency.value += Math.random() * 0.0001;
                        return osc;
                    };
                    return ctx;
                };
            }
        """)

        # Add cookies if cookies file exists and storage state was not loaded
        if not context_opts.get("storage_state") and os.path.exists(cookies_path):
            try:
                print("Loading existing fb_cookies.json cookies...")
                with open(cookies_path, 'r') as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
            except Exception as e:
                print(f"Could not load cookies: {e}")

        page = await context.new_page()

        print("Navigating to Facebook login page...")
        await page.goto("https://www.facebook.com/login", wait_until="load")

        print("\n--> PLEASE LOG IN NOW in the opened browser window.")
        print("Complete any security checks / Arkose Labs CAPTCHAs / 2FA.")
        print("Once you are fully logged in and can see your Facebook Feed/Home page,")
        print("press ENTER in this terminal to save the cookies and session state...")

        # Wait for terminal input
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)

        # Save storage state and cookies
        print("\nSaving session state...")
        await context.storage_state(path=storage_state_path)
        print(f"Saved browser state to: {storage_state_path}")

        cookies = await context.cookies()
        with open(cookies_path, 'w') as f:
            json.dump(cookies, f)
        print(f"Saved cookies to: {cookies_path}")

        print("\nSuccess! Closing the browser.")
        await browser.close()

        # SCP Automatic Transfer Command
        scp_cmd = [
            "scp",
            "-i", REMOTE_SSH_KEY,
            "-o", "StrictHostKeyChecking=no",
            storage_state_path,
            cookies_path,
            f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH}data/"
        ]
        scp_cmd_str = f"scp -i {REMOTE_SSH_KEY} -o StrictHostKeyChecking=no {storage_state_path} {cookies_path} {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH}data/"

        print("\n====================================================")
        choice = await loop.run_in_executor(
            None,
            lambda: input("Do you want to automatically copy the saved session state and cookies to the remote server? (Y/n): ").strip().lower()
        )

        if choice in ("", "y", "yes"):
            if not shutil.which("scp"):
                print("\nError: 'scp' command line utility not found in PATH.")
                print("Please copy the files manually using the command below:")
                print(scp_cmd_str)
            else:
                print(f"\nExecuting: {scp_cmd_str}")
                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(scp_cmd, shell=True if os.name == 'nt' else False, capture_output=True, text=True)
                    )
                    if result.returncode == 0:
                        print("Successfully copied session state and cookies to the remote server!")
                    else:
                        print(f"SCP transfer failed with exit code {result.returncode}.")
                        print(f"Error output:\n{result.stderr}")
                        print("\nPlease copy the files manually using the command below:")
                        print(scp_cmd_str)
                except Exception as e:
                    print(f"Failed to execute SCP: {e}")
                    print("\nPlease copy the files manually using the command below:")
                    print(scp_cmd_str)
        else:
            print("\nSkipping automatic credentials copy.")
            print("To copy manually, run:")
            print(scp_cmd_str)
        print("====================================================")

if __name__ == "__main__":
    asyncio.run(main())
