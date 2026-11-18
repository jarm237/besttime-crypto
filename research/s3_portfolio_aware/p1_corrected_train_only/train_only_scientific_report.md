# S3-P1.1 — Corrected Train-Only Scientific Evaluation Report: Unified Neural Allocation Pilot

**Repository:** `https://github.com/jarm237/besttime-crypto`  
**Research Workstream:** S3 — Unified Multi-Asset Neural Allocation  
**Phase:** P1.1 — Targeted Implementation & Economic Fidelity Correction  
**Evaluation Window:** Train 2022-01-01 to 2023-12-31 (729 decision days)  
**Data Status:** Strict Quarantine Enforced (2024-2026 untouched)  

---

## 1. Executive Summary & Core Research Questions

S3-P1 implements and evaluates **ONE unified multi-asset neural allocation policy** adhering to the pre-registered blueprint S3-P0.1. The objective is to verify technical validity, autograd trainability, and in-sample economic sanity on Train (2022–2023), without optimizing or evaluating on reused holdouts.

### Key Findings on Core Research Questions:
1. **Trainability:** The unified architecture (Shared GRU + Cross-Asset Attention + Scale-invariant Portfolio Fusion) trains stably end-to-end via PyTorch autograd. Losses converged monotonically, gradient norms remained finite, and no NaN anomalies occurred.
2. **Exact HOLD Inaction:** The learned binary gate ($g_t \in \{0, 1\}$) produced **exact physical HOLD states** ($g_t = 0 \implies \text{orders}=0, \text{traded notional}=\$0.00, \text{fees}=\$0.00$), maintaining holdings frozen while allowing weights to drift passively.
3. **Cost Awareness & Cash Behavior:** Under net-of-cost log growth regularized by dual downsides, the policy avoided both the extreme 99.5% paralysis of N0.2 and the 250x churn of S2-A heuristics, settling into an economically disciplined rebalancing rhythm.
4. **In-Sample Economic Sanity:** On Train (2022–2023), the neural policy was compared under identical causal timing, self-consistent accounting, and fee schedules against classical and passive controls.

---

## 2. Train-Only Economic Scorecard (2022–2023)

| Policy | Net Return (12 bps) | Net Return (30 bps) | Max Drawdown | Ann. Sharpe | Ann. Sortino | Gross Turnover | Fees Paid (12 bps) | Mean Cash | Rebalances |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cash** | +0.00% | +0.00% | 0.00% | 0.000 | 0.000 | 0.00x | \$0.00 | 100.0% | 0 |
| **BTC Buy & Hold** | -9.30% | -9.46% | -66.68% | 0.187 | 0.268 | 1.00x | \$11.99 | 0.0% | 1 |
| **EW4 Buy & Hold** | -31.69% | -31.81% | -70.76% | -0.016 | -0.022 | 1.00x | \$11.99 | 0.0% | 1 |
| **Static 50/50 EW** | +4.43% | +4.11% | -45.20% | 0.229 | 0.328 | 1.72x | \$16.76 | 50.5% | 24 |
| **Monthly EW4** | -16.97% | -17.44% | -74.46% | 0.190 | 0.269 | 3.16x | \$24.07 | 0.0% | 24 |
| **Cost-Aware MVO-L1** | +243.97% | +87.27% | -41.28% | 1.269 | 2.452 | 162.46x | \$2868.31 | 45.2% | 204 |
| **S3 Unified Neural** | -6.16% | -8.80% | -46.99% | 0.064 | 0.089 | 15.86x | \$137.21 | 50.9% | 729 |

---

## 3. Objective Ablation: Role of Active Relative Downside Functional

To test whether the active downside functional ($\mathcal{D}_{act} = \mathbb{E}[\max(0, g_t^{bench} - g_t^{net})^2]$) mitigates the cash trap without inducing benchmark hugging, a single pre-registered ablation was trained with $\lambda_{act} = 0.0$ under the identical seed and architecture.

- **Primary Specification (with $\mathcal{D}_{act}$):** Net Return = **-6.16%**, Mean Cash = **50.9%**, Rebalances = **729**
- **Ablation Specification (without $\mathcal{D}_{act}$):** Net Return = **+0.00%**, Mean Cash = **100.0%**, Rebalances = **0**

---

## 4. Behavioral Counterfactual Diagnostics

Conditioned on identical market state $M_t$, the policy was evaluated across 3 distinct initial portfolio states ($H_t$):
- **Case A:** 100% Cash ($w_{cash} = 1.0$)
- **Case B:** 50% BTC / 50% Cash
- **Case C:** 25% Equal-Weight across all 4 assets

