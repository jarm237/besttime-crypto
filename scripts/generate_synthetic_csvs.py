#!/usr/bin/env python3
import csv, os

BASE = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(BASE, "data", "BTC_15m.csv")
OUT_DIR = os.path.join(BASE, "data")

# scale factors to convert BTC prices into synthetic coin prices
TARGETS = {
    "BNB": 0.003,   # ~100k -> ~300
    "XRP": 1e-05,   # ~100k -> ~1
    "DOGE": 1e-06,  # ~100k -> ~0.1
    "ADA": 1e-05,   # ~100k -> ~1
    "LTC": 0.005,   # ~100k -> ~500
    "ZEC": 0.01,    # ~100k -> ~1000
}

os.makedirs(OUT_DIR, exist_ok=True)

with open(SRC, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

for coin, factor in TARGETS.items():
    out_path = os.path.join(OUT_DIR, f"{coin}_15m.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as wf:
        writer = csv.writer(wf)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        for r in rows:
            try:
                open_p = float(r["open"]) * factor
                high_p = float(r["high"]) * factor
                low_p = float(r["low"]) * factor
                close_p = float(r["close"]) * factor
                vol = float(r.get("volume", 0.0))
            except Exception:
                continue
            # Round prices to sensible decimals depending on magnitude
            if close_p >= 100:
                fmt = "{:.2f}"
            elif close_p >= 1:
                fmt = "{:.4f}"
            else:
                fmt = "{:.6f}"
            writer.writerow([
                r["time"],
                fmt.format(open_p),
                fmt.format(high_p),
                fmt.format(low_p),
                fmt.format(close_p),
                "{:.6f}".format(vol),
            ])
    print(f"Wrote {out_path} ({len(rows)} rows)")

print("Done generating synthetic CSVs.")
