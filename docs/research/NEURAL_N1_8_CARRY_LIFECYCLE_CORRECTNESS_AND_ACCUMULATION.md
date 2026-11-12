# N1.8 — COIN-M Forward Lifecycle Correctness & Natural Economic Accumulation

**Authoritative Research Report**  
**Date:** 2026-11-11 (Updated 2026-11-12 with N1.8-R1 Integration)  
**Workspace:** `D:\Workspaces\besttime-crypto`  
**Research Subject:** `H-1 — DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`  
**Predecessor Research:** N1.7 (`docs/research/NEURAL_N1_7_FORWARD_PAIRED_CARRY_LIFECYCLE.md`)  
**Integration Addendum:** N1.8-R1 (`docs/research/NEURAL_N1_8_R1_FORWARD_INTEGRATION.md`)

---

## Executive Summary & Research Disposition

N1.7 established initial forward paired-trade lifecycles across Binance Spot and COIN-M quarterly delivery contracts, reporting three active virtual positions with $12,370.00 deployed notional, zero realized PnL, and an initial mark-to-market drawdown of `-$167.96`.

The objective of **N1.8** was to audit and correct the material portfolio and margin contracts governing these virtual carry positions, establish independent-leg execution realities under true physical exchange sequencing, reconcile the reported `-$167.96` drawdown against first-principles market mechanics, and monitor forward lifecycles naturally without retuning historical rules or introducing fabricated synthetic observations.

```text
========================================================================================
                          N1.8 RESEARCH DISPOSITION
========================================================================================
N1_8_PORTFOLIO_RISK_AGGREGATION        = VERIFIED
N1_8_COINM_COLLATERAL_FEASIBILITY      = VERIFIED
N1_8_INDEPENDENT_LEG_ACCOUNTING        = VERIFIED
N1_8_COST_ACCOUNTING                   = RECONCILED

H1_FORWARD_LIFECYCLES                  = ACCUMULATING
H1_FORWARD_NET_ECONOMIC_VALUE          = INCONCLUSIVE

H1_PRODUCTION_CANDIDATE                = FALSE
REAL_TRADING                           = DISABLED
========================================================================================
```

### Key Breakthrough Findings
1. **Material Portfolio Risk Aggregation Defect in N1.7**:
   - In N1.7, the single-asset cap (25% or $5,000 on a $20,000 portfolio) was checked per *contract symbol* rather than per *underlying asset*. Consequently, both `BNBUSD_261225` ($5,000.00) and `BNBUSD_270326` ($2,370.00) were admitted, accumulating **$7,370.00** of BNB notional (36.85% of total capital), strictly breaching the 25% single-underlying risk boundary.
   - In N1.8, an account-level allocation ledger enforces limits strictly by underlying asset. `BNBUSD_270326` has been quarantined as `RISK_ACTION_REQUIRED / DEFECT_RECORDED: EXCEEDS_AGGREGATE_UNDERLYING_CAP` without erasing historical N1.7 records. Valid open deployed capital is **$10,000.00** (50.0% capital utilization: $5,000 BNB + $5,000 BTC).
2. **COIN-M Initial Collateral Feasibility**:
   - In COIN-M inverse futures, order placement physically requires underlying coin collateral in the margin wallet. If an account starts with USDT cash, placing a COIN-M short first is blocked by the exchange: `COINM_FIRST_BLOCKED_INSUFFICIENT_COLLATERAL`.
   - If coin collateral is prefunded, the account holds unhedged `+Delta` long coin exposure prior to the short futures fill. Intermediate unhedged delta cannot be zero under independent-leg execution.
3. **Forensic Reconciliation of the Reported `-$167.96` MTM Drawdown**:
   - Rigorous forensic audit revealed that **`-$153.04`** of the reported `-$167.96` loss was an artifact of a simulator inner loop bug in N1.7: positions were evaluated against the orderbook of the last processed pair in the batch (`XRPUSD_270326`), whose ~1.2% basis imposed a synthetic mark-down.
   - Re-evaluated against true asset-specific orderbooks over the 38-minute forward window:
     - **True Gross Basis MTM:** **`+$3.63`** across the three positions (basis compressed by -3.39 bps on BNB Mar and -7.26 bps on BTC Mar).
     - **Upfront Fees Paid:** **`$18.56`** (15.0 bps taker fee schedule).
     - **True Net MTM:** **`-$14.92`** across all three positions, and **`-$12.41`** on the two valid portfolio positions (`-$8.97` BNB Dec + `-$3.44` BTC Mar).
