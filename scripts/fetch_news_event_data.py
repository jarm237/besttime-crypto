"""Data Fetcher and Preprocessor for S1 News/Event Shock Discovery.

Fetches:
1. DeFiLlama verified crypto exploits/hacks database (2022-2026).
2. GDELT 2.0 15m archives for 6 representative market regime windows.
Saves raw artifacts into data/news_events/.
"""

import io
import csv
import json
import time
import zipfile
import urllib.request
import concurrent.futures
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "news_events"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_defillama_hacks():
    """Fetch all verified crypto security exploits from DeFiLlama."""
    print("Fetching DeFiLlama hacks dataset...")
    url = "https://api.llama.fi/hacks"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out_file = DATA_DIR / "defillama_hacks.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Successfully saved {len(data)} DeFiLlama incidents to {out_file}")
        return data
    except Exception as e:
        print(f"Error fetching DeFiLlama hacks: {e}")
        out_file = DATA_DIR / "defillama_hacks.json"
        if out_file.exists():
            print(f"Loading cached file from {out_file}")
            with open(out_file, "r", encoding="utf-8") as f:
                return json.load(f)
        raise e


def fetch_gdelt_15m_archive(dt_str: str):
    """Download and filter a single GDELT 2.0 15m archive for crypto events."""
    url = f"http://data.gdeltproject.org/gdeltv2/{dt_str}.export.CSV.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            content = resp.read()
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                lines = f.read().decode("utf-8", errors="ignore").splitlines()
                reader = csv.reader(lines, delimiter="\t")
                matches = []
                for row in reader:
                    if len(row) > 60:
                        url_src = row[60].lower()
                        # Match crypto-specific keywords in URL
                        if any(k in url_src for k in ["bitcoin", "crypto", "btc", "ethereum", "binance", "coinbase"]):
                            goldstein = float(row[30]) if row[30] else 0.0
                            tone = float(row[34]) if row[34] else 0.0
                            matches.append({
                                "global_id": row[0],
                                "date_added": row[59],
                                "event_code": row[26],
                                "goldstein": goldstein,
                                "tone": tone,
                                "url": row[60]
                            })
                return matches
    except Exception:
        return []


def fetch_gdelt_bounded_windows():
    """Fetch GDELT 2.0 archives for representative market shock windows.
    
    Windows:
    1. 2023-03-09 to 2023-03-14 (SVB / USDC depeg)
    2. 2023-06-05 to 2023-06-10 (SEC vs Binance & Coinbase)
    3. 2023-08-16 to 2023-08-20 (Flash crash liquidations)
    4. 2023-10-15 to 2023-10-20 (ETF rumor volatility)
    5. 2024-12-28 to 2025-01-04 (Train/Val split boundary)
    6. 2025-02-20 to 2025-02-25 (Bybit $1.4B hack stress)
    """
    out_file = DATA_DIR / "gdelt_bounded_windows.json"
    if out_file.exists():
        print(f"Loading existing GDELT cache from {out_file}...")
        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)

    print("Fetching GDELT 2.0 archives for bounded windows...")
    windows = [
        ("W1_SVB_USDC", pd.date_range("2023-03-09", "2023-03-14", freq="2h")),
        ("W2_SEC_ACTIONS", pd.date_range("2023-06-05", "2023-06-10", freq="2h")),
        ("W3_FLASH_CRASH", pd.date_range("2023-08-16", "2023-08-20", freq="2h")),
        ("W4_ETF_MOMENTUM", pd.date_range("2023-10-15", "2023-10-20", freq="2h")),
        ("W5_SPLIT_BOUNDARY", pd.date_range("2024-12-28", "2025-01-04", freq="2h")),
        ("W6_VAL_BYBIT", pd.date_range("2025-02-20", "2025-02-25", freq="2h")),
    ]

    all_window_data = {}
    for win_name, dr in windows:
        timestamps = [d.strftime("%Y%m%d%H%M00") for d in dr]
        print(f"Sampling {len(timestamps)} timepoints for window {win_name}...")
        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(fetch_gdelt_15m_archive, timestamps))
        events = [item for sub in results for item in sub]
        print(f"Window {win_name}: {len(events)} crypto events parsed in {time.time()-t0:.2f}s")
        all_window_data[win_name] = {
            "total_sampled_archives": len(timestamps),
            "events_found": len(events),
            "events": events
        }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_window_data, f, indent=2)
    print(f"Saved GDELT bounded windows to {out_file}")
    return all_window_data


if __name__ == "__main__":
    fetch_defillama_hacks()
    fetch_gdelt_bounded_windows()
