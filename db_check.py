import os
import re

log_path = '/home/ubuntu/apartmentsBot/logs/app.log'

print("=== Analyzing Facebook scraper runs in current app.log (June 6) ===")

recent_runs = []
try:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_no, line in enumerate(f, 1):
            if "2026-06-06" in line:
                if "facebook" in line.lower() or "fb_login" in line:
                    if "Scraping Facebook group" in line or "Facebook scrape complete" in line or "Failed to scrape" in line or "login is required" in line or "blocked" in line:
                        recent_runs.append(f"Line {line_no}: {line.strip()}")
except Exception as e:
    print(f"Error reading app.log: {e}")

print(f"Found {len(recent_runs)} Facebook scraper events today. Showing them all:")
for event in recent_runs:
    print(event)
