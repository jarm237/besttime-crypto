from pathlib import Path
import sqlite3

logs_dir = Path("runtime/worktrees/timestamp-remediation-20260901-01/runtime/paper/paper-canary-win-tsfix-20260901-01/logs")

for db_path in logs_dir.glob("*.sqlite"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"\n--- Database: {db_path.name} ---")
    for t in tables:
        count = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if count > 0:
            print(f"  Table '{t}': {count} rows")
    conn.close()
