#!/usr/bin/env python3
import os
import json
import re

def split_log():
    log_dir = "logs"
    out_dir = os.path.join(log_dir, "daily")
    input_file = os.path.join(log_dir, "meta_prob_entry.log")
    
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    
    if not os.path.exists(input_file):
        print(f"Error: {input_file} does not exist.")
        return

    print(f"Splitting {input_file} into {out_dir}...")
    
    # Regex to quickly extract ts if json parsing fails or for speed
    ts_regex = re.compile(r'"ts"\s*:\s*"(\d{4}-\d{2}-\d{2})')
    
    open_files = {}
    lines_processed = 0
    lines_written = 0
    errors = 0
    
    try:
        with open(input_file, 'r', encoding='utf-8') as infile:
            for line in infile:
                lines_processed += 1
                line_str = line.strip()
                if not line_str:
                    continue
                
                date_str = None
                # First try regex for speed/robustness
                match = ts_regex.search(line_str)
                if match:
                    date_str = match.group(1)
                else:
                    # Fallback to JSON parsing
                    try:
                        data = json.loads(line_str)
                        ts = data.get("ts")
                        if ts and len(ts) >= 10:
                            date_str = ts[:10]
                    except Exception:
                        pass
                
                if date_str:
                    if date_str not in open_files:
                        out_path = os.path.join(out_dir, f"meta_prob_entry_{date_str}.log")
                        open_files[date_str] = open(out_path, 'a', encoding='utf-8')
                    
                    open_files[date_str].write(line)
                    lines_written += 1
                else:
                    errors += 1
                    # Log the erroneous line or skip
                    print(f"Warning: Could not parse timestamp on line {lines_processed}: {line_str[:100]}")
                    
    finally:
        # Close all open files
        for f in open_files.values():
            f.close()
            
    print(f"Split complete. Processed {lines_processed} lines. Written {lines_written} lines. Errors: {errors}.")
    print("Generated daily log files:")
    for date_str in sorted(open_files.keys()):
        out_path = os.path.join(out_dir, f"meta_prob_entry_{date_str}.log")
        size = os.path.getsize(out_path)
        print(f"  - {out_path} ({size / 1024:.2f} KB)")

if __name__ == "__main__":
    split_log()
