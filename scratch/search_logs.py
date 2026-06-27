import os

def search_logs():
    terms = ["צביקה", "בירן"]
    log_files = ["app_remote.log", "app_remote.log.1"]
    
    with open("scratch/log_matches.txt", "w", encoding="utf-8") as out:
        for lf in log_files:
            if not os.path.exists(lf):
                out.write(f"Log file not found: {lf}\n")
                continue
                
            out.write(f"Searching log: {lf}...\n")
            line_num = 0
            matches = 0
            with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_num += 1
                    if any(t in line for t in terms):
                        # Filter out if it's just 'אבירן'
                        if "אבירן" in line and all(line.count("אבירן") == line.count(t) for t in terms if t == "בירן") and "צביקה" not in line:
                            continue
                        out.write(f"  Line {line_num}: {line.strip()[:300]}\n")
                        matches += 1
            out.write(f"Found {matches} matches in {lf}\n\n")

if __name__ == "__main__":
    search_logs()
