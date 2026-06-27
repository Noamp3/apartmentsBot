import sqlite3
import json

def get_listing():
    conn = sqlite3.connect("apartment_bot_remote.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM enriched_listings WHERE raw_text LIKE '%צביקה בירן%'")
    rows = c.fetchall()
    
    data = [dict(r) for r in rows]
    with open("scratch/zvi_detail.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Extracted {len(data)} listings.")

if __name__ == "__main__":
    get_listing()
