# Signal Detection & Scoring Assessment

> Updated: 2026-07-14
> Scope: `main.py`, `btc_scraper/analysis/`, `btc_scraper/ml_engine/`, `btc_scraper/trading/auto_trader.py`
> Verdict: **Signal detection and AutoTrader local gates are active. SELL threshold semantics have been fixed with side-agnostic `strength`; several orchestrator-level gates still need stronger execution wiring.**
> Superseded operational status: 2026-07-17 system reports mark live execution as **BLOCKED** until Gate A runtime evidence and shadow evidence are complete. See `docs/remediation/System_Status_Report_2026-07-17.md`.

---

## 1. Executive Summary

Luồng chính của hệ thống hiện tại là một pipeline nhiều tầng:

```text
Binance WS / REST candles
  -> MarketAnalystAgent
  -> analyze_market() 15m + MTF 1h/4h/1d
  -> rule signal label: BUY / SELL / WEAK / STRONG / NEUTRAL
  -> score_signal(): internal score 0-100 + display score + meta confidence
  -> CausalContextBridge + CausalGate
  -> RiskManagerAgent + PortfolioManagerAgent
  -> AutoTrader.should_trade()
  -> ExecutionEngine paper/live guarded path
  -> Telegram, Dashboard, shadow logs, counterfactual logs
```

Điểm mạnh lớn nhất là hệ thống không vào lệnh chỉ vì một nhãn kỹ thuật đơn lẻ. AutoTrader đang có local gates thực tế như whitelist, WEAK-signal skip, meta threshold, score threshold, duplicate-position check, correlation check, sizing, VaR/exposure caps và execution guard.

Điểm đã sửa: AutoTrader không còn dùng raw directional score để so threshold. `signal_score` có thêm `strength` side-agnostic (`BUY=strength=score`, `SELL=strength=100-score`), và AutoTrader dùng `signal_score.action` làm nguồn quyết định hướng. Điều này sửa lỗi STRONG SELL bị chặn sai bởi threshold cao.

Điểm còn cần lưu ý sau khi kiểm tra từng bước: một số gate ở tầng orchestrator chưa thật sự được tiêu thụ bởi AutoTrader. `RiskManagerAgent` và `PortfolioManagerAgent` cập nhật `signals_info`, nhưng `ExecutionAgent` gọi AutoTrader bằng `analysis`. Causal anomaly runtime trong `main.py` cũng chạy sau khi orchestrator đã gọi execution, nên chủ yếu là cảnh báo/hiển thị cho chu kỳ đó.

---

## 2. Current Main Flow

### 2.1. Data Ingestion

- `main.py::fetch_and_display()` lấy nến 15m từ `CandleStore` nếu WebSocket khỏe, fallback REST nếu cần.
- Nếu dùng REST fallback, hệ thống lấy thêm 1h, 4h, 1d song song.
- `AgentOrchestrator.run_cycle()` nhận `raw_candles_dict` và `mtf_candles_dict`.

### 2.2. Signal Detection

`MarketAnalystAgent` gọi `analyze_market()` cho 15m và từng MTF.

`analyze_market()` tính:

- Trend/momentum: RSI, EMA9/21, SMA50/200, MACD.
- Volatility: ATR, ATR MA, Bollinger Bands, ADX, Choppiness, realized volatility, HV.
- Liquidity/flow proxy: volume SMA, volume spike, OBV, CMF, MFI.
- Structure: support/resistance, SFP, BOS/CHOCH, higher-high/lower-low.
- Regime: trend/ranging/high-volatility/compression/breakout/panic/pump-risk flags.
- Sentiment: Fear & Greed score/trend/recovery/risk.

Tín hiệu rule-based chính:

| Pattern | Output |
| --- | --- |
| RSI crosses back above 30 with trend confirmation | `STRONG BUY (Confirmed Reversal)` |
| RSI crosses back below 70 | `STRONG SELL (Confirmed Reversal)` |
| Bullish/Bearish SFP | `BUY/SELL (SFP-Liquidity-Sweep)` |
| EMA9/EMA21 crossover with valid trend regime | `BUY/SELL (Crossover)` |
| EMA crossover blocked by low ADX/high choppiness | `NEUTRAL (Trend-Blocked)` |
| Pullback into EMA21-SMA50 in bull trend | `BUY (Pullback-Zone)` |
| SMA50 break in bear trend | `SELL (Break-SMA50)` |
| Ongoing trend without entry trigger | `NEUTRAL (BULLISH/BEARISH/CAUTION)` |