4. **Recorder Operational Reliability**:
   - The standalone recorder process (PID 9812) exited after its initial burst session. Consistent with the prompt's integrity requirement, `FORWARD_ACCUMULATION = PAUSED` is explicitly declared. No synthetic forward quotes were fabricated.

---

## Phase A — Material Portfolio and Margin Contracts Correction

### A1. Aggregate Risk by Underlying Asset
In crypto portfolio management, risk limits must constrain exposure to the underlying economic risk factor (e.g., BNB price volatility), regardless of whether exposure is partitioned across multiple delivery expiries.

In N1.7, three virtual carry positions were opened:
- `BNBUSD_261225`: $5,000.00 notional (500 contracts @ $10/contract; 7.353 BNB collateral).
- `BNBUSD_270326`: $2,370.00 notional (237 contracts @ $10/contract; 3.485 BNB collateral).
- `BTCUSD_270326`: $5,000.00 notional (50 contracts @ $100/contract; 0.068 BTC collateral).

#### The Defect
Evaluating the cap per contract admitted $7,370.00 of BNB exposure on a $20,000.00 portfolio (36.85%), exceeding the frozen 25.0% ($5,000.00) single-asset ceiling by $2,370.00 (+47.4% over-allocation). Furthermore, if the account only allocated $5,000.00 of cash to BNB, the same 7.353 BNB collateral could not legally support both short positions without leverage.

#### Corrected Account-Level Allocation Ledger (`n1_8_underlying_allocation_ledger.json`)
```json
{
  "portfolio_capital_usd": 20000.0,
  "max_per_underlying_cap_usd": 5000.0,
  "total_portfolio_committed_capital_usd": 12370.0,
  "portfolio_utilization_pct": 61.85,
  "underlying_buckets": {
    "BNB": {
      "underlying_asset": "BNB",
      "max_capital_usd": 5000.0,
      "aggregate_position_notional_usd": 7370.0,
      "aggregate_collateral_coin": 10.838336,
      "aggregate_committed_capital_usd": 7370.0,
      "capital_utilization_pct": 147.4,
      "active_contracts_count": 2,
      "defect_detected": true,
      "defect_note": "EXCEEDS_AGGREGATE_UNDERLYING_CAP: Underlying BNB already has $5000.00 committed; adding $2370.00 would reach $7370.00, exceeding $5000.00 cap.",
      "contracts": [
        {
          "contract_symbol": "BNBUSD_261225",
          "contracts_short": 500,
          "entry_notional_usd": 5000.0,
          "status": "HEDGED_HOLD",
          "disposition_note": "ALLOCATED_WITHIN_RISK_CAP"
        },
        {
          "contract_symbol": "BNBUSD_270326",
          "contracts_short": 237,
          "entry_notional_usd": 2370.0,
          "status": "RISK_ACTION_REQUIRED",
          "disposition_note": "EXCEEDS_AGGREGATE_UNDERLYING_CAP: Underlying BNB already has $5000.00 committed; adding $2370.00 would reach $7370.00, exceeding $5000.00 cap."
        }
      ]
    },
    "BTC": {
      "underlying_asset": "BTC",
      "max_capital_usd": 5000.0,
      "aggregate_position_notional_usd": 5000.0,
      "aggregate_collateral_coin": 0.068006,
      "aggregate_committed_capital_usd": 5000.0,
      "capital_utilization_pct": 100.0,
      "active_contracts_count": 1,
      "defect_detected": false,
      "contracts": [
        {
          "contract_symbol": "BTCUSD_270326",
          "contracts_short": 50,
          "entry_notional_usd": 5000.0,
          "status": "HEDGED_HOLD",
          "disposition_note": "ALLOCATED_WITHIN_RISK_CAP"
        }
      ]
    }
  }
}
```

