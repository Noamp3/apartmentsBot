import sqlite3
import glob
import json
import os

def search_dbs():
    search_term = "צביקה"
    out = open("scratch/search_results.txt", "w", encoding="utf-8")
    for db_file in glob.glob("*.db"):

        out.write(f"Searching database: {db_file}...\n")
        try:
            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in c.fetchall()]
            for table in tables:
                try:
                    c.execute(f"SELECT * FROM {table} LIMIT 1")
                    row = c.fetchone()
                    if not row:
                        continue
                    columns = list(row.keys())
                    for col in columns:
                        query = f"SELECT * FROM {table} WHERE CAST({col} AS TEXT) LIKE ?"
                        c.execute(query, (f"%{search_term}%",))
                        rows = c.fetchall()
                        if rows:
                            filtered_rows = []
                            for r in rows:
                                val = str(r[col])
                                # Find if it's 'אבירן' only
                                if "אבירן" in val and val.count("אבירן") == val.count("בירן") and "צביקה" not in val:
                                    continue
                                filtered_rows.append(r)
                            
                            if filtered_rows:
                                out.write(f"  Table: {table}, Column: {col}, Matches: {len(filtered_rows)}\n")
                                for r in filtered_rows[:5]:
                                    d = dict(r)
                                    for k, v in d.items():
                                        if isinstance(v, str) and len(v) > 200:
                                            d[k] = v[:200] + "..."
                                    out.write(f"    {json.dumps(d, ensure_ascii=False)}\n")
                except Exception as e:
                    out.write(f"    Error reading table {table}: {e}\n")
        except Exception as e:
            out.write(f"  Error connecting to {db_file}: {e}\n")
    out.close()


if __name__ == "__main__":
    search_dbs()
