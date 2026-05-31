import asyncio
import os
import json
from playwright.async_api import async_playwright

async def main():
    print("====================================================")
    print("   Facebook Manual Login helper for apartmentsBot   ")
    print("====================================================")
    print("This script will open a HEADED browser on your local machine.")
    print("Please log in to Facebook, complete any 2FA/security checks,")
    print("and wait until you are fully logged in and on the home page.")
    print("====================================================\n")

    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)

    async with async_playwright() as p:
        # Launch headed chromium browser
        print("Launching headed browser...")
        browser = None
        # Try msedge first (highly likely on Windows), fall back to chromium
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel="msedge"
            )
        except Exception:
            try:
                browser = await p.chromium.launch(headless=False)
            except Exception as e:
                print(f"Error launching browser: {e}")
                print("Make sure playwright is installed and browsers are installed (run: playwright install)")
                return
            
        context = await browser.new_context()
        page = await context.new_page()
        
        print("Navigating to Facebook login page...")
        await page.goto("https://www.facebook.com/login", wait_until="load")
        
        print("\n--> PLEASE LOG IN NOW in the opened browser window.")
        print("Complete any security checks / Arkose Labs CAPTCHAs / 2FA.")
        print("Once you are fully logged in and can see your Facebook Feed/Home page,")
        print("press ENTER in this terminal to save the cookies and session state...")
        
        # Wait for terminal input using executor to avoid blocking the asyncio event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)
        
        # Save storage state and cookies
        print("\nSaving session state...")
        storage_state_path = "data/fb_storage_state.json"
        cookies_path = "data/fb_cookies.json"
        
        await context.storage_state(path=storage_state_path)
        print(f"Saved browser state to: {storage_state_path}")
        
        cookies = await context.cookies()
        with open(cookies_path, 'w') as f:
            json.dump(cookies, f)
        print(f"Saved cookies to: {cookies_path}")
        
        print("\nSuccess! Closing the browser.")
        await browser.close()
        
        print("\n====================================================")
        print("Next step: Copy these files to your remote server using this command:")
        print("scp -i C:/Users/noamp/.ssh/oci_llm_a1_fixed data/fb_storage_state.json data/fb_cookies.json ubuntu@129.159.139.195:/home/ubuntu/apartmentsBot/data/")
        print("====================================================")

if __name__ == "__main__":
    asyncio.run(main())
