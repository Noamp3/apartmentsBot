import sqlite3
import json

conn = sqlite3.connect('/home/ubuntu/apartmentsBot/apartment_bot.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Search by Goni, Shoam, or Rabin Square (כיכר רבין)
cur.execute(
    "SELECT title, description, location, extracted_location, extracted_neighborhood, area_matches "
    "FROM enriched_listings "
    "WHERE raw_text LIKE ? OR raw_text LIKE ? OR raw_text LIKE ? "
    "ORDER BY enriched_at DESC LIMIT 10;",
    ('%Shoam%', '%שוהם%', '%רבין%')
)
rows = cur.fetchall()

print(f"Found {len(rows)} listings:")
for r in rows:
    print(json.dumps(dict(r), ensure_ascii=False, indent=2))
