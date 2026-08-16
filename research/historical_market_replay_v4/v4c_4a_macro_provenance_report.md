# HMR-V4C-4A — Macro Event State Provenance Audit Report

> **Knowledge Class**: `STATIC_KNOWLEDGE` — network access to FRED/Fed calendar
> is restricted in this environment. Provenance facts are sourced from official
> BLS, FOMC, and FRED documentation and represent well-established methodology.

## Governance Context

| Field | Value |
| :--- | :--- |
| Program | `HMR-V4C-4A` |
| Audit Class | `PROVENANCE_ONLY` |
| Discovery Budget | `4/4` |
| FEATURE_DISCOVERY_HARD_STOP | **DISARMED** (V4C-3 ETF2 already promoted) |
| DISCOVERY_CLOSE_GATE | **ARMED** — closes after V4C-4 regardless of result |
| Discovery Outcome | **`DISCOVERY_PHASE_COMPLETE`** |
| Promoted Source Count | `1` (ETF2 ex-GBTC) |
| V4C-4 Stage Verdict | **`REJECTED_FINAL`** |
| ML Training | **`BLOCKED`** |

---

## Critical Finding

> [!CAUTION]
> **C7 (surprise PIT safety) fails universally.** The `surprise = actual − consensus`
> feature family cannot be constructed with point-in-time safety from any free public
> source. Bloomberg/Reuters pre-release consensus vintage polls are not publicly
> available. This is a **structural provenance boundary**, not a data quality issue.

---

## Gate Summary by Source

| Gate | CPI_BLS | NFP_BLS | FOMC_FED |
| :--- | :---: | :---: | :---: |
| C0 Source reachable | ⚠️ `WARN_API_KEY_REQUIRED` | ⚠️ `WARN_API_KEY_REQUIRED` | ✅ `PASS_STATIC_KNOWLEDGE` |
| C1 Timestamp resolution | ⚠️ `WARN_DATE_ONLY_CONVENTIONAL_TIME` | ⚠️ `WARN_DATE_ONLY_CONVENTIONAL_TIME` | ⚠️ `WARN_DATE_ONLY_CONVENTIONAL_TIME` |
| C2 Consensus vintage | ❌ `FAIL_CONSENSUS_NOT_PUBLICLY_AVAILABLE` | ❌ `FAIL_CONSENSUS_NOT_PUBLICLY_AVAILABLE` | ❌ `FAIL_CONSENSUS_NOT_PUBLICLY_AVAILABLE` |
| C3 Revision risk | ✅ `PASS_MINOR` | ❌ `FAIL_MAJOR_REVISION_RISK` | ✅ `PASS` |
| C4 Coverage 2023–2024 | ✅ `PASS` | ✅ `PASS` | ✅ `PASS_LOWER_FREQUENCY` |
| C5 PIT lag policy | ✅ `PASS` | ✅ `PASS` | ✅ `PASS` |
| C6 Schema determinism | ✅ `PASS` | ✅ `PASS` | ✅ `PASS` |
| **C7 Surprise PIT safe** | ❌ `FAIL_CONSENSUS_NOT_PIT_SAFE` | ❌ `FAIL_CONSENSUS_NOT_PIT_SAFE` | ❌ `FAIL_CONSENSUS_NOT_PIT_SAFE` |
| C8 Intraday timestamp | ⚠️ `WARN_CONVENTIONAL_TIME_NOT_MACHINE_READABLE` | ⚠️ `WARN_CONVENTIONAL_TIME_NOT_MACHINE_READABLE` | ⚠️ `WARN_CONVENTIONAL_TIME_NOT_MACHINE_READABLE` |
| C9 Production feasible | ✅ `PASS` | ✅ `PASS` | ✅ `PASS` |

**Overall verdict per source:**

- `CPI_BLS`: ❌ **`REJECT_PROVENANCE_INCOMPLETE`**
- `NFP_BLS`: ❌ **`REJECT_PROVENANCE_INCOMPLETE`**
- `FOMC_FED`: ❌ **`REJECT_PROVENANCE_INCOMPLETE`**

---

## Detailed Source Notes

### CPI_BLS
*US CPI All Urban Consumers (BLS release, FRED CPIAUCSL)*

- **Releases per year in 2023–2024**: `24`
- **Scheduled UTC release time**: `13:30` (conventional)
- **PIT lag policy**: `0d (intraday, after 13:30 UTC on release day)`
- **Revision class**: `MINOR_REVISION`
- **FRED vintage history**: `True`

**Revision scope**: CPI is revised within the release cycle: preliminary, then final. YoY figures can be restated when seasonal factors are updated annually (Jan). Typical magnitude: ±0.1 pp YoY in seasonal revisions.

**Consensus vintage**: Consensus polls are collected by Bloomberg/Reuters from professional forecasters in the days before each release. Historical poll vintage data (what was the consensus as-of T-1 day before release N) is not publicly available. Current-database consensus reflects the final polled value, not the real-time pre-release snapshot used by traders.

