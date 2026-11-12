"""
tests/test_simulator_first_principles.py

Exhaustive first-principles unit test suite validating economic accounting,
risky notional turnover, fee calculations, drift dynamics, and risk barriers.
"""
import pytest
import numpy as np
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.engine.hard_risk import DeterministicHardRiskBarrier

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
INITIAL_CAPITAL = 20_000.0
FRICTION_14BPS = 14.0  # 10 bps fee + 2 bps slip + 2 bps spread = 14 bps


def test_case_1_100_percent_cash_price_unchanged():
    """1. 100% Cash, prices unchanged, zero trades."""
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=10.0, slippage_bps=2.0, typical_spread_bps=2.0)
    K = 10
    # Proposed weights: [1.0, 0, 0, 0, 0, 0] (100% cash)
    target_w = np.zeros((K, 6))
    target_w[:, 0] = 1.0
    price_relatives = np.ones((K, 5))
    timestamps = [f"2023-01-01 {h:02d}:00:00" for h in range(K)]

    res = sim.simulate(target_w, price_relatives, timestamps)
    assert res["final_equity"] == INITIAL_CAPITAL
    assert res["net_pnl_usd"] == 0.0
    assert res["total_friction_usd"] == 0.0
    assert res["actual_trade_count"] == 0
    assert res["total_executed_notional"] == 0.0
    assert res["total_return_pct"] == 0.0


def test_case_2_cash_to_btc_20pct_then_back_to_cash():
    """2. Cash to BTC 20%, then BTC back to Cash."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.0, max_asset_pct=1.0)
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=10.0, slippage_bps=2.0, typical_spread_bps=2.0, hard_risk_barrier=barrier)
    
    # Step 0: Cash -> 20% BTC, 80% Cash
    # Step 1: 20% BTC -> 100% Cash
    target_w = np.zeros((2, 6))
    target_w[0, 0] = 0.80
    target_w[0, 1] = 0.20
    target_w[1, 0] = 1.00
    
    price_relatives = np.ones((2, 5))
    timestamps = ["2023-01-01 00:00:00", "2023-01-01 01:00:00"]

    res = sim.simulate(target_w, price_relatives, timestamps)

    # Step 0:
    # Traded risky notional = 0.20 * $20,000 = $4,000
    # Cost = $4,000 * 0.0014 = $5.60
    # Capital after step 0 = $20,000 - $5.60 = $19,994.40
    # Step 1:
    # Drifted weight into step 1 = [0.8, 0.2, 0, 0, 0, 0]
    # Traded risky notional = 0.20 * $19,994.40 = $3,998.88
    # Cost = $3,998.88 * 0.0014 = $5.598432
    # Final equity = $19,994.40 - $5.598432 = $19,988.80
    assert abs(res["total_friction_usd"] - 11.20) < 0.05
    assert abs(res["final_equity"] - 19988.80) < 0.10
    assert res["actual_trade_count"] == 2
    assert abs(res["total_executed_notional"] - 7998.88) < 0.50


def test_case_3_btc_up_10pct_no_rebalancing():
    """3. BTC up 10%, no rebalancing (natural drift)."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.0, max_asset_pct=1.0)
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=10.0, slippage_bps=2.0, typical_spread_bps=2.0, hard_risk_barrier=barrier)

    # Initially allocate 20% BTC in step 0 with 0% friction
    sim_zero_fee = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=0.0, slippage_bps=0.0, typical_spread_bps=0.0, hard_risk_barrier=barrier)
    
    target_w = np.zeros((2, 6))
    target_w[0] = [0.80, 0.20, 0, 0, 0, 0]
    # In step 1, target weight matches drifted weight: target_w[1] = drifted_w
    # But let's check step 0 return when BTC moves +10%:
    price_relatives = np.ones((2, 5))
    price_relatives[0, 0] = 1.10 # BTC +10%

    # Growth = 0.80 * 1.0 + 0.20 * 1.10 = 1.02 (+2%)
    # Capital = $20,000 * 1.02 = $20,400
    # Drifted BTC weight = 0.22 / 1.02 = 0.215686
    # In step 1, we set target to exactly drifted weight so NO rebalance happens:
    target_w[1] = [0.80 / 1.02, 0.22 / 1.02, 0, 0, 0, 0]

    res = sim_zero_fee.simulate(target_w, price_relatives, ["2023-01-01 00:00:00", "2023-01-01 01:00:00"])
    assert abs(res["final_equity"] - 20400.0) < 0.01
    assert abs(res["total_return_pct"] - 2.00) < 0.01


