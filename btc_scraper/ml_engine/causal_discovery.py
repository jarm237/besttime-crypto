"""
CausalDiscoveryEngine - Automatically discover causal relationships from historical data.

Phase 3.0 of the Causal World Model integration.

Uses statistical methods to infer causal structure from time-series data:
  - Granger Causality: Does X's past predict Y's future beyond Y's own past?
  - Lagged Correlation: Cross-correlation at multiple lags
  - Partial Correlation: Control for confounders

Discovered edges are written back to causal_graph.json with source="learned",
allowing the graph to evolve as market structure changes.

Design Principles:
  - No heavy external dependencies (no causallearn/tigramite required)
  - Uses only numpy/pandas (already in project dependencies)
  - Conservative: only adds edges that pass both correlation AND Granger tests
  - Versioned: bumps graph patch version when writing learned edges
  - Non-destructive: never modifies manual edges

Usage:
    engine = CausalDiscoveryEngine("data/causal_graph.json")
    report = engine.discover(historical_df, target_variable="BTC")
    engine.save_learned_edges(report.learned_edges)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class LearnedEdge:
    """A causal edge discovered from data."""
    from_node: str
    to_node: str
    effect: str           # "positive" or "negative"
    weight: float         # Normalized effect strength (0.0–1.0)
    confidence: float     # Statistical confidence (0.0–1.0)
    lag: int              # Optimal lag in periods (e.g., 3 = 3 candles)
    lag_unit: str         # "candle", "hour", "day"
    granger_pvalue: float
    correlation: float    # Raw cross-correlation at best lag
    source: str = "learned"

    def to_graph_edge(self, edge_id: str) -> Dict:
        """Convert to causal_graph.json edge format."""
        return {
            "id": edge_id,
            "from": self.from_node,
            "to": self.to_node,
            "effect": self.effect,
            "weight": round(self.weight, 3),
            "lag": f"{self.lag}{self.lag_unit[0]}",
            "confidence": round(self.confidence, 3),
            "condition": "always",
            "is_active": True,
            "source": self.source,
            "propagate_confidence": True,
            "description": (
                f"Learned: {self.from_node}→{self.to_node} "
                f"(corr={self.correlation:+.3f}, lag={self.lag}, p={self.granger_pvalue:.3f})"
            ),
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "granger_pvalue": round(self.granger_pvalue, 4),
        }


@dataclass
class DiscoveryReport:
    """Results of a causal discovery run."""
    target_variable: str
    candidate_variables: List[str]
    learned_edges: List[LearnedEdge]
    rejected_candidates: List[str]
    n_samples: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def summary(self) -> str:
        return (
            f"CausalDiscovery | target={self.target_variable} | "
            f"candidates={len(self.candidate_variables)} | "
            f"learned={len(self.learned_edges)} edges | "
            f"n_samples={self.n_samples}"
        )


# ─── Statistical Tests ────────────────────────────────────────────────────────

def _lagged_correlation(x: pd.Series, y: pd.Series, max_lag: int = 10) -> Tuple[int, float]:
    """
    Find the lag at which x most strongly correlates with y.

    Tests lags 0..max_lag. Returns (best_lag, best_correlation).
    x is the cause, y is the effect (y is shifted forward in time relative to x).
    """
    best_lag = 0
    best_corr = 0.0

    for lag in range(0, max_lag + 1):
        if lag == 0:
            x_aligned, y_aligned = x.align(y, join="inner")
        else:
            x_lagged = x.shift(lag)
            x_aligned, y_aligned = x_lagged.align(y, join="inner")
            x_aligned = x_aligned.dropna()
            y_aligned = y_aligned.loc[x_aligned.index]

        if len(x_aligned) < 30:
            continue

        try:
            corr = float(x_aligned.corr(y_aligned))
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag
        except Exception:
            continue

    return best_lag, best_corr


def _granger_causality_simple(
    cause: pd.Series,
    effect: pd.Series,
    lag: int,
    significance: float = 0.05,
) -> Tuple[bool, float]:
    """
    Simplified Granger causality test using OLS regression comparison.

    Restricted model:  effect_t = a0 + a1*effect_{t-1} + ... + ε
    Unrestricted model: effect_t = a0 + a1*effect_{t-1} + ... + b1*cause_{t-lag} + ε

    Uses F-statistic to test if including lagged cause significantly reduces residuals.

    Returns: (is_significant, pseudo_pvalue)
    """
    try:
        df = pd.DataFrame({"cause": cause, "effect": effect}).dropna()
        if len(df) < lag + 30:
            return False, 1.0

        # Build lag features
        for i in range(1, lag + 1):
            df[f"effect_lag_{i}"] = df["effect"].shift(i)
            df[f"cause_lag_{i}"] = df["cause"].shift(i)

        df = df.dropna()
        if len(df) < 20:
            return False, 1.0

        y = df["effect"].values
        effect_lags = df[[f"effect_lag_{i}" for i in range(1, lag + 1)]].values

        # Restricted model (effect_lags only) — no intercept column needed
        X_r = np.column_stack([np.ones(len(y)), effect_lags])
        # Unrestricted model (+ cause lags)
        cause_lags = df[[f"cause_lag_{i}" for i in range(1, lag + 1)]].values
        X_u = np.column_stack([X_r, cause_lags])

        def _ols_rss(X: np.ndarray, y_arr: np.ndarray) -> float:
            try:
                beta, res, _, _ = np.linalg.lstsq(X, y_arr, rcond=None)
                y_hat = X @ beta
                return float(np.sum((y_arr - y_hat) ** 2))
            except Exception:
                return float("inf")

        rss_r = _ols_rss(X_r, y)
        rss_u = _ols_rss(X_u, y)

        if rss_u <= 0 or rss_r <= 0:
            return False, 1.0

        # F-statistic: ((RSS_r - RSS_u)/q) / (RSS_u/(n-k))
        n = len(y)
        q = lag          # number of added regressors
        k = X_u.shape[1]
        if n <= k:
            return False, 1.0

        f_stat = ((rss_r - rss_u) / q) / (rss_u / (n - k))
        if f_stat < 0:
            return False, 1.0

        # Convert to pseudo p-value using chi2 approximation
        # p ≈ exp(-f_stat/2) — conservative approximation
        pseudo_pvalue = float(np.exp(-min(f_stat / 2, 20)))
        is_significant = pseudo_pvalue < significance

        return is_significant, pseudo_pvalue

    except Exception as exc:
        logger.debug(f"[CausalDiscovery] Granger test error: {exc}")
        return False, 1.0


# ─── Main Engine ──────────────────────────────────────────────────────────────

class CausalDiscoveryEngine:
    """
    Discovers causal relationships from time-series data and merges them
    into the causal graph as 'learned' edges.

    Conservative thresholds ensure only statistically robust edges are added.
    """

    # Minimum absolute correlation to consider an edge
    MIN_CORRELATION = 0.25
    # Maximum Granger causality p-value to accept an edge
    MAX_GRANGER_PVALUE = 0.10
    # Minimum confidence to write to graph
    MIN_CONFIDENCE = 0.60

    def __init__(
        self,
        graph_path: str = "data/causal_graph.json",
        max_lag: int = 10,
        min_correlation: float = 0.25,
        max_pvalue: float = 0.10,
    ):
        """
        Args:
            graph_path: Path to causal_graph.json (for reading existing nodes + writing learned edges).
            max_lag: Maximum lag periods to test.
            min_correlation: Minimum correlation coefficient to consider an edge.
            max_pvalue: Maximum Granger causality p-value to accept an edge.
        """
        self.graph_path = graph_path
        self.max_lag = max_lag
        self.min_correlation = min_correlation
        self.max_pvalue = max_pvalue
        self._graph: Optional[Dict] = self._load_graph()

    def _load_graph(self) -> Optional[Dict]:
        try:
            with open(self.graph_path) as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"[CausalDiscovery] Cannot load graph: {exc}")
            return None

    def _existing_manual_pairs(self) -> set:
        """Return set of (from, to) pairs that already exist as manual edges."""
        if self._graph is None:
            return set()
        return {
            (e["from"], e["to"])
            for e in self._graph.get("edges", [])
            if e.get("source") == "manual"
        }

    def discover(
        self,
        data: pd.DataFrame,
        target_variable: str = "BTC",
        candidate_variables: Optional[List[str]] = None,
    ) -> DiscoveryReport:
        """
        Run causal discovery analysis.

        Args:
            data: DataFrame with time-series columns. Each column is a variable name.
                  Should have at least 100 rows for reliable statistics.
            target_variable: The variable to find causes for (e.g., "BTC").
            candidate_variables: List of potential causal variables. Defaults to all other columns.

        Returns:
            DiscoveryReport with learned edges and rejected candidates.
        """
        if target_variable not in data.columns:
            raise ValueError(f"Target variable '{target_variable}' not in data columns: {list(data.columns)}")

        if candidate_variables is None:
            candidate_variables = [c for c in data.columns if c != target_variable]

        target_series = data[target_variable].dropna()
        # Use returns/differences for stationarity (prevents spurious correlation)
        target_stationary = target_series.pct_change().dropna()
        n_samples = len(target_stationary)

        if n_samples < 50:
            logger.warning(
                f"[CausalDiscovery] Only {n_samples} samples — results may be unreliable"
            )

        existing_pairs = self._existing_manual_pairs()
        learned_edges: List[LearnedEdge] = []
        rejected: List[str] = []

        for candidate in candidate_variables:
            if candidate not in data.columns:
                logger.debug(f"[CausalDiscovery] Candidate '{candidate}' not in data, skipping")
                rejected.append(candidate)
                continue

            cause_series = data[candidate].dropna()
            # Use pct_change for stationary series (price-like columns)
            # Z-score/ratio columns are already stationary, use as-is
            cause_stationary = cause_series.pct_change().dropna() if cause_series.std() > 1.0 else cause_series

            # Step 1: Lagged correlation screen (on stationary series)
            best_lag, best_corr = _lagged_correlation(cause_stationary, target_stationary, self.max_lag)

            if abs(best_corr) < self.min_correlation:
                logger.debug(
                    f"[CausalDiscovery] {candidate}→{target_variable}: "
                    f"corr={best_corr:.3f} < {self.min_correlation} — rejected"
                )
                rejected.append(candidate)
                continue

            # Step 2: Granger causality test at best lag (on stationary series)
            effective_lag = max(best_lag, 1)  # Granger requires lag >= 1
            is_granger, pvalue = _granger_causality_simple(
                cause_stationary, target_stationary, lag=effective_lag, significance=self.max_pvalue
            )

            if not is_granger:
                logger.debug(
                    f"[CausalDiscovery] {candidate}→{target_variable}: "
                    f"Granger p={pvalue:.3f} > {self.max_pvalue} — rejected"
                )
                rejected.append(candidate)
                continue

            # Step 3: Build learned edge
            effect = "positive" if best_corr > 0 else "negative"
            # Normalize weight from correlation magnitude
            weight = min(1.0, abs(best_corr) * 1.2)  # slight amplification
            # Confidence from correlation strength + Granger significance
            confidence = min(0.95, (abs(best_corr) + (1.0 - pvalue) * 0.3) / 1.3)

            if confidence < self.MIN_CONFIDENCE:
                rejected.append(candidate)
                continue

            edge = LearnedEdge(
                from_node=candidate,
                to_node=target_variable,
                effect=effect,
                weight=round(weight, 3),
                confidence=round(confidence, 3),
                lag=best_lag,
                lag_unit="candle",
                granger_pvalue=round(pvalue, 4),
                correlation=round(best_corr, 4),
            )
            learned_edges.append(edge)
            logger.info(
                f"[CausalDiscovery] ✓ {candidate}→{target_variable}: "
                f"effect={effect}, corr={best_corr:+.3f}, lag={best_lag}, "
                f"confidence={confidence:.2f}, granger_p={pvalue:.3f}"
            )

        return DiscoveryReport(
            target_variable=target_variable,
            candidate_variables=candidate_variables,
            learned_edges=learned_edges,
            rejected_candidates=rejected,
            n_samples=n_samples,
        )

    def save_learned_edges(self, learned_edges: List[LearnedEdge]) -> bool:
        """
        Merge learned edges into causal_graph.json.

        Rules:
        - Never overwrites manual edges
        - Removes stale learned edges before adding new ones
        - Bumps graph patch version (e.g., 2.0.0 → 2.0.1)

        Args:
            learned_edges: Edges to merge from a DiscoveryReport.

        Returns:
            True if saved successfully.
        """
        if not learned_edges:
            logger.info("[CausalDiscovery] No learned edges to save")
            return True

        self._graph = self._load_graph()
        if self._graph is None:
            logger.error("[CausalDiscovery] Cannot load graph — aborting save")
            return False

        existing_edges = self._graph.get("edges", [])

        # Remove all previously learned edges (will be replaced)
        manual_edges = [e for e in existing_edges if e.get("source") != "learned"]
        existing_manual_pairs = {(e["from"], e["to"]) for e in manual_edges}

        # Add new learned edges (skip any that conflict with manual edges)
        new_learned = []
        last_id = max(
            (int(e["id"].replace("edge_", "")) for e in manual_edges if e["id"].startswith("edge_")),
            default=0,
        )

        for edge in learned_edges:
            pair = (edge.from_node, edge.to_node)
            if pair in existing_manual_pairs:
                logger.info(
                    f"[CausalDiscovery] Skipping learned edge {pair} — manual edge exists"
                )
                continue
            last_id += 1
            new_learned.append(edge.to_graph_edge(f"edge_{last_id}"))

        self._graph["edges"] = manual_edges + new_learned

        # Bump patch version
        version_parts = self._graph.get("version", "2.0.0").split(".")
        try:
            version_parts[-1] = str(int(version_parts[-1]) + 1)
        except (ValueError, IndexError):
            version_parts = ["2", "0", "1"]
        self._graph["version"] = ".".join(version_parts)
        now = datetime.now(timezone.utc)
        self._graph["updated_at"] = now.strftime("%Y-%m-%d")
        self._graph["metadata"]["last_discovery_run"] = now.isoformat()

        # Write back
        try:
            with open(self.graph_path, "w") as f:
                json.dump(self._graph, f, indent=2)
            logger.info(
                f"[CausalDiscovery] ✓ Saved {len(new_learned)} learned edges to '{self.graph_path}' "
                f"(v{self._graph['version']})"
            )
            return True
        except Exception as exc:
            logger.error(f"[CausalDiscovery] Failed to write graph: {exc}")
            return False

    def generate_synthetic_data(self, n: int = 500, seed: int = 42) -> pd.DataFrame:
        """
        Generate synthetic market data for testing causal discovery.

        Known ground-truth causal structure:
          DXY    → BTC (negative, lag=1)  — strong signal
          VIX    → BTC (negative, lag=0)  — medium signal
          FundingZ → BTC (negative, lag=2) — medium signal
          RealYield → BTC (negative, lag=1) — strong signal
        """
        rng = np.random.default_rng(seed)

        DXY = 104.0 + np.cumsum(rng.normal(0, 0.3, n))
        VIX = np.abs(20.0 + np.cumsum(rng.normal(0, 0.5, n)))
        FundingZ = rng.normal(0.3, 0.8, n)
        RealYield = 1.5 + np.cumsum(rng.normal(0, 0.02, n))

        # BTC log-returns driven by causal factors with clear effect sizes
        log_btc = np.log(50000.0)
        btc_prices = [np.exp(log_btc)]
        for i in range(1, n):
            dxy_effect = -0.035 * (DXY[i] - DXY[i-1])         # DXY lag=0/1
            vix_effect = -0.008 * max(0, VIX[i] - 20)         # VIX level
            fund_effect = -0.025 * FundingZ[max(0, i-2)]      # Funding lag=2
            yield_effect = -0.040 * (RealYield[i] - 1.5)      # Real yield level
            noise = rng.normal(0, 0.008)                       # Smaller noise
            log_btc += dxy_effect + vix_effect + fund_effect + yield_effect + noise
            btc_prices.append(np.exp(log_btc))

        return pd.DataFrame({
            "DXY": DXY,
            "VIX": VIX,
            "FundingZ": FundingZ,
            "RealYield": RealYield,
            "BTC": btc_prices,
        })


if __name__ == "__main__":
    engine = CausalDiscoveryEngine("data/causal_graph.json", max_lag=5)

    print("Generating synthetic data...")
    data = engine.generate_synthetic_data(n=500)
    print(f"Data shape: {data.shape}")

    print("\nRunning causal discovery (target=BTC)...")
    report = engine.discover(data, target_variable="BTC")

    print(f"\n{report.summary()}")
    print(f"\nLearned edges ({len(report.learned_edges)}):")
    for edge in report.learned_edges:
        print(f"  {edge.from_node} → {edge.to_node}: "
              f"effect={edge.effect}, weight={edge.weight:.3f}, "
              f"confidence={edge.confidence:.3f}, lag={edge.lag}, "
              f"corr={edge.correlation:+.3f}, p={edge.granger_pvalue:.3f}")

    print(f"\nRejected: {report.rejected_candidates}")