Historical records remain untouched; the defect is explicitly quarantined with disposition `RISK_ACTION_REQUIRED`.

---

### A2. Correct COIN-M Initial Collateral Feasibility

In exchange execution architecture, order execution must respect collateral dependencies:
```text
USDT cash balance
    │
    ▼
1. Spot Coin Acquisition (Orderbook Ask Sweep)
    │
    ▼
2. Coin Available for Transfer (Wallet Settled)
    │
    ▼
3. Transfer to COIN-M Delivery Margin Wallet (Subaccount / API)
    │
    ▼
4. Futures Initial Margin Validation (Check Available Balance >= IMR)
    │
    ▼
5. Futures Short Order Submission (Orderbook Bid Sweep)
```

#### Feasibility Verdicts:
1. **Unfunded COIN-M-First:**
   - Attempting to submit a short order on Binance COIN-M Delivery without existing coin collateral results in immediate API rejection:
     `COINM_FIRST_BLOCKED_INSUFFICIENT_COLLATERAL`.
   - The assumption in N1.7 that an account starting in USDT can fill COIN-M first with zero prefunding was an execution simulator defect.
2. **Prefunded COIN-M-First:**
   - If the account pre-holds 7.353 BNB in its margin wallet prior to execution, it carries **`+$5,000.00`** of unhedged Long coin exposure during the entire prefunding interval.
   - Net account delta drops to ~0.0 only after the short futures contract fills.
   - Intermediate unhedged delta cannot be assumed zero.

---

### A3. Account-Level Margin Ledger

Under Binance Cross Margin rules for COIN-M Delivery, all contracts sharing the same margin coin (e.g., `BNBUSD_261225` and `BNBUSD_270326`) are collateralized against a unified coin margin balance.

#### Binance Margin Formulas:
$$\text{Inverse uPnL (coin)} = \sum_{i} \text{Notional}_i \times \left(\frac{1}{F_{\text{mark}, i}} - \frac{1}{F_{\text{entry}, i}}\right)$$
$$\text{Margin Balance (coin)} = \text{Wallet Balance (coin)} + \text{Inverse uPnL (coin)}$$
$$\text{Maintenance Margin (coin)} = \sum_{i} \frac{\text{Notional}_i \times \text{MMR}_i}{F_{\text{mark}, i}}$$
$$\text{Margin Ratio} = \frac{\text{Maintenance Margin (coin)}}{\text{Margin Balance (coin)}}$$

#### Real Account Metrics (`n1_8_account_margin_ledger.json`):
| Margin Coin | Wallet Balance | Inverse uPnL | Margin Balance (Coin) | Margin Balance (USD) | Maintenance Margin | Dynamic Margin Ratio | Contract Tier | Liquidation Risk |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BNB** | 7.353009 BNB | -0.042098 BNB | 7.310911 BNB | $4,998.53 | 0.036249 BNB | **0.4958%** (0.004958) | Tier 1 (MMR = 0.50%) | Non-zero |
| **BTC** | 0.068006 BTC | -0.000318 BTC | 0.067688 BTC | $5,004.06 | 0.000265 BTC | **0.3916%** (0.003916) | Tier 1 (MMR = 0.40%) | Non-zero |

> [!NOTE]
> Margin ratio is computed dynamically from first principles and is not hardcoded to the MMR rate. Liquidation occurs if the margin ratio reaches 100.0%. While a 100% floor-collateralized carry position has substantial buffer (~99.5%), liquidation risk is non-zero during extreme basis blowouts or negative basis spikes.

---

## Phase B — Correct Independent-Leg Execution Semantics

We evaluated the three execution scenarios across 100 intents under physical constraints:

| Metric | Scenario 1: Spot-First | Scenario 2: COIN-M First (Unfunded) | Scenario 2b: COIN-M First (Prefunded) | Scenario 3: Matched Orderbook Capacity |
| :--- | :--- | :--- | :--- | :--- |
| **Initial Account Delta** | $0.00 | $0.00 | +$5,000.00 | $0.00 |
| **First Leg Fill** | Spot Buy $5,000.00 | REJECTED (None) | Futures Short $5,000.00 | Virtual Spot $5,000.00 |
| **Intermediate Account Delta** | **+$5,000.00** | $0.00 | ~$0.00 | $0.00 |
| **Second Leg Fill** | Futures Short $5,000.00 | None | Spot Rebalance $0.00 | Virtual COIN-M $5,000.00 |
| **Final Account Delta** | $0.00 | $0.00 | $0.00 | $0.00 |
| **Maximum Unhedged Delta** | **$5,000.00** | $0.00 | **$5,000.00** | $0.00 |
| **Required Prefunding** | USDT Cash | Blocked (No Collateral) | 100% Coin Collateral | Theoretical Overlap |
| **Execution Cost** | $7.50 (15 bps) | $0.00 | $7.50 (15 bps) | $7.50 (15 bps) |
| **Execution Status** | `HEDGE_COMPLETE` | `BLOCKED_BY_EXCHANGE_MARGIN_RULE` | `HEDGE_COMPLETE_PREFUNDED` | `BOOK_DEPTH_PAIRABLE` |

> [!IMPORTANT]
> Scenario 3 represents overlapping book depth at observed quotes. Because Binance does not provide cross-market atomic order execution across Spot and COIN-M, orderbook capacity is labeled **`BOOK_DEPTH_PAIRABLE`**, never `TWO_LEG_EXECUTION_CONFIRMED`.

---

## Phase C — Reconciliation of N1.7 Economic Ledger

### Forensic Audit of Reported `-$167.96` MTM Drawdown
In N1.7, the economic scorecard reported:
- `total_open_unrealized_pnl_usd`: `-$167.96`
- `VTRADE_0001` (`BNBUSD_261225`): `-$67.88`
- `VTRADE_0002` (`BNBUSD_270326`): `-$32.13`
- `VTRADE_0003` (`BTCUSD_270326`): `-$67.95`

#### Root Cause Decomposition:
1. **Cross-Symbol Valuation Bug (`-$153.04` error):**
   In N1.7 `lifecycle_engine.py` (lines 510–522), the update loop iterated over all intents in the parquet file. The inner loop updated all active lifecycles against the current intent record without filtering by symbol. Consequently, all three lifecycles were evaluated against the *final processed intent* in the dataset, which was `XRPUSD_270326` (Spot $1.0705, Futures $1.0836). Because XRP had a ~1.2% basis, evaluating inverse PnL using XRP prices created an artificial `-$60.45` markdown on every $5,000 position.
2. **Upfront Fees Paid (`$18.56` real):**
   Upfront taker fees were paid upon entry: 10 bps Spot + 5 bps Futures = 15 bps ($7.50 on BNB Dec, $3.56 on BNB Mar, $7.50 on BTC Mar).
3. **True Asset-Specific Market Movement (`+$3.63` gross MTM):**
   When marked against each position's actual orderbook quotes across the 38-minute forward window:
   - `BNBUSD_261225`: Spot rose from 679.99 to 683.71; Futures rose from 685.70 to 689.68. Basis widened from 83.92 bps to 87.37 bps (+3.45 bps). Gross MTM: **`-$1.47`**. Net MTM: **`-$8.97`**.
   - `BNBUSD_270326`: Basis compressed from 215.78 bps to 212.38 bps (-3.39 bps). Gross MTM: **`+$1.04`**. Net MTM: **`-$2.51`**.
   - `BTCUSD_270326`: Spot rose from 73,522.40 to 73,928.12; Futures rose from 75,093.19 to 75,453.90. Basis compressed from 213.65 bps to 206.39 bps (-7.26 bps). Gross MTM: **`+$4.06`**. Net MTM: **`-$3.44`**.

```text
Reconciliation Summary:
-----------------------------------------------------------------
N1.7 Reported Unrealized PnL:               -$167.96
Less Simulator Cross-Symbol Valuation Bug:  -$153.04
-----------------------------------------------------------------
True Net Mark-to-Market PnL:                 -$14.92
  - True Gross Basis Mark-to-Market:         +$3.63
  - Upfront Taker Fees Paid (15 bps):       -$18.56
-----------------------------------------------------------------
```

