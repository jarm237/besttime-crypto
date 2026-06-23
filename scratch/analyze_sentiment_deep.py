"""
Phân tích sâu hơn: cơ chế fallback sentiment, records cụ thể,
và kiểm tra dữ liệu sentiment lịch sử từ nguồn khác
"""
import json, sys, os, collections
sys.stdout.reconfigure(encoding="utf-8")

# ── 1. Kiểm tra records có 2 giá trị fear_greed (15.0 và 23.0) ──────────────
print("=" * 65)
print("1. PHÂN TÍCH fear_greed theo time range")
print("=" * 65)

with open(r"d:\Workspaces\Vọc vạch\logs\adaptive_signals_v2.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# Tách theo giá trị fear_greed
fg15 = [r for r in data if r.get("fear_greed") == 15.0]
fg23 = [r for r in data if r.get("fear_greed") == 23.0]

if fg15:
    times15 = sorted(str(r.get("entry_time",""))[:10] for r in fg15)
    print(f"  fear_greed=15.0: {len(fg15)} records")
    print(f"    Time range: {times15[0]} → {times15[-1]}")
    print(f"    Example coins: {list(set(r.get('coin') for r in fg15[:20]))[:8]}")

if fg23:
    times23 = sorted(str(r.get("entry_time",""))[:10] for r in fg23)
    print(f"  fear_greed=23.0: {len(fg23)} records")
    print(f"    Time range: {times23[0]} → {times23[-1]}")
    print(f"    Example coins: {list(set(r.get('coin') for r in fg23[:20]))[:8]}")

# ── 2. Tìm file sentiment lịch sử thực sự ────────────────────────────────────
print()
print("=" * 65)
print("2. TÌM FILE SENTIMENT LỊCH SỬ TRONG PROJECT")
print("=" * 65)

base = r"d:\Workspaces\Vọc vạch"
for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if d not in ['.git', '.venv', '__pycache__', '.pytest_cache', 'node_modules']]
    for fn in files:
        if 'sentiment' in fn.lower() and fn.endswith(('.json', '.csv', '.jsonl')):
            fp = os.path.join(root, fn)
            size = os.path.getsize(fp)
            print(f"  {fp}  ({size:,} bytes)")

# ── 3. Kiểm tra dữ liệu historical_18m có tháng nào ──────────────────────────
print()
print("=" * 65)
print("3. DATA RANGE TRONG historical_18m vs SENTIMENT")
print("=" * 65)

data_dir = r"d:\Workspaces\Vọc vạch\data\historical_18m"
if os.path.exists(data_dir):
    files = sorted(os.listdir(data_dir))
    months = sorted(set("_".join(f.split("_")[:2]) for f in files if f.endswith(".csv")))
    print(f"  Số tháng có data: {len(months)}")
    print(f"  Tháng đầu: {months[0] if months else 'N/A'}")
    print(f"  Tháng cuối: {months[-1] if months else 'N/A'}")
else:
    print(f"  ❌ Không tìm thấy: {data_dir}")

# ── 4. Xem cấu trúc của 1 record để hiểu tại sao sentiment=0 ─────────────────
print()
print("=" * 65)
print("4. XEM CẤU TRÚC RECORD ĐẦY ĐỦ (record đầu tiên)")
print("=" * 65)

r0 = data[0]
# Tất cả keys và values
for k in sorted(r0.keys()):
    v = r0[k]
    print(f"  {k}: {v}")

# ── 5. Kiểm tra xem có record nào có sentiment != 0 không ────────────────────
print()
print("=" * 65)
print("5. RECORDS CÓ sentiment_momentum != 0 (nếu có)")
print("=" * 65)
non_zero = [r for r in data if r.get("sentiment_momentum", 0) != 0]
print(f"  Số records có sentiment_momentum != 0: {len(non_zero)}")
if non_zero:
    r = non_zero[0]
    print(f"  Ví dụ: coin={r.get('coin')}, time={r.get('entry_time','')[:10]}")
    print(f"    sentiment_momentum: {r.get('sentiment_momentum')}")
    print(f"    fear_greed: {r.get('fear_greed')}")
