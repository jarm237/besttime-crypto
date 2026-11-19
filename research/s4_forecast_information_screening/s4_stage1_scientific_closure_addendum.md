# S4 Stage 1: Scientific Closure Addendum & Release Seal

- **Document Version:** 1.0.0
- **Repository:** `https://github.com/jarm237/besttime-crypto`
- **Branch:** `research/s4-stage1-forecast-screening`
- **Frozen Pre-registration Commit:** `7b5a97becbd6da1249a484ed588133761cc57bd0`
- **Date (UTC):** 2026-11-19
- **Governing Status:** Formal Scientific Closure & Release Seal

---

## A. Canonical Scientific Verdict

The pre-registered Stage-1 one-shot predictive screening for 2023 was completed strictly adhering to the frozen executable pre-registration protocol (`research/s4_forecast_information_screening/s4_p0_executable_preregistration.md`).

### Verified Canonical Results Summary

| Metric | Canonical Value |
|---|---:|
| 2023 common decision dates | 349 |
| Neural Fisher-z S | +0.031217 |
| Ridge Fisher-z S | +0.012557 |
| Primary Delta S [$S(\text{Neural}) - S(\text{Ridge})$] | +0.018660 |
| Primary 14-day Paired 95% Bootstrap CI | [-0.115742, +0.155270] |
| Positive Neural Mincer–Zarnowitz slopes | 2/4 (BTC: +0.3674, BNB: +0.6091; ETH: -0.2174, SOL: -0.2907) |
| Extreme-day-excluded Delta S (top 5% dropped) | -0.105712 |
| H1 (Jan–Jun) Delta S | +0.124640 |
| H2 (Jul–Dec) Delta S | -0.092684 |

### Final Scientific Verdict

$$\mathbf{S4\_SCIENTIFIC\_VERDICT = STAGE1\_SIGNAL\_INCONCLUSIVE}$$

### Methodological Reasoning

1. **Positive Point Estimate with Statistical Non-Significance:** The Unified Neural Forecaster produced a positive Fisher-z skill score ($S(\text{Neural}) = +0.031217 > 0$) and a positive point estimate differential over the Ridge baseline ($\Delta S = +0.018660$). However, the primary 14-day paired stationary bootstrap 95% confidence interval `[-0.115742, +0.155270]` comfortably spans zero. Under classical null hypothesis testing, the null hypothesis $\Delta S \le 0$ cannot be rejected at the registered 95% confidence level.
2. **Failure of Pre-registered Corroboration:** Only 2 of 4 assets demonstrated positive Mincer–Zarnowitz regression slopes (failing the registered requirement of $\ge 3/4$ positive slopes and positive median slope).
3. **Fragility to Extreme-Day Exclusion:** Dropping the top 5% most volatile days (18 dates) caused Delta S to invert dramatically from $+0.018660$ to $-0.105712$. The aggregate positive point estimate was heavily dependent on a handful of large-move dates rather than consistent incremental predictive power across normal regimes.
4. **Adherence to Pre-registered Decision Logic:** The pre-registered protocol dictates `STAGE1_SIGNAL_SUPPORTED` only if all criteria (a)–(f) pass simultaneously, and `STAGE1_SIGNAL_NOT_SUPPORTED` if $S(\text{Neural}) \le 0$ or the upper bound of the 95% CI is $\le 0$. Because $S(\text{Neural}) > 0$ and the upper CI bound ($+0.155270$) is strictly positive, declaring `NOT_SUPPORTED` would violate the pre-registration specification. The verdict is definitively and unambiguously **`STAGE1_SIGNAL_INCONCLUSIVE`**.
5. **No Universal Generalization:** This verdict certifies that incremental predictive information over Ridge was not established under the registered experimental protocol on 2023 data. It does not assert that neural architectures cannot extract alpha under different horizons, objective functions, or feature spaces.

---

## B. Training Objective & Source Code Provenance

To eliminate ambiguity regarding training versus evaluation objectives, this section documents the exact source code contracts implemented in the repository.

### 1. Training Objective Implementation

Direct inspection of `run_development_2022()` in `scripts/run_s4_stage1_screen.py`:

```python
y_dev_clipped = np.stack([
    dev_sigma_normalizer.standardize_target_vector(
        partitions.raw_labels[d], d, clip=True
    )
    for d in dev_decisions
], axis=0)

criterion = nn.MSELoss()
```

Cross-referenced with `btc_scraper/research/s4_forecast.py`:
- `CausalSigmaNormalizer.standardize_target()`
- `CausalSigmaNormalizer.standardize_target_vector()`

The exact contracts are:

```text
TARGET_NORMALIZATION = y / causal_sigma
TARGET_CLIPPING      = [-4, +4]
TRAINING_LOSS        = SQUARED_ERROR
NEURAL_OPTIMIZER     = ADAMW
HUBER_LOSS           = NOT_USED
RAW_RETURN_MSE       = NOT_USED
```

### 2. Scientific Interpretation of Objective Function

- **Conditional-Mean Surrogate:** Minimizing mean squared error on causal-sigma standardized and $[-4, +4]$ clipped returns estimates a conditional expectation of the standardized and bounded distribution: $\mathbb{E}[z_{i,t} \mid \mathcal{F}_{t-1}]$ where $z_{i,t} = \text{clip}(y_{i,t} / \sigma_{i,t}, -4, +4)$.
- **Distinction from Raw Expected Return:** Standardizing by causal rolling volatility and clipping tails acts as a robust conditional-mean surrogate. It is mathematically distinct from conditional expected raw return $\mathbb{E}[y_{i,t} \mid \mathcal{F}_{t-1}]$.
- **Evaluation vs. Training Consistency:** In accordance with the pre-registration, the primary information coefficient (IC) evaluation was conducted on raw unclipped standardized targets $z_{i,t} = y_{i,t} / \sigma_{i,t}$, while training intentionally applied the $[-4, +4]$ bound to stabilize gradient dynamics in the GRU network. Training objective and evaluation target must not be conflated.

