import sys
import os

# Đảm bảo import được module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_scraper.core.db import closed_positions_col
from scripts.shadow_log import update_outcome

def migrate():
    closed_positions = list(closed_positions_col.find({}))
    print(f"Tìm thấy {len(closed_positions)} lệnh đã đóng trong database.")
    
    updated_count = 0
    for pos in closed_positions:
        pos_id = pos.get("id") or pos.get("coin")
        result = pos.get("result", "LOSS")
        pnl_pct = float(pos.get("pnl_pct", 0.0))
        
        if pos_id:
            updated = update_outcome(
                position_id=pos_id,
                actual_result=result,
                actual_pnl_pct=pnl_pct
            )
            if updated:
                updated_count += 1
                print(f" Đã map lệnh {pos_id} -> {result} (PnL: {pnl_pct}%)")

    print(f"\n✅ Migration hoàn tất. Đã map thành công {updated_count}/{len(closed_positions)} lệnh.")

if __name__ == "__main__":
    migrate()
