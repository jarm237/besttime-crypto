r"""N1.4 — Greenfield Economic-First Alpha Discovery Package.

Implements:
- `acquisition.py`: Phase D raw historical data acquisition & SHA-256 `.CHECKSUM` verification
  for Binance COIN-M (`SYMUSD_YYMMDD`) and USD-M (`SYMUSDT_YYMMDD`) Dated Quarterly Delivery Futures
  across 17 contract maturities (2022 Q1 through 2025 Q4 / 2026 Q1 front-next curve, strictly capped at
  2025-12-31 23:00 UTC) and 8 underlying assets (`BTC, ETH, BNB, XRP, ADA, LINK, LTC, SOL`), joined
  with verified Spot 1h klines and Coinbase `USDT-USD` numeraire conversion under a strict PIT contract.
- `falsification.py`: Phase E Economic Falsification before neural training for Candidate H-1
  (`Dated Quarterly Delivery Futures Basis Carry & Term-Structure Convergence`) and Candidate H-2
  (`Multi-Day Cross-Sectional Forced-Deleveraging Liquidity Provision`), computing all 13 mandatory
  economic and risk metrics plus the exact 5-term trade-ledger gross/net bridge.
- `neural_pilot.py`: Phase F Bounded Stateful Term-Structure Neural Policy (`TermStructureCarryPolicy`)
  trained only on the economically feasible mechanism (`H-1`), with explicit `[current_weight, cash]`
  state, HOLD gating, external deterministic risk/margin controls, and direct comparison against the
  hypothesis-specific non-neural baseline and exposure-matched passive benchmark.
"""