---

## C. Diagnostic Interpretations & Scientific Limitations

### 1. Low Forecast Amplitude and Suspected Underfitting
The observed forecast standard deviations across assets range between 25 and 81 bps, significantly smaller than the realized daily return standard deviations (approximately 236 to 522 bps). This compressed dispersion indicates strong shrinkage and forecast amplitude attenuation toward zero. While this is characteristic of heavy $L_2$/weight-decay regularization and conservative feature representation, it does not constitute formal mathematical "mean collapse" because variance remains strictly non-zero and time-varying. No constant-mean benchmark was pre-registered to statistically test for strict collapse.

### 2. High Dimensionality and Ridge Boundary Selection
The Ridge regression baseline maps 4,032 flattened input dimensions (168 hourly steps $\times$ 4 assets $\times$ 6 features) against only 364 daily development observations in 2022, resulting in an extreme parameter-to-sample ratio $p/n \approx 11.08$. Across the pre-registered geometric alpha grid `[0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000]`, cross-validation error decreased monotonically up to the upper boundary $\alpha = 10,000.0$. While selecting the boundary value reflects the necessity of heavy shrinkage in ultra-high dimensions, it cannot be formally concluded whether an unconstrained optimal alpha exists beyond 10,000 without violating the pre-registered search grid.

### 3. Statistical Uncertainty and Power Limitation
The primary 14-day stationary bootstrap 95% confidence interval has a width of approximately 0.271 (`[-0.115742, +0.155270]`). Sample size constraints ($N = 349$), serial autocorrelation across consecutive decision windows, and strong cross-sectional contemporaneous correlations among crypto assets inherently limit statistical precision. No formal statistical power simulation or minimum detectable effect (MDE) calculation was pre-registered; therefore, asserting a definitive detection threshold or post-hoc power estimate is mathematically unwarranted.

### 4. Temporal Instability and Extreme-Day Sensitivity
Performance exhibited substantial non-stationarity across calendar halves: H1 (Jan–Jun) showed positive incremental skill ($\Delta S = +0.124640$), whereas H2 (Jul–Dec) showed negative incremental skill ($\Delta S = -0.092684$). Furthermore, removing 18 extreme days inverted Delta S to $-0.105712$. These extreme dates are distributed across multiple months from January through November 2023. Attributing this instability to specific market narratives (e.g., SVB/USDC depeg, banking sector stress, ETF announcements, or liquidity dry-ups) would constitute unfalsifiable post-hoc storytelling. Market regime change remains an interesting hypothesis, not a demonstrated causal explanation.

### 5. Scope & Boundary Disclaimers
- **Reused Internal Screen:** The calendar year 2023 was previously utilized during historical S3 explorations; these results constitute a `REUSED_INTERNAL_SCREEN`, not an untouched out-of-sample test.
- **No Trading PnL Implication:** Stage 1 evaluated purely information-theoretic forecast correlations ($IC$ and Fisher-z $S$). It provides zero empirical evidence regarding portfolio Sharpe ratio, execution feasibility, slippage tolerance, or net trading profitability.
- **No Stage-2 Allocator Authorization:** Given that incremental forecast skill was not established, there is no scientific basis for deploying portfolio allocators or risk weighting engines on top of this model.

---

## D. Research Boundaries & Final Closure Status

The research boundaries are sealed with immediate effect:

```text
S4_STAGE1_RESEARCH        = CLOSED_INCONCLUSIVE
S4_SCIENTIFIC_VERDICT     = STAGE1_SIGNAL_INCONCLUSIVE
S4_INCREMENTAL_SKILL      = NOT_ESTABLISHED

S4_2023_SCREEN            = CONSUMED
S4_2023_RETUNING          = PROHIBITED
S4_NEURAL_RETRAINING      = NOT_AUTHORIZED
S4_STAGE2_ALLOCATOR       = NOT_AUTHORIZED
S4_2024_2026_ACCESS      = NOT_AUTHORIZED
PRODUCTION_PROMOTION      = NOT_AUTHORIZED

NEXT_ACTION               = STOP
```

No follow-up experiments, retuning, model mutations, or dataset expansions are authorized within this closure.

---

## E. Verified Commit Provenance & Erratum

### 1. Canonical Verified Git Commits
The exact commit lineage of Stage 1 has been verified against GitHub remote metadata:

- **S4_P1C_ENGINE_COMMIT:**
  `bb063a69ac29994f3f720ea333b8a3269741b708`
  *(Implementation of evaluation engine, bootstrap metrics, diagnostic statistics, and synthetic verification suite)*

- **S4_P1C_EVIDENCE_COMMIT:**
  `15d7c115583466fa57d6751dc1f5f229f6753a99`
  *(Execution of one-shot 2023 predictive screening and commit of immutable evidence artifacts)*

### 2. Historical Erratum
In earlier automated session transcripts and interim summaries, truncated short SHAs (`bb063a69` and `15d7c115`) were inadvertently expanded with non-matching trailing hex characters:
- Erroneous engine SHA expansion: `bb063a69a04f9f740a85a0899014b2d561a3a60a`
- Erroneous evidence SHA expansion: `15d7c11579979dbe339d20c52869919f42cbaef4`

This addendum formally records that the true canonical full SHAs are `bb063a69ac29994f3f720ea333b8a3269741b708` and `15d7c115583466fa57d6751dc1f5f229f6753a99`. The erroneous expansions are preserved strictly as a documented historical erratum and must never be referenced as canonical commit targets.
