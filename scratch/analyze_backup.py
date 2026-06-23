"""
Phân tích file backup adaptive_signals_backup.json:
- Cấu trúc sentiment data 
- Xem bao nhiêu unique fear_greed values
- Kiểm tra time range và distribution
"""
import json, sys, collections
sys.stdout.reconfigure(encoding="utf-8")

with open(r"d:\Workspaces\Vọc vạch\logs\adaptive_signals_backup.json", "r", encoding="utf-8") as f:
    backup = json.load(f)

print(f"Backup records: {len(backup)}")
print()

# ── Kiểm tra sentiment fields trong backup ───────────────────────────────────
sentiment_fields = ["fear_greed", "sentiment_momentum", "sentiment_recovery",
                    "sentiment_risk", "sentiment_trend_up", "sentiment_trend_down"]

print("=== SENTIMENT STATS IN BACKUP ===")
for field in sentiment_fields:
    values = [r.get(field) for r in backup]
    missing = sum(1 for v in values if v is None)
    nums = [v for v in values if v is not None]
    if nums:
        unique = len(set(nums))
        mn, mx = min(nums), max(nums)
        avg = sum(nums) / len(nums)
        non_zero = sum(1 for v in nums if v != 0)
        print(f"  {field:<22}: missing={missing:>5}, unique={unique:>4}, min={mn:.1f}, max={mx:.1f}, mean={avg:.2f}, non_zero={non_zero}")
    else:
        print(f"  {field:<22}: ALL MISSING ({missing} records)")

# ── Phân phối fear_greed theo nhóm 10 ───────────────────────────────────────
print()
print("=== FEAR_GREED DISTRIBUTION (backup) ===")
fg_vals = [r.get("fear_greed") for r in backup if r.get("fear_greed") is not None]
fg_buckets = collections.Counter(int(v // 10) * 10 for v in fg_vals)
for bucket in sorted(fg_buckets.keys()):
    count = fg_buckets[bucket]
    bar = "█" * (count // 100)
    print(f"  {bucket:>3}-{bucket+9:<3}: {count:>5} {bar}")

# ── Time range backup ─────────────────────────────────────────────────────────
print()
print("=== TIME RANGE (backup) ===")
times = sorted(str(r.get("entry_time", ""))[:10] for r in backup if r.get("entry_time"))
valid_times = [t for t in times if t.startswith("20")]
if valid_times:
    print(f"  Earliest : {valid_times[0]}")
    print(f"  Latest   : {valid_times[-1]}")
    years = collections.Counter(t[:4] for t in valid_times)
    print(f"  By year  : {dict(sorted(years.items()))}")

# ── Xem cấu trúc 1 backup record đầy đủ ─────────────────────────────────────
print()
print("=== SAMPLE BACKUP RECORD (first record) ===")
r0 = backup[0]
for k in sorted(r0.keys()):
    print(f"  {k}: {r0[k]}")