### 2.3. Numeric Scoring

`score_signal()` converts the raw signal label into an internal directional score:

```text
0   = strongest SELL
50  = neutral
100 = strongest BUY
```

Base mapping:

| Raw label | Base score |
| --- | ---: |
| `STRONG BUY` | 90 |
| `BUY` | 70 |
| `WEAK BUY` | 55 |
| `NEUTRAL` | 50 |
| `WEAK SELL` | 45 |
| `SELL` | 30 |
| `STRONG SELL` | 10 |

Context adjustments include:

- Volume spike: +5.
- BUY above SMA200: +5.
- ATR shock: -10.
- Extreme fear on BUY or extreme greed on SELL: usually -20.
- Adaptive model probability, when available: blends probability into score by up to roughly +/-20 points.
- MTF confluence:
  - 1h alignment: +8 bonus or -15 penalty by direction.
  - 4h alignment: +5 bonus or -10 penalty.
  - 1d alignment: +5 bonus or -5 penalty.
- `META_REJECT_THRESHOLD`: optional score penalty.
- `META_HARD_REJECT_THRESHOLD`: optional hard neutralization.
- Drawdown risk block: forces `NEUTRAL`.

Displayed score and trade strength are direction-normalized:

- BUY: `display_score = score`, `strength = score`.
- SELL: `display_score = 100 - score`, `strength = 100 - score`.
- NEUTRAL: `0`.

`strength` is the business field used by AutoTrader gates; `display_score` remains UI-oriented.

### 2.4. Meta Confidence & Sizing

If ML is enabled and model artifacts are present:

- `predict_meta_confidence()` estimates win probability.
- Kelly fraction is computed from `meta_prob` and estimated reward/risk ratio.
- Position size is scaled by:
  - score distance from 50,
  - meta probability or Kelly,
  - volatility multiplier,
  - regime multiplier,
  - risk multiplier from recent drawdown/loss streak.

Important runtime behavior:

- If `meta_confidence` is missing, `AutoTrader._process_signal()` skips trading.
- Auto-trading requires both a strong enough score and meta confidence.

### 2.5. Causal Context

`SignalGeneratorAgent` calls `enhance_signal_with_causal_context()` with `CAUSAL_ALPHA`:

- Default `CAUSAL_ALPHA=0.0` means rule-only safe mode.
- `CRITICAL` causal risk overrides actionable BUY/SELL to `NEUTRAL`.
- `HIGH` or `MEDIUM` causal risk adds warnings but does not block by itself.

`main.py::_run_causal_runtime_pass()` also runs a world-model/anomaly pass. If a structural anomaly is detected, actionable signals receive:

- `causal_anomaly_warning = true`
- `causal_deviation_score`
- a visible `CAUSAL ANOMALY` tag in the signal text.

AutoTrader has an extra conflict gate: high meta confidence plus low score plus causal anomaly is rejected.

### 2.6. Trade Gate

`AutoTrader.should_trade()` requires:

- Coin is in `allowed_coins`.
- Signal contains BUY or SELL in the raw `ana["signal"]` text.
- Signal is not `WEAK`.
- `meta_confidence >= meta_threshold`.
- No conflict gate violation from `causal_anomaly_warning` or `CAUSAL ANOMALY` text.
- Raw `signal_score >= score_threshold`.

Then `_process_signal()` applies:

- Circuit breaker and daily limit.
- No duplicate position for same coin/direction.
- Correlation filter: rejects if correlation with an open position is > 0.75.
- Kelly/risk-based position sizing.
- Portfolio VaR and exposure caps:
  - single coin cap around 15%,
  - sector cap around 35%,
  - total exposure cap around 75%.
- ExecutionEngine guard checks before recording a paper/live execution result.

