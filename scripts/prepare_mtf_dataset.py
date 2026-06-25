"""
Prepare MTF training datasets from historical CSVs and adaptive_signals logs.
Usage:
    python scripts/prepare_mtf_dataset.py --tf 1h --hold_candles 6 --out data/mtf_dataset_1h.csv

This script:
 - Loads per-coin TF CSVs (e.g. data/BTC_1h.csv)
 - Loads historical signals from logs/adaptive_signals.json (optional)
 - For each signal, computes features via btc_scraper.ml_engine.feature_extractor.build_meta_features
 - Computes label by checking future price movement over `hold_candles` on target TF using 'close' column
 - Emits a CSV with features + label
"""

import argparse
import json
import os
import glob
import csv
from datetime import datetime
from typing import Dict, Any

# Local imports inside functions to avoid import-time side effects


def load_signals(signals_path: str) -> list:
    if not os.path.exists(signals_path):
        return []
    out = []
    with open(signals_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def read_csv_candles(path: str) -> list[Dict[str, Any]]:
    # Expect header with at least: timestamp,open,high,low,close,volume
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                r2 = {k: float(v) if k in ('open','high','low','close','volume') else v for k,v in r.items()}
            except Exception:
                r2 = r
            rows.append(r2)
    return rows


def find_csv_for_coin_tf(coin: str, tf: str) -> str | None:
    # Match patterns like data/BTC_1h.csv or data/april_2025_BTC_1h.csv
    base = os.path.join('data', f'*{coin.upper()}*_{tf}.csv')
    matches = glob.glob(base)
    if matches:
        return matches[0]
    # try coin lowercase
    base = os.path.join('data', f'*{coin.lower()}*_{tf}.csv')
    matches = glob.glob(base)
    return matches[0] if matches else None


def compute_future_return(candles: list, idx: int, hold: int) -> float:
    # return percent change from close at idx to close at idx+hold
    if idx + hold >= len(candles):
        return 0.0
    try:
        c0 = float(candles[idx]['close'])
        c1 = float(candles[idx+hold]['close'])
        return (c1 - c0) / c0
    except Exception:
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tf', required=True, help='TF to prepare (1h,4h,1d)')
    parser.add_argument('--hold_candles', type=int, default=6, help='Number of candles to hold for label')
    parser.add_argument('--out', required=True, help='Output CSV file')
    parser.add_argument('--signals', default='logs/adaptive_signals.json', help='Path to adaptive_signals JSONL')
    args = parser.parse_args()

    tf = args.tf
    hold = args.hold_candles
    out_path = args.out

    signals = load_signals(args.signals)
    print(f"Loaded {len(signals)} historical signals from {args.signals}")

    # Group signals by coin and tf (if signal contains tf info)
    by_coin = {}
    for s in signals:
        coin = s.get('coin') or s.get('symbol') or s.get('ticker') or s.get('pair')
        if not coin:
            continue
        coin = coin.replace('USDT','').replace('/','').upper()
        # Some signals may include tf info; we keep all and later match by timestamp
        by_coin.setdefault(coin, []).append(s)

    # Prepare CSV header using feature_extractor fields
    try:
        from btc_scraper.ml_engine.feature_extractor import build_meta_features
    except Exception as e:
        print('Cannot import feature_extractor:', e)
        return

    header_written = False
    with open(out_path, 'w', encoding='utf-8', newline='') as outf:
        writer = None
        for coin, sigs in by_coin.items():
            csv_path = find_csv_for_coin_tf(coin, tf)
            if not csv_path:
                continue
            print(f"Processing {coin} using {csv_path}")
            candles = read_csv_candles(csv_path)
            # build index by timestamp if available
            ts_index = {str(int(r.get('timestamp'))): i for i, r in enumerate(candles) if 'timestamp' in r}

            for s in sigs:
                # find nearest candle index by signal timestamp
                ts = s.get('ts') or s.get('timestamp') or s.get('time')
                if not ts:
                    continue
                # normalize ts strings
                try:
                    tsi = int(float(ts))
                except Exception:
                    try:
                        # try parse ISO
                        tsi = int(datetime.fromisoformat(ts).timestamp())
                    except Exception:
                        continue
                key = str(tsi)
                idx = ts_index.get(key)
                if idx is None:
                    # fallback: skip
                    continue

                # prepare sample
                # construct info dict from candle and signal
                info = dict(candles[idx])
                info.update(s)
                # compute future return label
                fut = compute_future_return(candles, idx, hold)
                label = 1 if fut > 0 else 0

                features = build_meta_features(info)
                features['label'] = label
                features['coin'] = coin
                features['tf'] = tf
                features['ts'] = tsi

                if not header_written:
                    writer = csv.DictWriter(outf, fieldnames=list(features.keys()))
                    writer.writeheader()
                    header_written = True
                writer.writerow(features)

    print('Done. Wrote', out_path)


if __name__ == '__main__':
    main()
