# H14.2 G4 — signal_score semantics audit

## Scope and verdict

This is a read-only diagnostic over the 647 authoritative analyses rebuilt from checkpoint #681. Outcome, realized quality, and PnL were not read.

**Verdict: `EXPECTED_NEUTRAL_SEMANTICS`.** No historical evidence is affected and no model or scoring change is warranted.

## Pipeline trace

`analyze_market` derives a technical signal from indicators and explicit policy guards. `SignalGeneratorAgent.run` then calls `evaluate_signal_score`, which delegates to `score_signal`. `_primary_signal_action` treats any signal containing `NEUTRAL` as neutral; `score_signal` assigns that branch score 50, LOW confidence, and zero directional strength before contextual adjustments. BUY/SELL signals instead start from directional base scores and may be adjusted or clipped to [0, 100]. The H14 observer records that score and the later policy action; MF2/MF4 shadow actions additionally require schedule eligibility.

Thus 50 is the documented midpoint (`0 = strongest SELL`, `50 = NEUTRAL`, `100 = strongest BUY`), not an inferred imputation for ordinary neutral rows.

## Authoritative distribution

| Slice | Rows | Score 50 | Directional BUY/SELL | Shared actionable | MF2-only | MF4-only | Neither |
|---|---:|---:|---:|---:|---:|---:|---:|
| BNBUSDT | 215 | 211 | 4 | 2 | 0 | 0 | 213 |
| BTCUSDT | 216 | 207 | 9 | 0 | 0 | 0 | 216 |
| ETHUSDT | 216 | 212 | 4 | 2 | 0 | 0 | 214 |
| **Total** | **647** | **630** | **17** | **4** | **0** | **0** | **643** |

Score distribution: 50×630, 13×5, 68×3, 35×2, 36×2, and one each at 12, 48, 51, 52, and 70.

Technical-state distribution: NEUTRAL(BULLISH) 277, NEUTRAL(BEARISH-CAUTION) 138, NEUTRAL(BEARISH) 112, NEUTRAL(BULLISH-CAUTION) 78, NEUTRAL(TREND-BLOCKED) 19, SELL 13, BUY 4, NEUTRAL(CROSSOVER-BEARMKT) 3, and NEUTRAL(CT-UNCONFIRMED) 3.

| Diagnostic classification | Rows | Interpretation |
|---|---:|---|
| Feature schema and snapshot hash present | 647 | Feature lineage is complete; individual raw feature values were not retained in this stream. |
| Score-50 with explicit NEUTRAL technical state | 630 | Documented neutral branch. |
| Directional technical state with score 50 | 0 | No directional collapse to the midpoint. |
| Runtime score log matched | 644 | All matched scores equal the authoritative score and all have `meta_error = null`. |
| Runtime log unavailable | 3 | Initial paper-canary triplet; each is explicitly NEUTRAL(BEARISH). |
| Matched score-50 rows with risk block annotation | 119 | Downstream action/risk annotation; not the source of score 50. |
| Matched score-50 rows with Optuna reject annotation | 167 | Downstream action annotation; overlaps other categories and does not change the already-neutral score. |
| Hard-reject, meta-filter, or MTF reason on score-50 rows | 0 | No evidence these normalization branches collapsed scores to 50. |

## Four audit questions

1. **Is 50 the documented neutral/default value?** Yes. All 630 score-50 observations have a `NEUTRAL (...)` technical state. No BUY or SELL technical observation has score 50.
2. **Did missing features silently push score to 50?** No such defect is evidenced. All 647 rows have a feature schema and feature snapshot hash. Runtime score diagnostics were recoverable for 644 local-production rows: every score matched the authoritative row and every matched `meta_error` was null. The three initial paper-canary rows have no retained detailed score log, but their technical state is explicitly NEUTRAL(BEARISH), consistent with the documented branch. The authoritative stream does not retain individual feature values, so this conclusion is about observed scoring behavior, not a claim that every upstream indicator was non-null.
3. **Did clipping or rounding collapse the distribution?** No. The non-neutral sample occupies nine distinct scores from 12 through 70; all 17 directional technical observations escaped 50. Clipping exists as a documented [0,100] bound, but no authoritative score is at either bound and it does not explain the mass at 50.
4. **Did actionable observations escape 50?** Yes. All four shared-actionable observations have non-50 scores (BNB SELL at 35/36, ETH SELL at 51, ETH BUY at 68).

## Discrimination funnel

```text
647 authoritative
 ├─ 17 technical BUY/SELL
 │   ├─ 8 MF2 schedule-eligible
 │   └─ 8 MF4 schedule-eligible
 ├─ 4 shared actionable
 ├─ 0 MF2-only actionable
 ├─ 0 MF4-only actionable
 └─ 643 neither actionable
```

`N_effective_disagreement = 0`. MF2 and MF4 currently contain the same symbol subset (`ETHUSDT`, `BNBUSDT`), so their eligibility and shadow actions are identical in this checkpoint. This is a sufficiency limitation, not an integrity incident and not a reason to alter score semantics.

## G4 gate

- Signal score semantics: EXPLAINED
- Silent score fallback defect: NONE OBSERVED
- Clipping/normalization defect: NONE
- Historical evidence affected: NONE
- Model change: NOT AUTHORIZED / NOT REQUIRED
- G4: PASS