Current behavior: AutoTrader now checks `sig_score["action"]` first and blocks when it is not `BUY`/`SELL`. This lets upstream gates neutralize trades without relying on raw signal text parsing.

### 2.7. Step-by-Step Verification Result

| Step | Code path checked | Status | Finding |
| --- | --- | --- | --- |
| 1. Ingest 15m candles | `main.py::fetch_and_display()` -> `_get_candles_for_coin()` | PASS | Uses WebSocket/CandleStore when healthy, REST fallback otherwise. |
| 2. Ingest MTF candles | `fetch_and_display()` -> 1h/4h/1d loop | PASS | REST mode fetches MTF in parallel; WebSocket mode fetches sequentially through the same helper. |
| 3. Build analysis | `MarketAnalystAgent.run()` -> `analyze_market()` | PASS | Produces 15m analysis, MTF analysis, HTF trend, and `tf_1h/4h/1d_bull` features. |
| 4. First scoring pass | `analysis/core.py` -> `score_signal()` | PASS / DUPLICATED | `analyze_market()` attaches an initial `signal_score` before MTF features are added. |
| 5. Second scoring pass | `SignalGeneratorAgent.run()` -> `evaluate_signal_score()` | PASS | Re-scores after MTF features are attached, so this is the effective score for AutoTrader. |
| 6. CausalContextBridge | `enhance_signal_with_causal_context()` | PASS / PARTIAL | Adds `causal_decision` and warning metadata. `CRITICAL` changes `sig_score["action"]`, and AutoTrader now honors non-BUY/SELL action. Remaining caveat: context must mutate the same `signal_score` object before AutoTrader runs. |
| 7. Runtime causal anomaly | `main.py::_run_causal_runtime_pass()` | ADVISORY / POST-EXECUTION | Runs after `AgentOrchestrator.run_cycle()`, so after AutoTrader has already been called for the cycle. Useful for display/logging, not a same-cycle pre-trade block. |
| 8. RiskManagerAgent | `RiskManagerAgent.run()` | PARTIAL / NOT WIRED TO EXECUTION | Mutates `context["signals_info"]`, but AutoTrader receives `analysis`; changes do not directly block `_process_signal()`. |
| 9. PortfolioManagerAgent | `PortfolioManagerAgent.run()` | PARTIAL / NOT WIRED TO EXECUTION | MVO weights are written to `signals_info`, but AutoTrader sizes from `ana["signal_score"]` and its own risk/exposure logic. |
| 10. RLExitAgent | `RLExitAgent.run()` | PASS / METADATA | Loads model and marks `rl_model_loaded`; exit recommendations are handled elsewhere, not an entry gate. |
| 11. AutoTrader local gate | `auto_trader.should_trade()` and `_process_signal()` | PASS | Real entry gate is here: whitelist, WEAK skip, meta threshold, `strength` threshold, action gate, duplicate/correlation/circuit/exposure checks. SELL/raw-score threshold bug fixed. |
| 12. ExecutionEngine paper | `ExecutionEngine.submit_paper()` | PASS | Liquidity, slippage, risk guard, order type selection and fill simulation are active. |
| 13. ExecutionEngine live | `ExecutionEngine.submit_live()` | CONDITIONAL | Has live guard and legacy guard, but liquidity is candle-derived and selected order type is still executed as market buy/sell. |
| 14. Outputs | `latest_signals.json`, Telegram, shadow log, counterfactual | PASS | Latest signals and alerts happen after orchestrator; shadow logging happens inside `ExecutionAgent`. |

### 2.8. Enforcement Gaps Found

1. **Runtime causal anomaly is post-execution in the current cycle.**
   `main.py` runs `_run_causal_runtime_pass()` after `orchestrator.run_cycle()`, and `ExecutionAgent` is part of that run cycle.

2. **RiskManagerAgent does not directly gate execution.**
   It edits `signals_info`; AutoTrader uses `analysis`. The separate risk block inside `score_signal()` can affect `sig_score["action"]`, but AutoTrader does not check that field.