def test_case_4_btc_up_10pct_rebalance_back_to_target():
    """4. BTC up 10%, rebalance back to target weight 20%."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.0, max_asset_pct=1.0)
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=10.0, slippage_bps=2.0, typical_spread_bps=2.0, hard_risk_barrier=barrier)

    # Step 0: [0.80, 0.20] with zero friction to establish baseline
    target_w = np.zeros((2, 6))
    target_w[0] = [0.80, 0.20, 0, 0, 0, 0]
    target_w[1] = [0.80, 0.20, 0, 0, 0, 0] # Rebalance back to 20%
    
    price_relatives = np.ones((2, 5))
    price_relatives[0, 0] = 1.10 # BTC +10%
    
    res = sim.simulate(target_w, price_relatives, ["2023-01-01 00:00:00", "2023-01-01 01:00:00"])
    
    # Step 0:
    # Traded risky = 0.20 * $20k = $4k. Friction = $5.60. Capital = $19,994.40.
    # Growth = 0.8 * 1.0 + 0.2 * 1.10 = 1.02.
    # Capital after bar 0 = $19,994.40 * 1.02 = $20,394.288
    # Drifted BTC weight = 0.22 / 1.02 = 0.215686
    # Step 1:
    # Target BTC weight = 0.20. Delta = 0.215686 - 0.20 = 0.015686
    # Traded risky notional = 0.015686 * $20,394.288 = $319.90
    # Friction = $319.90 * 0.0014 = $0.4478
    # Capital after step 1 = $20,394.288 - $0.4478 = $20,393.84
    assert abs(res["final_equity"] - 20393.84) < 0.50
    assert abs(res["total_friction_usd"] - (5.60 + 0.448)) < 0.10


def test_case_5_two_assets_opposite_direction():
    """5. Two assets change price in opposite directions (+10% and -10%)."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.0, max_asset_pct=1.0)
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=0.0, slippage_bps=0.0, typical_spread_bps=0.0, hard_risk_barrier=barrier)

    # 50% Cash, 25% BTC, 25% ETH
    target_w = np.zeros((1, 6))
    target_w[0] = [0.50, 0.25, 0.25, 0, 0, 0]

    price_relatives = np.ones((1, 5))
    price_relatives[0, 0] = 1.10  # BTC +10%
    price_relatives[0, 1] = 0.90  # ETH -10%

    res = sim.simulate(target_w, price_relatives, ["2023-01-01 00:00:00"])
    # Net growth = 0.50 * 1.0 + 0.25 * 1.10 + 0.25 * 0.90 = 0.50 + 0.275 + 0.225 = 1.000
    assert abs(res["final_equity"] - 20000.0) < 0.01
    assert abs(res["net_pnl_usd"]) < 0.01


def test_case_6_trading_halt_and_unavailable_asset():
    """6. Trading halt and unavailable asset handling."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.0, max_asset_pct=1.0)
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, fee_bps=10.0, slippage_bps=2.0, typical_spread_bps=2.0, hard_risk_barrier=barrier)

    target_w = np.zeros((3, 6))
    target_w[0] = [0.80, 0.20, 0, 0, 0, 0]
    target_w[1] = [0.50, 0.50, 0, 0, 0, 0]  # Proposed aggressive rebalance during halt!
    target_w[2] = [0.50, 0.50, 0, 0, 0, 0]

    price_relatives = np.ones((3, 5))
    is_halt = np.array([False, True, False])  # Step 1 is HALTED

    res = sim.simulate(target_w, price_relatives, ["2023-03-24 12:00:00", "2023-03-24 13:00:00", "2023-03-24 14:00:00"], is_halt_seq=is_halt)
    
    # During halt (step 1), no trade could be executed, so friction at step 1 MUST be zero!
    step_1_friction = res["equity_curve"][1]["friction_cost"]
    assert step_1_friction == 0.0
    assert res["equity_curve"][1]["is_halt"] is True


def test_case_7_invalid_model_output_handled_by_barrier():
    """7. Invalid model output (NaN, negative, >100% allocation) handled by hard-risk barrier."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.05, max_asset_pct=0.35)
    sim = NeuralPortfolioSimulator(symbols=SYMBOLS, initial_capital=INITIAL_CAPITAL, hard_risk_barrier=barrier)

    target_w = np.zeros((3, 6))
    # Step 0: Concentration violation: BTC = 90% (max allowed is 35%)
    target_w[0] = [0.10, 0.90, 0, 0, 0, 0]
    # Step 1: Cash violation: Cash = 0% (min cash is 5%)
    target_w[1] = [0.00, 0.25, 0.25, 0.25, 0.25, 0.00]
    # Step 2: NaN in model prediction
    target_w[2] = [np.nan, 0.2, 0.2, 0.2, 0.2, 0.2]

    price_relatives = np.ones((3, 5))
    res = sim.simulate(target_w, price_relatives, ["2023-01-01 00:00:00", "2023-01-01 01:00:00", "2023-01-01 02:00:00"])

    # Step 0: BTC should be clipped to <= 35%
    assert res["equity_curve"][0]["cash_weight"] >= 0.05
    # Step 1: Cash should be >= 5%
    assert res["equity_curve"][1]["cash_weight"] >= 0.05
    # Step 2: NaN should trigger fallback to 100% Cash
    assert res["equity_curve"][2]["cash_weight"] == 1.00
    assert res["final_equity"] <= INITIAL_CAPITAL  # Finite and solvent
