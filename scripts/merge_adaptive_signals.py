#!/usr/bin/env python3
"""Merge per-coin adaptive signals files into a single `logs/adaptive_signals_v2.json`.

It looks for files `logs/adaptive_signals_v2_*.json` and concatenates lists.
"""
import json
from pathlib import Path


LOGS = Path("logs")
OUT = LOGS / "adaptive_signals_v2.json"


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    parts = sorted(LOGS.glob("adaptive_signals_v2_*.json"))
    if not parts:
        print("No per-coin files found in logs/ (adaptive_signals_v2_*.json)")
        return 1

    merged = []
    counts = {}
    for p in parts:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Skipping {p}: load error: {e}")
            continue
        if isinstance(data, list):
            merged.extend(data)
            counts[p.name] = len(data)
        else:
            print(f"Skipping {p}: unexpected format (not a list)")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"Merged {len(parts)} files → {OUT} ({len(merged)} records)")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