3. **PortfolioManagerAgent MVO allocation is not consumed by AutoTrader.**
   AutoTrader computes position size from `ana["signal_score"]`, TP/SL, Kelly and exposure manager, not from `signals_info["portfolio_weight"]`.

4. **Causal anomaly conflict gate still depends on timing.**
   AutoTrader can block `causal_anomaly_warning`, but the runtime anomaly tag in `main.py` is added after execution for the same cycle.

---

## 3. Assessment

### Strengths

- Detection and scoring are layered: no single indicator directly creates a final paper/live execution.
- AutoTrader has real local gates for whitelist, WEAK signals, meta threshold, side-agnostic strength threshold, action gate, duplicate positions, correlation, sizing and execution guard.
- MTF confluence is explicit and asymmetric; 1h disagreement is penalized more strongly than 4h/1d.
- Causal layer is safe by default for context generation, and AutoTrader now honors `sig_score["action"]` when it is neutralized before execution.
- AutoTrader refuses to trade without meta confidence, reducing accidental rule-only live entries.
- Signal tracking persists TP/SL status for active signals, improving feedback and alert quality.

### Weaknesses / Risks

- `analysis/core.py` is still a large monolithic strategy file, making subtle rule interactions hard to test.
- Score starts from text labels, so label wording changes can alter downstream behavior.
- `MetaDecisionEngine` exists, but the main production path primarily uses `score_signal()` + `meta_confidence`, not the full posterior decision in every trade path.
- Causal anomaly tagging in `main.py` occurs after AutoTrader has already run for the cycle.
- `RiskManagerAgent` and `PortfolioManagerAgent` update `signals_info`, but `ExecutionAgent` passes `analysis` to AutoTrader.
- Phase 10 live execution remains conditional: paper/simulation guard path is stronger than full live order-style routing.

---

## 4. Recommended Updates

### P0 — Finish Gate Wiring Beyond AutoTrader Local Checks

AutoTrader now consumes `signal_score.action` and side-agnostic `strength`. Next, add an explicit `trade_allowed` / `block_reason` contract so RiskManagerAgent, PortfolioManagerAgent and runtime causal anomaly can block or size trades through `analysis`, not only `signals_info`.

### Done — Clarify SELL Threshold Semantics

AutoTrader now uses `strength` instead of raw directional score, so STRONG SELL and STRONG BUY are treated symmetrically by `AUTO_TRADE_SCORE_THRESHOLD`.

### P1 — Split Signal Detection Modules

Refactor `analysis/core.py` into smaller units:

- `indicator_snapshot.py`
- `patterns.py`
- `signal_finalize.py`
- `tp_sl.py`
- `historical_analyzer.py`

This reduces regression risk when adding strategies.

### P1 — Make Scoring Reasons First-Class

`score_signal()` accumulates reason text internally but does not return it in the final dict. Returning `reason` would make Telegram, dashboard, audit logs and backtests easier to explain.

### P1 — Align Decision Engine Usage

Either route production decisions through `MetaDecisionEngine.decide_with_provider()` or clearly keep it as a research/shadow component. Right now both concepts exist, which can confuse operators.

### P2 — Add Focused Tests

Recommended tests:

- STRONG SELL should pass/skip according to side-aware score semantics.
- MTF disagreement should apply the expected delta for BUY and SELL.
- `CAUSAL ANOMALY` plus low score should block even with high meta confidence.
- Missing meta confidence should never trade.
- WEAK BUY/SELL should never auto-trade.

---

## 5. Current Readiness

```text
Signal detection: PASS
Signal scoring: PASS - side-agnostic strength added
Paper auto-trade gating: PASS
Causal safe gate: PASS for pre-execution `signal_score.action` neutralization; runtime anomaly timing remains partial
Risk/Portfolio orchestrator gates: PARTIAL - update signals_info, not analysis
Live execution readiness: BLOCKED pending Gate A/shadow evidence
Maintainability: NEEDS REFACTOR
```

The 2026-07-14 signal-flow assessment remains valid for local scoring/gating semantics. The newer 2026-07-17 operational reports supersede its live-readiness line: live execution is blocked until Gate A runtime evidence, shadow evidence, and Phase 5 readiness are satisfied.
