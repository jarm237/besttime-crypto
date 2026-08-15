#!/usr/bin/env python3
"""HMR-V3.9–3.13: Event Hypotheses Generation & Freeze.

Defines three prospective event architectures based on characterization findings
and freezes their definitions in a JSON registry.
"""

import json
import sys
import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def run():
    out_dir = REPO_ROOT / "research/historical_market_replay_v3/v3_3_hypotheses"
    out_dir.mkdir(parents=True, exist_ok=True)

    hypotheses = {
        "V3-H1_COMPRESSION_BREAKOUT": {
            "hypothesis_id": "V3-H1",
            "name": "Compression Channel Breakout",
            "expected_horizon": 72,
            "rules": {
                "bollinger_width_max": 0.0120,
                "range_pos_buy_min": 0.80,
                "range_pos_sell_max": 0.20
            },
            "rationale": "Enters when volatility is tightly compressed and price initiates a breakout near the 50-bar channel extremes."
        },
        "V3-H2_ATR_COMPRESSION": {
            "hypothesis_id": "V3-H2",
            "name": "ATR Squeeze Expansion",
            "expected_horizon": 72,
            "rules": {
                "atr_compression_max": 1.05,
                "range_pos_buy_min": 0.75,
                "range_pos_sell_max": 0.25
            },
            "rationale": "Enters when short-term ATR relative to long-term ATR reaches a local squeeze state (ATR ratio < 1.05) and price moves near boundaries."
        },
        "V3-H3_MOMENTUM_ACCEL": {
            "hypothesis_id": "V3-H3",
            "name": "Volatility Slope Breakout",
            "expected_horizon": 32,
            "rules": {
                "bollinger_width_max": 0.0150,
                "ema9_slope_buy_min": 0.0001,
                "ema9_slope_sell_max": -0.0001
            },
            "rationale": "Uses a wider volatility gate but requires directional momentum slope confirmation to initiate entry."
        }
    }

    # Hash the file content
    content_str = json.dumps(hypotheses, sort_keys=True, ensure_ascii=True)
    freeze_hash = hashlib.sha256(content_str.encode()).hexdigest()

    manifest = {
        "schema": "v3_event_hypotheses_v1",
        "freeze_sha256": freeze_hash,
        "hypotheses": hypotheses,
        "rules_immutable": True
    }

    (out_dir / "hypotheses.json").write_text(json.dumps(manifest, indent=2))
    print(f"HMR-V3.13: Event Hypotheses Frozen.")
    print(f"  ✓ Saved registry: {out_dir / 'hypotheses.json'}")
    print(f"  Freeze Hash: {freeze_hash[:16]}...")
    print("\n  GATE: EVENT_HYPOTHESES_FROZEN = PASS")

if __name__ == "__main__":
    run()
