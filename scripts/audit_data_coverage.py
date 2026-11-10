import os, json, glob
from pathlib import Path
import pandas as pd

base_dir = Path("data/fresh_training_data_2023_2026")
manifest_file = base_dir / "manifest.json"

with open(manifest_file, "r") as f:
    manifest = json.load(f)

coins = manifest.get("coins", [])
intervals = manifest.get("intervals", [])
print(f"Total coins in manifest: {len(coins)}: {coins}")
print(f"Intervals: {intervals}")

summary = {}
for coin in coins:
    coin_dir = base_dir / coin
    if not coin_dir.exists():
        summary[coin] = {"status": "DIRECTORY_NOT_FOUND"}
        continue
    
    tf_data = {}
    for tf in intervals:
        tf_dir = coin_dir / tf
        if not tf_dir.exists():
            tf_data[tf] = {"status": "NO_TF_DIR"}
            continue
        csvs = sorted(glob.glob(str(tf_dir / "*.csv")))
        if not csvs:
            tf_data[tf] = {"status": "NO_FILES"}
            continue
        
        n_files = len(csvs)
        try:
            df_first = pd.read_csv(csvs[0])
            df_last = pd.read_csv(csvs[-1])
            earliest_time = str(df_first["time"].iloc[0])
            latest_time = str(df_last["time"].iloc[-1])
            
            # Quick row sum
            total_rows = 0
            for c in csvs:
                with open(c, "r", encoding="utf-8") as f_c:
                    total_rows += sum(1 for _ in f_c) - 1
            
            first_month = Path(csvs[0]).stem.split("_")[-1]
            last_month = Path(csvs[-1]).stem.split("_")[-1]
            
            tf_data[tf] = {
                "n_files": n_files,
                "first_month": first_month,
                "last_month": last_month,
                "earliest_time": earliest_time,
                "latest_time": latest_time,
                "total_rows": total_rows,
            }
        except Exception as e:
            tf_data[tf] = {"error": str(e)}
    summary[coin] = tf_data

print("\n" + "=" * 80)
print(f"{'Coin':<8} | {'15m Range':<22} | {'15m Rows':<10} | {'1h Range':<22} | {'1h Rows':<10} | {'Status'}")
print("-" * 80)

for coin, tfs in summary.items():
    r15 = tfs.get("15m", {})
    r1h = tfs.get("1h", {})
    r15_str = f"{r15.get('first_month')}..{r15.get('last_month')}" if "first_month" in r15 else "MISSING"
    r15_rows = r15.get("total_rows", 0)
    r1h_str = f"{r1h.get('first_month')}..{r1h.get('last_month')}" if "first_month" in r1h else "MISSING"
    r1h_rows = r1h.get("total_rows", 0)
    
    # Classify coin listing status
    first_m = r1h.get("first_month", "")
    if first_m == "2023-01":
        status = "FULL_HISTORY_2023_2026"
    elif first_m > "2023-01":
        status = f"LATE_LISTING ({first_m})"
    else:
        status = "UNKNOWN_OR_MISSING"
        
    print(f"{coin:<8} | {r15_str:<22} | {r15_rows:<10} | {r1h_str:<22} | {r1h_rows:<10} | {status}")
