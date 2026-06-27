import sqlite3
import json

def main():
    conn = sqlite3.connect("/home/ubuntu/apartmentsBot/apartment_bot.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM enriched_listings WHERE raw_text LIKE '%צביקה בירן%'")
    rows = c.fetchall()
    data = [dict(r) for r in rows]
    with open("/home/ubuntu/apartmentsBot/scratch_zvi.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Successfully extracted {len(data)} listings.")

if __name__ == "__main__":
    main()
