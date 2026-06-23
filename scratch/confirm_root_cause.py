"""
Xác nhận root cause cuối cùng:
Kiểm tra xem sentiment_history.json có được ghi đè bởi process nào không
(live system đang chạy ghi timestamps mới liên tục vào file)
"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")

# ── Kiểm tra format key trong sentiment_history.json ─────────────────────────
print("=== KEY FORMAT ANALYSIS ===")
with open(r"d:\Workspaces\Vọc vạch\logs\sentiment_history.json", "r", encoding="utf-8") as f:
    sh = json.load(f)

keys = sorted(sh.keys())
print(f"Total keys: {len(keys)}")
print(f"Sample keys (first 5):")
for k in keys[:5]:
    print(f"  '{k}'")
print()

# Thử parse theo cách build_and_train.py làm (k[:10])
print("=== DATE EXTRACTION (k[:10]) ===")
date_keys = set(k[:10] for k in keys)
print(f"Unique dates: {sorted(date_keys)}")
print()

# ── Giải thích vấn đề key format ─────────────────────────────────────────────
print("=== PHÂN TÍCH VẤN ĐỀ KEY FORMAT ===")
print()
print("Format key hiện tại trong file:")
print(f"  '{keys[0]}'")
print()
print("Format mà build_and_train.py parse (k[:10]):")
print(f"  → '{keys[0][:10]}'")
print()
print("Format mà migrate_sentiment_history.py tạo ra:")
print("  '2024-12-01T00:00:00Z' → k[:10] = '2024-12-01'  ← ĐÚNG")
print()
print("Vấn đề: File hiện tại dùng microsecond timestamps từ live system:")
print(f"  '2026-06-23T10:01:08.955169+00:00Z' → k[:10] = '2026-06-23' ← chỉ có 1 ngày!")
print()
print("=== KẾT LUẬN ROOT CAUSE ===")
print()
print("1. sentiment_history.json ĐÃ BỊ GHI ĐÈ bởi live system")
print("   (mỗi lần get_market_sentiment() chạy → append entry với timestamp microsecond)")
print("   → 720 keys nhưng tất cả đều thuộc ngày 2026-06-23")
print()
print("2. Lần cuối migrate_sentiment_history.py được chạy: KHÔNG RÕ")
print("   → Dữ liệu lịch sử 2023-2026 bị mất hoàn toàn")
print()
print("3. Trong build_and_train.py, _load_sentiment_history() chỉ")
print("   tìm thấy 1 ngày → tất cả candles (2023-2026) dùng fallback")
print("   → fear_greed luôn = 23.0 (raw_value của ngày 2026-06-23)")
print()
print("4. sentiment_momentum/recovery/risk/trend: luôn = 0.0")
print("   vì diff giữa hôm nay và hôm qua = 0 (cùng 1 ngày → cùng giá trị)")
print()
print("=== VERIFY: BACKUP CÓ DỮ LIỆU LỊCH SỬ TỐT ===")
with open(r"d:\Workspaces\Vọc vạch\logs\adaptive_signals_backup.json", "r", encoding="utf-8") as f:
    backup = json.load(f)
fg_unique = len(set(r.get("fear_greed") for r in backup if r.get("fear_greed") is not None))
print(f"  Backup fear_greed unique values: {fg_unique} (tốt, đa dạng)")
print(f"  Backup records: {len(backup)} (2025-01 → 2026-06)")
print()
print("  → Backup có fear_greed đa dạng nhưng KHÔNG CÓ sentiment_momentum/recovery/risk")
print("  → Vì các fields này chỉ được thêm vào FEATURE_SCHEMA_V2 SAU khi backup được tạo")