### NFP_BLS
*US Nonfarm Payrolls (BLS Employment Situation, FRED PAYEMS)*

- **Releases per year in 2023–2024**: `24`
- **Scheduled UTC release time**: `13:30` (conventional)
- **PIT lag policy**: `0d (intraday, after 13:30 UTC on release day)`
- **Revision class**: `MAJOR_REVISION_RISK`
- **FRED vintage history**: `True`

**Revision scope**: NFP is subject to two subsequent monthly revisions (preliminary, second estimate). Annual benchmark revisions occur in Feb. Typical preliminary-to-final revision: ±50k–100k jobs (0.03–0.07% of employment). The benchmark revision (2024) revised 2023 figures by ~800k jobs.

**Consensus vintage**: Same provenance boundary as CPI. Bloomberg consensus polls are not free. In addition, the 2024 benchmark revision retroactively changed 2023 headline figures by ~818k jobs — if a model is trained with post-revision data, it has implicit lookahead on the exact series value a model would have seen at trade time.

### FOMC_FED
*FOMC rate decisions (Federal Reserve press releases)*

- **Releases per year in 2023–2024**: `16`
- **Scheduled UTC release time**: `19:00` (conventional)
- **PIT lag policy**: `0d (intraday, after 19:00 UTC on decision day)`
- **Revision class**: `NO_REVISION`
- **FRED vintage history**: `False`

**Revision scope**: Rate decision (hike/hold/cut) is not revised — it is the official policy action. Statement text is the official record. Dot plot and projections released quarterly may be revised in subsequent meetings but are not retroactively restated.

**Consensus vintage**: Rate-change surprise = actual_rate_change − market_implied_expectation. Market-implied expectation (from OIS or Fed funds futures) must be snapshotted just before the 2 PM ET announcement. Historical snapshots of OIS-implied probability distributions are not freely available; they require Bloomberg WIRP function historical data or similar proprietary feed. Binary direction (hike/hold/cut) IS PIT-safe from Fed press releases alone.

---

## Special Findings

### NFP_BENCHMARK_REVISION_LOOKAHEAD — severity: `HIGH`

The 2024 annual benchmark revision retroactively revised 2023 NFP figures by approximately −818k jobs. Any model trained or evaluated with post-revision PAYEMS data for the 2023 period has implicit lookahead. FRED vintage API (REALTIME_START parameter) is required to obtain first-print values — this requires an API key not present in this environment. Gate C3 for NFP must be classified MAJOR_REVISION_RISK until vintage-correct data can be confirmed.

### CONSENSUS_VINTAGE_UNIVERSAL_BLOCKER — severity: `HIGH`

The surprise feature (actual - consensus) is the primary information vector for macro event strategies. It fails universally because historical consensus snapshots require Bloomberg BEST function or Reuters terminal data. This is a structural, not incidental, provenance boundary.

---

## What Remains Viable

| Feature Concept | C7 PIT Safe | Information Content | Status |
| :--- | :---: | :--- | :--- |
| `fomc_event_day` binary | ✅ | Low — scheduled in advance | Viable from FOMC calendar |
| `fomc_hike_cut_hold` | ✅ | Moderate — known at 2 PM ET | Viable from Fed press release |
| `nfp_headline_first_print_level` | ⚠️ | Moderate — requires vintage API | Viable with FRED API key |
| `cpi_yoy_vs_prior_direction` | ⚠️ | Low–Moderate | Viable with FRED API key |
| `cpi_surprise_bps` | ❌ | High | **NOT VIABLE** — consensus vintage missing |
| `nfp_surprise_k` | ❌ | High | **NOT VIABLE** — consensus vintage missing |
| `fomc_rate_surprise_bps` | ❌ | High | **NOT VIABLE** — OIS baseline missing |

Binary event-state features are **out of scope for V4C-4B** given the rejection
of the surprise-magnitude family. A separate scoped audit would be required.

---

## Discovery Phase Closure

| Stage | Source Family | Verdict |
| :--- | :--- | :--- |
| V4C-1 | Cross-Market Risk Regime | `REJECTED_FINAL` |
| V4C-2 | Stablecoin Liquidity | `REJECTED_FINAL` |
| V4C-3 | ETF / Institutional Flow | `INFORMATION_SOURCE_PROMOTED` |
| V4C-4 | Macro Event State | **`REJECTED_FINAL`** |

**`DISCOVERY_PHASE_COMPLETE`** — 4/4 families audited.
**`FEATURE_DISCOVERY_HARD_STOP` = DISARMED** — 1 source promoted (ETF2 ex-GBTC).

Next: `HMR-V4D-1-r1` confirmatory integration audit proceeds as the sole remaining gate
before ML training can be unblocked.