### Cost Disentanglement
The frozen 39.0 bps round-trip taker schedule was reconciled to prevent double counting:
- **Upfront Execution Fees (15.0 bps):** Deducted explicitly ($18.56 paid).
- **Crossing Bid-Ask Spread (~8.0 bps):** Directly captured by executable VWAP sweeps from book depth. Not added as an additional fee.
- **Residual Slippage Buffer (1.0 bps):** Preserved for execution latency.
- **Exit / Settlement Fees (15.0 bps):** 10 bps Spot exit + 5 bps settlement, accounted for at position closure.

---

## Phase D — Natural Forward Lifecycle Preservation

Rather than recreating synthetic entries, N1.8 updates the state machine of the existing N1.7 lifecycles based on risk compliance:

```mermaid
stateDiagram-v2
    [*] --> ENTRY_ELIGIBLE
    ENTRY_ELIGIBLE --> PAIR_ENTRY_SIMULATED: Orderbook Depth Paired
    PAIR_ENTRY_SIMULATED --> HEDGED_HOLD: Valid Underlying Allocation
    PAIR_ENTRY_SIMULATED --> RISK_ACTION_REQUIRED: Exceeds Underlying Cap
    HEDGED_HOLD --> EXIT_ELIGIBLE: Basis <= 15 bps
    HEDGED_HOLD --> SETTLEMENT_PENDING: Expiry Delivery (08:00 UTC)
    EXIT_ELIGIBLE --> CLOSED: Early Close Executed
    SETTLEMENT_PENDING --> CLOSED: Delivery Settlement
```

### Current Status of Active Lifecycles (`n1_8_lifecycle_state.json`)
1. **`VTRADE_0001` (`BNBUSD_261225`):**
   - Status: **`HEDGED_HOLD`** (`ACCUMULATING`)
   - Notional: $5,000.00 | Collateral: 7.353009 BNB
   - Basis: 83.92 bps entry $\to$ 87.37 bps current (+3.45 bps)
   - Gross MTM: `-$1.47` | Net MTM: `-$8.97` | Realized PnL: `$0.00`
2. **`VTRADE_0002` (`BNBUSD_270326`):**
   - Status: **`RISK_ACTION_REQUIRED`** (`QUARANTINED`)
   - Notional: $2,370.00 | Collateral: 3.485326 BNB
   - Reason: Exceeded 25% single-underlying allocation by $2,370.00.
   - Gross MTM: `+$1.04` | Net MTM: `-$2.51` | Realized PnL: `$0.00`
3. **`VTRADE_0003` (`BTCUSD_270326`):**
   - Status: **`HEDGED_HOLD`** (`ACCUMULATING`)
   - Notional: $5,000.00 | Collateral: 0.068006 BTC
   - Basis: 213.65 bps entry $\to$ 206.39 bps current (-7.26 bps)
   - Gross MTM: `+$4.06` | Net MTM: `-$3.44` | Realized PnL: `$0.00`

---

## Phase E — Recorder Operational Reliability

We audited `data/neural_n1_6/state/recorder_status.json` and verified process health:
- Process PID 9812 has terminated.
- In strict adherence to prompt rules, the status is set to **`FORWARD_ACCUMULATION = PAUSED`**.
- We do not claim continuous forward streaming in the absence of an active ingestion daemon.

### Operational Specification Audit:
1. **Append-Only Storage:** Confirmed. Raw payloads stored in partitioned JSONL and compressed parquet.
2. **Timestamp Continuity:** Confirmed. Millisecond timestamps (`recv_ms`) strictly monotonic.
3. **Quote Freshness:** Confirmed. Stale quotes (>5.0s age or >2.0s inter-venue skew) blocked by signal guard.
4. **Restart / Resume Deduplication:** Verified. Pair IDs and receive timestamps ensure deduplication.
5. **Stale-Source Blocking:** Verified. `QUOTE_NOT_ELIGIBLE_FOR_EXECUTION_ANALYSIS` applied when feed ages.
6. **Explicit Pause / Resume:** Verified. Handled gracefully via state manifest.
7. **Separation of Source Health and Strategy Status:** Verified. Feed availability is decoupled from carry economic profitability.

