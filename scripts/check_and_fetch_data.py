"""
Check data directory for required candle CSVs; if missing, run
`fetch_historical_range.py` to fetch them. Also migrate legacy files named
`<COIN>_<interval>.csv` -> `legacy_<COIN>_<interval>.csv` to avoid lookup issues.
Saves a JSON report to `logs/data_check_report.json`.
"""
import os
import sys
import glob
import json
import time
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
LOGS = BASE / "logs"
REPORT = LOGS / "data_check_report.json"

sys.path.insert(0, str(BASE))

try:
    from btc_scraper.core.config import COINS
except Exception:
    COINS = []

INTERVAL = "15m"


def find_files_for_coin(coin: str) -> list:
    pattern1 = str(DATA_DIR / f"*_{coin}_{INTERVAL}.csv")  # month_prefixed
    pattern2 = str(DATA_DIR / f"{coin}_{INTERVAL}.csv")   # legacy style
    return glob.glob(pattern1) + glob.glob(pattern2)


def main():
    os.makedirs(LOGS, exist_ok=True)
    report = {
        "timestamp": time.time(),
        "coins_checked": [],
        "missing_coins": [],
        "found_examples": [],
        "migrated_files": [],
        "fetch_ran": False,
        "fetch_returncode": None,
        "fetch_stdout": None,
        "fetch_stderr": None,
    }

    if not COINS:
        print("Warning: COINS list empty or config import failed.")

    for coin in COINS:
        files = find_files_for_coin(coin)
        report["coins_checked"].append({"coin": coin, "files_found": files})
        if not files:
            report["missing_coins"].append(coin)
        else:
            report["found_examples"].append({"coin": coin, "example": files[0]})

    if report["missing_coins"]:
        print("Missing data for coins:", report["missing_coins"])
        print("Running fetch_historical_range.py to attempt to fetch missing data...")
        fetch_cmd = [sys.executable, str(BASE / "fetch_historical_range.py")]
        try:
            proc = subprocess.run(fetch_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=3600)
            report["fetch_ran"] = True
            report["fetch_returncode"] = proc.returncode
            report["fetch_stdout"] = (proc.stdout or '')[:20000]
            report["fetch_stderr"] = (proc.stderr or '')[:20000]
            print("Fetch finished with returncode", proc.returncode)
        except subprocess.TimeoutExpired:
            report["fetch_ran"] = True
            report["fetch_returncode"] = -1
            report["fetch_stdout"] = "TIMEOUT"
            report["fetch_stderr"] = "TIMEOUT"
            print("Fetch command timed out.")

        # Re-scan after fetch
        report["post_fetch"] = {"coins": []}
        for coin in report["missing_coins"]:
            files = find_files_for_coin(coin)
            report["post_fetch"]["coins"].append({"coin": coin, "files_found": files})

    # Migrate legacy files: e.g., BTC_15m.csv -> legacy_BTC_15m.csv
    migrated = []
    for coin in COINS:
        legacy_pattern = DATA_DIR / f"{coin}_{INTERVAL}.csv"
        if legacy_pattern.exists():
            target = DATA_DIR / f"legacy_{coin}_{INTERVAL}.csv"
            try:
                shutil.move(str(legacy_pattern), str(target))
                migrated.append({"from": str(legacy_pattern), "to": str(target)})
                print(f"Migrated {legacy_pattern} -> {target}")
            except Exception as e:
                print(f"Failed to migrate {legacy_pattern}: {e}")

    report["migrated_files"] = migrated

    # Save report
    try:
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("Saved report to", REPORT)
    except Exception as e:
        print("Failed to save report:", e)
        return 2

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
