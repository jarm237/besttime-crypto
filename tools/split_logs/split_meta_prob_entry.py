#!/usr/bin/env python3
"""Split meta_prob_entry.log (JSONL) into daily files named
meta_prob_entry_YYYY-MM-DD.log saved in a `daily/` subdirectory
next to each input log file.

Usage: python3 split_meta_prob_entry.py /path/to/meta_prob_entry.log [...]
"""
import argparse
import json
import os
from datetime import datetime


def safe_parse_json_line(line: str):
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        # try to recover by extracting the first {...} block
        start = line.find('{')
        end = line.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(line[start:end+1])
            except Exception:
                return None
        return None


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def split_file(path: str, dry_run: bool = False, inplace: bool = False):
    if not os.path.isfile(path):
        print(f"Skipping (not found): {path}")
        return 0
    if inplace:
        out_dir = os.path.dirname(path)
    else:
        out_dir = os.path.join(os.path.dirname(path), 'daily')
    ensure_dir(out_dir)

    writers = {}
    count = 0
    with open(path, 'r', encoding='utf-8') as fh:
        for i, raw in enumerate(fh, start=1):
            obj = safe_parse_json_line(raw)
            if not obj:
                # skip malformed line but report once per 1000
                if i % 1000 == 0:
                    print(f"Warning: skipping malformed line {i} in {path}")
                continue
            ts = obj.get('ts') or obj.get('timestamp')
            if not ts:
                # fallback: use current date
                date_key = datetime.utcnow().date().isoformat()
            else:
                try:
                    # handle ISO-like strings
                    dt = datetime.fromisoformat(ts)
                    date_key = dt.date().isoformat()
                except Exception:
                    # last-resort: take first 10 chars
                    date_key = ts[:10]

            out_name = f"meta_prob_entry_{date_key}.log"
            out_path = os.path.join(out_dir, out_name)

            if dry_run:
                writers.setdefault(out_path, 0)
                writers[out_path] += 1
            else:
                if out_path not in writers:
                    writers[out_path] = open(out_path, 'a', encoding='utf-8')
                writers[out_path].write(raw.rstrip('\n') + '\n')
            count += 1

    # close file handles
    if not dry_run:
        for p, w in writers.items():
            try:
                w.close()
            except Exception:
                pass
    else:
        # print summary for dry run
        for p, c in writers.items():
            print(f"Would write {c} lines to {p}")

    print(f"Processed {count} lines from {path}. Output in {out_dir}")
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('files', nargs='+', help='Paths to meta_prob_entry.log files')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--inplace', action='store_true', help='Write output files into the same directory as input')
    args = parser.parse_args()

    total = 0
    for p in args.files:
        total += split_file(p, dry_run=args.dry_run, inplace=args.inplace)

    print(f"Total lines processed: {total}")


if __name__ == '__main__':
    main()
