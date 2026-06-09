import asyncio
import os
import json
import subprocess
import shutil
from playwright.async_api import async_playwright

# Remote OCI instance SSH configurations
REMOTE_SSH_KEY = "C:/Users/noamp/.ssh/oci_llm_a1_fixed"
REMOTE_USER = "ubuntu"
REMOTE_HOST = "129.159.139.195"
REMOTE_PATH = "/home/ubuntu/apartmentsBot/data/"


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
        
        # SCP Automatic Transfer
        scp_cmd = [
            "scp",
            "-i", REMOTE_SSH_KEY,
            "-o", "StrictHostKeyChecking=no",
            storage_state_path,
            cookies_path,
            f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH}"
        ]
        scp_cmd_str = f"scp -i {REMOTE_SSH_KEY} -o StrictHostKeyChecking=no {storage_state_path} {cookies_path} {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH}"
        
        print("\n====================================================")
        # Prompt user to copy files to remote
        loop = asyncio.get_event_loop()
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
                    # Run SCP synchronously using run_in_executor to avoid blocking the event loop
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
            print("\nSkipping automatic copy.")
            print("To copy manually, run:")
            print(scp_cmd_str)
        print("====================================================")

if __name__ == "__main__":
    asyncio.run(main())
