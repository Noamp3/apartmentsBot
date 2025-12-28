
import sys
import os

print(f"Python executable: {sys.executable}")
print(f"System path: {sys.path}")

try:
    import yad2_scraper
    print(f"Successfully imported yad2_scraper from: {yad2_scraper.__file__}")
except ImportError as e:
    print(f"Failed to import yad2_scraper: {e}")

# Check if the scripts/yad2_scraper folder exists
scripts_path = os.path.join(os.getcwd(), 'scripts', 'yad2_scraper')
print(f"scripts/yad2_scraper exists: {os.path.exists(scripts_path)}")
