#!/usr/bin/env python3
"""Analyze April backtest trades and run simple threshold tuning.

Usage: python3 scripts/analyze_april_backtest.py
"""
import json
import math
from pathlib import Path
import statistics as stats
import csv

# Try to import pandas, but provide a csv-only fallback if not available
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    pd = None
    PANDAS_AVAILABLE = False


def parse_signal_meta(s):
    if s is None:
        return {}
    if PANDAS_AVAILABLE and pd.isna(s):
        return {}
    # s may be a JSON-like string from CSV; try json.loads first
    try:
        return json.loads(s)
    except Exception:
        try:
            # fallback to ast-style
            import ast

            return ast.literal_eval(s)
        except Exception:
            # try to fix doubled quotes
            try:
                return json.loads(s.replace('""', '"'))
            except Exception:
                return {}


def summary_stats(df):
    # df can be a pandas DataFrame or a list of dict rows
    if PANDAS_AVAILABLE and hasattr(df, 'columns'):
        pnl = df['pnl'].astype(float)
        n = len(pnl)
        wins = (pnl > 0).sum()
        losses = (pnl <= 0).sum()
        win_rate = wins / n * 100 if n else 0.0
        total_pnl = pnl.sum()
        avg_pnl = pnl.mean() if n else 0.0
        std_pnl = pnl.std(ddof=0) if n else 0.0
        sharpe = (avg_pnl / std_pnl) if std_pnl and not math.isnan(std_pnl) else float('nan')

        equity = pnl.cumsum()
        peak = equity.cummax()
        drawdown = (peak - equity)
        max_dd = drawdown.max() if n else 0.0

        r_mult = None
        if 'r_multiplier' in df.columns:
            try:
                r_mult = df['r_multiplier'].astype(float).replace([pd.NA], float('nan'))
            except Exception:
                r_mult = None

        median_r = float(r_mult.median()) if r_mult is not None and not r_mult.dropna().empty else None
    else:
        # list of dicts
        rows = list(df)
        pnl = [float(r.get('pnl', 0) or 0) for r in rows]
        n = len(pnl)
        wins = sum(1 for x in pnl if x > 0)
        losses = n - wins
        win_rate = wins / n * 100 if n else 0.0
        total_pnl = sum(pnl)
        avg_pnl = total_pnl / n if n else 0.0
        std_pnl = stats.pstdev(pnl) if n > 0 else 0.0
        sharpe = (avg_pnl / std_pnl) if std_pnl and not math.isnan(std_pnl) else float('nan')

        equity = []
        s = 0.0
        for x in pnl:
            s += x
            equity.append(s)
        peak = []
        m = -1e18
        for e in equity:
            m = max(m, e)
            peak.append(m)
        drawdown = [p - e for p, e in zip(peak, equity)]
        max_dd = max(drawdown) if drawdown else 0.0

        r_vals = []
        for r in rows:
            v = r.get('r_multiplier')
            try:
                if v is None or v == '':
                    continue
                r_vals.append(float(v))
            except Exception:
                continue
        median_r = statistics_median_safe(r_vals)

    return {
        'n_trades': int(n),
        'wins': int(wins),
        'losses': int(losses),
        'win_rate_pct': round(win_rate, 2),
        'total_pnl': round(float(total_pnl), 4),
        'avg_pnl': round(float(avg_pnl), 6),
        'std_pnl': round(float(std_pnl), 6) if not math.isnan(std_pnl) else None,
        'sharpe': round(float(sharpe), 4) if not math.isnan(sharpe) else None,
        'max_drawdown': round(float(max_dd), 6),
        'median_r_multiplier': round(float(median_r), 6) if median_r is not None else None,
    }


def statistics_median_safe(seq):
    try:
        if not seq:
            return None
        return stats.median(seq)
    except Exception:
        return None


def run_threshold_sweep(df):
    # ensure signal_meta parsed with keys 'score' and 'position_size' when possible
    if PANDAS_AVAILABLE and hasattr(df, '_signal_meta'):
        metas = df['_signal_meta'].tolist()
        scores = [m.get('score') if isinstance(m, dict) else None for m in metas]
        df['_score'] = scores
    else:
        metas = [r.get('_signal_meta', {}) for r in df]
        scores = [m.get('score') if isinstance(m, dict) else None for m in metas]

    results = []
    for thresh in range(0, 101, 5):
        if PANDAS_AVAILABLE and hasattr(df, '_score'):
            sub = df[df['_score'].apply(lambda v: v is not None and v >= thresh)]
            empty = sub.empty
        else:
            sub = [r for r, sc in zip(df, scores) if sc is not None and sc >= thresh]
            empty = len(sub) == 0
        if empty:
            continue
        s = summary_stats(sub)
        s.update({'threshold': thresh})
        results.append(s)

    # sort by total_pnl desc and by expectancy (avg_pnl)
    results_sorted = sorted(results, key=lambda x: (x['total_pnl'], x['avg_pnl']), reverse=True)
    return results_sorted[:10]