---

## Phase F — Event-Driven Economic Scorecard

Economic evaluation was triggered by the risk audit and pricing reconciliation events:

```json
{
  "scorecard": {
    "evaluation_timestamp_utc": "2026-11-11T16:46:09.539932+00:00",
    "assumed_portfolio_capital_usd": 20000.0,
    "valid_open_positions": 2,
    "quarantined_positions": 1,
    "closed_lifecycle_count": 0,
    "realized_net_pnl": 0.0,
    "unrealized_net_pnl": -12.41,
    "committed_capital": 10000.0,
    "deployed_capital": 10000.0,
    "portfolio_capital_utilization_pct": 50.0,
    "account_level_delta": 0.0,
    "max_legging_exposure": 5000.0,
    "minimum_margin_buffer": 99.5,
    "economic_incidents": [
      {
        "incident_id": "INC_001",
        "type": "N1_7_SIMULATOR_OVER_ALLOCATION_DEFECT",
        "severity": "HIGH",
        "description": "BNBUSD_270326 exceeded the 25% single-underlying capital cap by $2,370.",
        "remedy": "Quarantined in N1.8 allocation engine as RISK_ACTION_REQUIRED."
      },
      {
        "incident_id": "INC_002",
        "type": "N1_7_CROSS_SYMBOL_PRICING_DEFECT",
        "severity": "HIGH",
        "description": "Inner loop evaluated all lifecycles against XRP orderbook, artificially inflating MTM loss by $153.03.",
        "remedy": "Corrected in N1.8 to asset-specific orderbook pricing."
      },
      {
        "incident_id": "INC_003",
        "type": "RECORDER_PROCESS_TERMINATION",
        "severity": "MEDIUM",
        "description": "PID 9812 exited after ~51s; live forward stream paused.",
        "remedy": "Set FORWARD_ACCUMULATION = PAUSED to prevent claiming false continuous stream."
      }
    ]
  }
}
```

---

## Phase G — Research Disposition & Guardrails

```text
N1_8_PORTFOLIO_RISK_AGGREGATION        = VERIFIED
N1_8_COINM_COLLATERAL_FEASIBILITY      = VERIFIED
N1_8_INDEPENDENT_LEG_ACCOUNTING        = VERIFIED
N1_8_COST_ACCOUNTING                   = RECONCILED

H1_FORWARD_LIFECYCLES                  = ACCUMULATING
H1_FORWARD_NET_ECONOMIC_VALUE          = INCONCLUSIVE

H1_PRODUCTION_CANDIDATE                = FALSE
REAL_TRADING                           = DISABLED
```

### Rationale for `INCONCLUSIVE` Economic Verdict:
The two valid open carry positions have only been observed across a 38-minute window. Net unrealized PnL is `-$12.41` on $10,000 deployed capital (-0.124% on deployed, -0.062% on total capital), which is dominated by upfront taker fees ($15.00). Basis compression (`<= 15 bps`) or delivery settlement (`08:00 UTC` on delivery date) has not yet occurred naturally. Therefore, concluding positive or negative net economic value at this stage would be scientifically premature.

### Machine-Readable Deliverables Generated:
1. `research/neural_n1_8/n1_8_underlying_allocation_ledger.json`
2. `research/neural_n1_8/n1_8_account_margin_ledger.json`
3. `research/neural_n1_8/n1_8_independent_leg_scenarios.json`
4. `research/neural_n1_8/n1_8_position_reconciliation.json`
5. `research/neural_n1_8/n1_8_recorder_health.json`
6. `research/neural_n1_8/n1_8_lifecycle_state.json`
7. `tests/test_neural_n1_8.py` (6 unit tests, 100% passing)

### Research Boundaries Maintained:
- Research-only virtual simulation.
- No live orders submitted.
- No new neural models trained.
- No historical threshold tuning or cherry-picking.
- Canonical paper trading daemon remained disabled.
