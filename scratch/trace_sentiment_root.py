"""
Trace root cause:
1. Tại sao fear_greed chỉ có 2 giá trị (15.0 và 23.0)?
2. Nguồn dữ liệu sentiment lịch sử ở đâu?
3. Phân tích khoảng trống dữ liệu 2023-08 → 2024-12
"""
import json, sys, os, glob
sys.stdout.reconfigure(encoding="utf-8")

BASE = r"d:\Workspaces\Vọc vạch"

# ── 1. Xem dải tháng trong historical_18m ────────────────────────────────────
print("=" * 65)
print("1. HISTORICAL DATA MONTHS vs SENTIMENT COVERAGE")
print("=" * 65)

data_dir = os.path.join(BASE, "data", "historical_18m")
files = sorted(os.listdir(data_dir))
months = sorted(set("_".join(f.split("_")[:2]) for f in files if f.endswith(".csv")))
print(f"  Months in historical_18m:")
for m in months:
    print(f"    {m}")

print()
print("  Sentiment file chỉ có ngày: 2026-06-23 (toàn bộ chỉ 1 ngày)")
print("  → Tất cả records từ 2023-2026 đều bị fallback về giá trị mặc định")
print()

# ── 2. Kiểm tra tại sao fear_greed = 15.0 cho dữ liệu 2023 ──────────────────
print("=" * 65)
print("2. SOURCE CỦA GIÁ TRỊ fear_greed=15.0 (2023 records)")
print("=" * 65)

# Đọc 1 record từ 2023 để xem
with open(os.path.join(BASE, "logs", "adaptive_signals_v2.json"), "r", encoding="utf-8") as f:
    data = json.load(f)

# Records 2023
r2023 = [r for r in data if str(r.get("entry_time",""))[:4] == "2023"]
print(f"  Số records 2023: {len(r2023)}")
if r2023:
    # Xem unique fear_greed values và coin
    fg_vals = set(r.get("fear_greed") for r in r2023)
    coins = set(r.get("coin") for r in r2023)
    print(f"  Unique fear_greed values: {fg_vals}")
    print(f"  Unique coins: {coins}")
    print(f"  Time range: {min(str(r.get('entry_time',''))[:10] for r in r2023)} → {max(str(r.get('entry_time',''))[:10] for r in r2023)}")

# Records 2024
r2024 = [r for r in data if str(r.get("entry_time",""))[:4] == "2024"]
print(f"\n  Số records 2024: {len(r2024)}")

# Records 2025
r2025 = [r for r in data if str(r.get("entry_time",""))[:4] == "2025"]
print(f"  Số records 2025: {len(r2025)}")
if r2025:
    fg25 = set(r.get("fear_greed") for r in r2025)
    print(f"    fear_greed values 2025: {fg25}")

# Records 2026
r2026 = [r for r in data if str(r.get("entry_time",""))[:4] == "2026"]
print(f"  Số records 2026: {len(r2026)}")
if r2026:
    fg26 = set(r.get("fear_greed") for r in r2026)
    print(f"    fear_greed values 2026: {fg26}")

# ── 3. Tìm script nào đã tạo ra 2023 records (với fear_greed=15) ─────────────
print()
print("=" * 65)
print("3. PHÂN TÍCH MERGE HISTORY (adaptive_signals_v2_2023_merge_summary)")
print("=" * 65)

merge_file = os.path.join(BASE, "logs", "adaptive_signals_v2_2023_merge_summary.json")
if os.path.exists(merge_file):
    with open(merge_file, "r", encoding="utf-8") as f:
        merge_summary = json.load(f)
    print(f"  Merge summary: {json.dumps(merge_summary, indent=2, ensure_ascii=False)}")
else:
    print(f"  File không tồn tại: {merge_file}")

# ── 4. Kiểm tra backup file (adaptive_signals_backup.json) ───────────────────
print()
print("=" * 65)
print("4. SO SÁNH BACKUP vs CURRENT (sentiment trong backup)")
print("=" * 65)

backup_path = os.path.join(BASE, "logs", "adaptive_signals_backup.json")
if os.path.exists(backup_path):
    with open(backup_path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)
    print(f"  Backup records: {len(backup_data)}")
    if backup_data:
        # Kiểm tra sentiment fields trong backup
        sentiment_fields = ["fear_greed", "sentiment_momentum", "sentiment_recovery"]
        r0 = backup_data[0]
        for sf in sentiment_fields:
            print(f"  {sf}: {r0.get(sf, 'MISSING')}")
        
        # Unique fear_greed in backup
        fg_backup = set(r.get("fear_greed") for r in backup_data if r.get("fear_greed") is not None)
        print(f"  Unique fear_greed in backup: {fg_backup}")
        
        # Time range
        times = sorted(str(r.get("entry_time",""))[:10] for r in backup_data)
        print(f"  Time range backup: {times[0]} → {times[-1]}")
else:
    print(f"  Không tìm thấy backup: {backup_path}")

# ── 5. Kiểm tra fetch scripts xem historical sentiment ở đâu ─────────────────
print()
print("=" * 65)
print("5. SCRIPTS XỬ LÝ SENTIMENT LỊCH SỬ")
print("=" * 65)

script_dir = os.path.join(BASE, "scripts")
for fn in sorted(os.listdir(script_dir)):
    if "sentiment" in fn.lower():
        fp = os.path.join(script_dir, fn)
        size = os.path.getsize(fp)
        print(f"  {fn} ({size:,} bytes)")