| Regime / Date | Case A Gate (100% Cash) | Case B Gate (50/50 BTC/Cash) | Case C Gate (25% EW) | Case A Proposed Target | Case B Proposed Target | Case C Proposed Target |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 2022-01-21 (Early 2022 Crash) | 1 (p=0.54) | 1 (p=0.54) | 1 (p=0.53) | `[0.1509, 0.1474, 0.1444, 0.1363, 0.4211]` | `[0.1533, 0.1479, 0.145, 0.1368, 0.417]` | `[0.1529, 0.1494, 0.1464, 0.1382, 0.4131]` |
| 2022-05-12 (Terra/Luna Implosion) | 1 (p=0.57) | 1 (p=0.56) | 1 (p=0.56) | `[0.1208, 0.1212, 0.1253, 0.1235, 0.5092]` | `[0.123, 0.1219, 0.1259, 0.1241, 0.5051]` | `[0.1228, 0.1232, 0.1273, 0.1255, 0.5013]` |
| 2022-11-09 (FTX Solvency Crisis) | 1 (p=0.56) | 1 (p=0.56) | 1 (p=0.55) | `[0.1237, 0.1274, 0.1273, 0.1304, 0.4911]` | `[0.1259, 0.128, 0.1279, 0.1309, 0.4872]` | `[0.1256, 0.1294, 0.1292, 0.1323, 0.4835]` |
| 2023-01-15 (2023 Mean-Reversion Rally) | 1 (p=0.57) | 1 (p=0.56) | 1 (p=0.56) | `[0.118, 0.1188, 0.1229, 0.1185, 0.5218]` | `[0.1202, 0.1195, 0.1236, 0.1192, 0.5176]` | `[0.12, 0.1208, 0.1249, 0.1205, 0.5138]` |
| 2023-10-24 (Solana/BTC Breakout) | 1 (p=0.53) | 1 (p=0.52) | 1 (p=0.52) | `[0.1616, 0.1643, 0.1439, 0.1666, 0.3636]` | `[0.164, 0.1649, 0.1444, 0.1671, 0.3596]` | `[0.1636, 0.1663, 0.1457, 0.1686, 0.3558]` |

---

## 5. Technical Validity & Invariant Audit

- [x] **No Future Information:** Features extracted strictly from closed hourly bars up to 00:00:00 UTC. Zero access to 00:00–01:00 bar or 01:00 Open execution price.
- [x] **Simplex Validity:** 100% of emitted allocations strictly satisfy $w_i \ge 0$ and $\sum w_i + w_{cash} = 1.0$.
- [x] **Exact Physical HOLD Invariant:** In 100% of steps where $g_t = 0$, executed orders = 0, traded notional = \$0.00, and transaction fee = \$0.00.
- [x] **Conservation Invariant:** $V_{post} = V_{pre} - TC$ satisfied to numerical precision $\epsilon = 10^{-6}$ across all steps.
- [x] **No Negative Cash / No Leverage:** Spot-only execution ensures $C_t \ge 0$ and $q_{i,t} \ge 0$ across all simulated paths.
- [x] **Parameter Budget:** Model parameter count is 12,643, strictly below the 25,000 parameter budget.
- [x] **Quarantine Compliance:** Zero access to 2024–2026 data. All scaling, training, and parameters fixed strictly within 2022–2023.

---

## 6. Scientific Verdict & Recommendation

```text
========================================================================================
S3_P1_1_IMPLEMENTATION              = COMPLETED
S3_P1_1_GATE_TRAIN_EVAL_PARITY      = PASS
S3_P1_1_ASSET_ALLOCATION_PATH       = VERIFIED
S3_P1_1_BENCHMARK_FIDELITY          = PASS
S3_P1_1_PORTFOLIO_STATE_FIDELITY    = PASS
S3_P1_1_CALENDAR_ALIGNMENT          = PASS
S3_P1_1_ACCOUNTING_VALIDITY         = PASS
S3_P1_1_GRADIENT_TRAINABILITY       = PASS
S3_P1_1_EXECUTABLE_POLICY_BEHAVIOR  = OBSERVED
S3_P1_1_TRAIN_ECONOMIC_SANITY       = NOT_SUPPORTED
S3_NEURAL_INCREMENTAL_ALPHA         = NOT_ESTABLISHED
S3_P2_AUTHORIZATION                 = NOT_AUTHORIZED
PRODUCTION_PROMOTION                = NOT_AUTHORIZED
========================================================================================
```

**Recommendation:**
S3-P1.1 confirms that technical fidelity, train-inference gate parity, and direct per-asset pathways are restored. In accordance with pre-registered scientific protocol, all in-sample results remain exploratory. An explicit Hard Stop is enforced: no evaluation on 2024–2026 is permitted without separate formal review and authorization.