def main():
    root = Path(__file__).resolve().parents[1]
    csv_path = root / 'logs' / 'backtest_trades.csv'
    if not csv_path.exists():
        print('backtest_trades.csv not found at', csv_path)
        return

    if PANDAS_AVAILABLE:
        df = pd.read_csv(csv_path)
        col_candidates = [c for c in df.columns if 'signal' in c]
        sig_col = col_candidates[0] if col_candidates else None
        if sig_col is None:
            df['_signal_meta'] = [{}] * len(df)
        else:
            df['_signal_meta'] = df[sig_col].apply(parse_signal_meta)
    else:
        # load with csv.DictReader
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                # parse signal meta field
                sig_keys = [k for k in r.keys() if 'signal' in k]
                if sig_keys:
                    meta = parse_signal_meta(r[sig_keys[0]])
                else:
                    meta = {}
                r['_signal_meta'] = meta
                rows.append(r)
        df = rows

    # If user asked for deep analysis, also aggregate all april backtest trade files
    def load_all_trades():
        files = []
        files += list((root / 'data').glob('april_backtest_trades_*.csv'))
        files += list((root / 'logs').glob('backtest_trades*.csv'))
        seen = set()
        rows = []
        for p in files:
            try:
                if PANDAS_AVAILABLE:
                    d = pd.read_csv(p)
                    for _, r in d.iterrows():
                        rd = dict(r.dropna().to_dict())
                        rd['_source'] = str(p.name)
                        # normalize pnl: prefer pnl_usd then pnl then pnl_pct
                        if 'pnl_usd' in rd:
                            rd['pnl'] = rd.get('pnl_usd')
                        elif 'pnl' in rd:
                            rd['pnl'] = rd.get('pnl')
                        elif 'pnl_pct' in rd:
                            rd['pnl'] = rd.get('pnl_pct')
                        rows.append(rd)
                else:
                    with open(p, 'r', encoding='utf-8') as fh:
                        reader = csv.DictReader(fh)
                        for r in reader:
                            r['_source'] = str(p.name)
                            if 'pnl_usd' in r and r['pnl_usd'] != '':
                                r['pnl'] = r['pnl_usd']
                            elif 'pnl' in r and r['pnl'] != '':
                                r['pnl'] = r['pnl']
                            elif 'pnl_pct' in r and r['pnl_pct'] != '':
                                r['pnl'] = r['pnl_pct']
                            rows.append(r)
            except Exception:
                continue
        return rows

    print('=== Backtest Trades Summary (single file) ===')
    base = summary_stats(df)
    for k, v in base.items():
        print(f'{k}: {v}')

    print('\n=== Aggregating all April backtest trade files ===')
    all_trades = load_all_trades()
    print(f'Found {len(all_trades)} combined trades from data/ and logs/')
    if not all_trades:
        print('No additional trades found. Done.')
        return

    overall = summary_stats(all_trades)
    print('\n=== Overall aggregated April backtest ===')
    for k, v in overall.items():
        print(f'{k}: {v}')

    # breakdown by coin
    from collections import defaultdict

    by_coin = defaultdict(list)
    by_conf = defaultdict(list)
    by_signal = defaultdict(list)
    for r in all_trades:
        coin = r.get('coin') or r.get('symbol') or r.get('ticker') or r.get('COIN')
        if coin is None:
            coin = 'UNKNOWN'
        by_coin[coin].append(r)
        conf = (r.get('confidence') or r.get('Confidence') or '').upper()
        by_conf[conf].append(r)
        sig = r.get('signal') or r.get('Signal') or ''
        by_signal[sig].append(r)

    print('\n=== Top coins by total_pnl ===')
    coin_stats = []
    for c, rows in by_coin.items():
        s = summary_stats(rows)
        s['coin'] = c
        coin_stats.append(s)
    coin_stats = sorted(coin_stats, key=lambda x: x['total_pnl'], reverse=True)
    for s in coin_stats[:10]:
        print(s)

    print('\n=== By confidence group ===')
    for conf, rows in by_conf.items():
        s = summary_stats(rows)
        print(conf or 'UNSPEC', s)

    print('\n=== Top signals by count ===')
    sig_counts = sorted([(k, len(v)) for k, v in by_signal.items()], key=lambda x: x[1], reverse=True)
    for k, cnt in sig_counts[:10]:
        print(k, cnt)

    print('\nDone deep analysis.')


if __name__ == '__main__':
    main()
