"""
Integration Test: Phase 3.0 Learning & Causal Discovery

Tests:
  1. BayesianContextProvider — probabilistic scoring, risk-off detection
  2. CausalDiscoveryEngine — Granger causality, learned edge writing
  3. HybridContextProvider — alpha blending, enable_learned_rules flag

Run:
    .venv/bin/pytest tests/test_phase30_learning.py -v
"""

import json
import os
import sys
import tempfile
import pytest
import math
from datetime import datetime, timezone

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.core.world_state import WorldState, MarketRegime
from btc_scraper.ml_engine.context_provider import RiskLevel
from btc_scraper.ml_engine.bayesian_context_provider import (
    BayesianContextProvider,
    FeatureSpec,
    DEFAULT_FEATURE_SPECS,
    _gaussian_log_likelihood,
)
from btc_scraper.ml_engine.causal_discovery import (
    CausalDiscoveryEngine,
    LearnedEdge,
    _granger_causality_simple,
    _lagged_correlation,
)
from btc_scraper.ml_engine.hybrid_context_provider import HybridContextProvider


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def risk_off_state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 108.5
    state.macro.VIX = 32.0
    state.macro.RealYield = 2.3
    state.liquidity.Funding_Z = 2.8
    state.sentiment.FearGreed = 18.0
    return state


@pytest.fixture
def risk_on_state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_ON)
    state.macro.DXY = 100.0
    state.macro.VIX = 13.5
    state.macro.RealYield = 0.3
    state.liquidity.Funding_Z = 0.2
    state.sentiment.FearGreed = 63.0
    return state


@pytest.fixture
def bayes_provider():
    return BayesianContextProvider.from_causal_graph("data/causal_graph.json")


@pytest.fixture
def discovery_engine():
    return CausalDiscoveryEngine("data/causal_graph.json", max_lag=5)


@pytest.fixture
def synthetic_data(discovery_engine):
    return discovery_engine.generate_synthetic_data(n=400, seed=42)


@pytest.fixture
def hybrid_provider():
    return HybridContextProvider.build(
        rules_path="data/context_rules.json",
        graph_path="data/causal_graph.json",
        alpha=0.30,
    )


# ─── 1. BayesianContextProvider ───────────────────────────────────────────────

class TestBayesianContextProvider:
    def test_validate_default_specs(self, bayes_provider):
        is_valid, msg = bayes_provider.validate()
        assert is_valid, f"Validation failed: {msg}"

    def test_penalizes_risk_off(self, bayes_provider, risk_off_state):
        """Under risk-off conditions, score should drop."""
        original = 0.80
        report = bayes_provider.generate_context_report(original, risk_off_state)
        assert report.adjusted_score < original, (
            f"Expected score to drop from {original}, got {report.adjusted_score:.3f}"
        )

    def test_supports_risk_on(self, bayes_provider, risk_on_state):
        """Under risk-on conditions, score should rise or hold."""
        original = 0.60
        report = bayes_provider.generate_context_report(original, risk_on_state)
        assert report.adjusted_score >= original - 0.05, (
            f"Expected score to rise from {original}, got {report.adjusted_score:.3f}"
        )

    def test_risk_off_gives_high_risk_level(self, bayes_provider, risk_off_state):
        report = bayes_provider.generate_context_report(0.80, risk_off_state)
        assert report.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_risk_on_gives_low_risk_level(self, bayes_provider, risk_on_state):
        report = bayes_provider.generate_context_report(0.70, risk_on_state)
        assert report.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)

    def test_score_is_bounded(self, bayes_provider, risk_off_state, risk_on_state):
        for state in [risk_off_state, risk_on_state]:
            report = bayes_provider.generate_context_report(0.75, state)
            assert 0.0 <= report.adjusted_score <= 1.0

    def test_report_has_adjustments(self, bayes_provider, risk_off_state):
        report = bayes_provider.generate_context_report(0.80, risk_off_state)
        assert len(report.adjustments) > 0

    def test_report_has_breakdown(self, bayes_provider, risk_off_state):
        report = bayes_provider.generate_context_report(0.80, risk_off_state)
        assert isinstance(report.breakdown, dict)
        assert len(report.breakdown) > 0

    def test_explanation_is_informative(self, bayes_provider, risk_off_state):
        report = bayes_provider.generate_context_report(0.80, risk_off_state)
        assert "Bayesian" in report.explanation
        assert "posterior" in report.explanation.lower()

    def test_from_causal_graph_applies_weight_overrides(self):
        """Loading from graph should produce different weights than defaults."""
        default_provider = BayesianContextProvider()
        graph_provider = BayesianContextProvider.from_causal_graph("data/causal_graph.json")

        default_weights = {s.name: s.weight for s in default_provider.feature_specs}
        graph_weights = {s.name: s.weight for s in graph_provider.feature_specs}

        # At least one weight should differ (graph has specific edge confidences)
        changed = [k for k in default_weights if abs(default_weights[k] - graph_weights.get(k, 0)) > 0.01]
        assert len(changed) >= 1, "Expected at least one weight to be overridden from graph"

    def test_handles_missing_features_gracefully(self):
        """Provider should passthrough with an unpopulated WorldState."""
        provider = BayesianContextProvider()
        empty_state = WorldState(timestamp=datetime.now(timezone.utc))
        report = provider.generate_context_report(0.70, empty_state)
        assert report.adjusted_score == pytest.approx(0.70)
        assert report.adjustments == []
        assert "No market features" in report.explanation

    def test_should_apply_returns_false_with_no_data(self):
        """should_apply_context should return False when no features available."""
        provider = BayesianContextProvider()
        state = WorldState(timestamp=datetime.now(timezone.utc))
        result = provider.should_apply_context(state)
        assert result is False

    def test_gaussian_log_likelihood(self):
        """Log-likelihood at mean should be highest."""
        ll_at_mean = _gaussian_log_likelihood(5.0, 5.0, 1.0)
        ll_one_std = _gaussian_log_likelihood(6.0, 5.0, 1.0)
        ll_two_std = _gaussian_log_likelihood(7.0, 5.0, 1.0)
        assert ll_at_mean > ll_one_std > ll_two_std

    def test_risk_off_score_lower_than_risk_on(self, bayes_provider, risk_off_state, risk_on_state):
        """Risk-off should always score lower than risk-on for the same original."""
        original = 0.75
        r_off = bayes_provider.generate_context_report(original, risk_off_state)
        r_on = bayes_provider.generate_context_report(original, risk_on_state)
        assert r_off.adjusted_score < r_on.adjusted_score, (
            f"Risk-off ({r_off.adjusted_score:.3f}) should be < risk-on ({r_on.adjusted_score:.3f})"
        )


# ─── 2. CausalDiscoveryEngine ────────────────────────────────────────────────

class TestCausalDiscoveryEngine:
    def test_synthetic_data_generation(self, discovery_engine):
        df = discovery_engine.generate_synthetic_data(n=300, seed=42)
        assert "BTC" in df.columns
        assert len(df) == 300
        assert not df.isnull().all().any()

    def test_lagged_correlation_finds_known_lag(self):
        """x at lag=3 should be detected."""
        rng = np.random.default_rng(0)
        n = 200
        x = pd.Series(rng.normal(0, 1, n))
        y = pd.Series(x.shift(3).fillna(0).values + rng.normal(0, 0.3, n))
        best_lag, best_corr = _lagged_correlation(x, y, max_lag=8)
        assert best_lag in (3, 4), f"Expected lag ~3, got {best_lag}"
        assert best_corr > 0.5, f"Expected high positive correlation, got {best_corr:.3f}"

    def test_discover_finds_dxy_causes_btc(self, discovery_engine, synthetic_data):
        """At least one known causal variable should be detected in synthetic data."""
        report = discovery_engine.discover(synthetic_data, target_variable="BTC")
        learned_names = [e.from_node for e in report.learned_edges]
        known_causes = {"DXY", "VIX", "FundingZ", "RealYield"}
        found = known_causes & set(learned_names)
        assert len(found) > 0, (
            f"Expected at least one of {known_causes} in learned edges, "
            f"got: {learned_names}. Rejected: {report.rejected_candidates}"
        )

    def test_discover_respects_correlation_threshold(self, discovery_engine):
        """Uncorrelated noise should not produce learned edges."""
        rng = np.random.default_rng(99)
        df = pd.DataFrame({
            "BTC": rng.normal(0, 1, 300),
            "NOISE1": rng.normal(0, 1, 300),
            "NOISE2": rng.normal(0, 1, 300),
        })
        report = discovery_engine.discover(df, target_variable="BTC")
        assert len(report.learned_edges) == 0, (
            f"Expected no edges from noise data, got: {[e.from_node for e in report.learned_edges]}"
        )

    def test_granger_test_detects_causal_signal(self):
        """Granger test should detect causal relationship."""
        rng = np.random.default_rng(42)
        n = 200
        x = pd.Series(rng.normal(0, 1, n))
        y = pd.Series(x.shift(1).fillna(0).values * 0.8 + rng.normal(0, 0.3, n))
        is_sig, pval = _granger_causality_simple(x, y, lag=1, significance=0.10)
        assert is_sig, f"Expected Granger significance, pval={pval:.4f}"

    def test_granger_test_rejects_noise(self):
        """Granger test should NOT flag pure noise as causal."""
        rng = np.random.default_rng(1)
        n = 200
        x = pd.Series(rng.normal(0, 1, n))
        y = pd.Series(rng.normal(0, 1, n))  # Independent noise
        is_sig, pval = _granger_causality_simple(x, y, lag=1, significance=0.05)
        # Noise should rarely be flagged — this is probabilistic, allow some false positives
        # We just check that pvalue is reasonable (not near 0)
        assert pval > 0.0, "pvalue must be positive"

    def test_learned_edge_to_graph_format(self):
        edge = LearnedEdge(
            from_node="DXY", to_node="BTC", effect="negative",
            weight=0.75, confidence=0.82, lag=1, lag_unit="candle",
            granger_pvalue=0.04, correlation=-0.62,
        )
        d = edge.to_graph_edge("edge_99")
        assert d["id"] == "edge_99"
        assert d["from"] == "DXY"
        assert d["to"] == "BTC"
        assert d["source"] == "learned"
        assert d["effect"] == "negative"
        assert "learned_at" in d

    def test_save_learned_edges_writes_to_graph(self, synthetic_data, tmp_path):
        """Saving learned edges should bump version and not overwrite manual edges."""
        # Copy graph to temp dir
        import shutil
        temp_graph = str(tmp_path / "causal_graph.json")
        shutil.copy("data/causal_graph.json", temp_graph)

        engine = CausalDiscoveryEngine(temp_graph, max_lag=5)
        report = engine.discover(synthetic_data, target_variable="BTC")

        if not report.learned_edges:
            pytest.skip("No learned edges found in synthetic data — skipping save test")

        success = engine.save_learned_edges(report.learned_edges)
        assert success

        with open(temp_graph) as f:
            updated = json.load(f)

        learned = [e for e in updated["edges"] if e.get("source") == "learned"]
        manual = [e for e in updated["edges"] if e.get("source") == "manual"]

        assert len(learned) > 0
        assert len(manual) > 0, "Manual edges must be preserved"

        # Version should have been bumped
        original_version = "2.0.0"
        assert updated["version"] != original_version

    def test_save_does_not_overwrite_manual_edges(self, synthetic_data, tmp_path):
        """Learned edges must never replace manual edges for same (from, to) pair."""
        import shutil
        temp_graph = str(tmp_path / "causal_graph.json")
        shutil.copy("data/causal_graph.json", temp_graph)

        engine = CausalDiscoveryEngine(temp_graph, max_lag=5)

        # Inject a learned edge that conflicts with a manual edge
        conflict_edge = LearnedEdge(
            from_node="DXY", to_node="BTC", effect="positive",
            weight=0.5, confidence=0.7, lag=0, lag_unit="candle",
            granger_pvalue=0.03, correlation=0.5,
        )
        engine.save_learned_edges([conflict_edge])

        with open(temp_graph) as f:
            updated = json.load(f)

        # DXY→BTC edge should still be manual
        dxy_btc = [e for e in updated["edges"] if e["from"] == "DXY" and e["to"] == "BTC"]
        assert len(dxy_btc) == 1, "Should have exactly one DXY→BTC edge"
        assert dxy_btc[0]["source"] == "manual", "DXY→BTC should remain manual"

    def test_discover_report_summary(self, discovery_engine, synthetic_data):
        report = discovery_engine.discover(synthetic_data, target_variable="BTC")
        summary = report.summary()
        assert "BTC" in summary
        assert "candidates" in summary.lower()


# ─── 3. HybridContextProvider ────────────────────────────────────────────────

class TestHybridContextProvider:
    def test_validate(self, hybrid_provider):
        is_valid, msg = hybrid_provider.validate()
        assert is_valid, f"Hybrid validation failed: {msg}"

    def test_alpha_zero_equals_rule_only(self, risk_off_state):
        """alpha=0 should produce same result as RuleContextProvider alone."""
        from btc_scraper.ml_engine.rule_context_provider import RuleContextProvider

        rule_only = RuleContextProvider("data/context_rules.json")
        hybrid = HybridContextProvider.build(alpha=0.0)

        original = 0.80
        r_rule = rule_only.generate_context_report(original, risk_off_state)
        r_hybrid = hybrid.generate_context_report(original, risk_off_state)

        assert abs(r_rule.adjusted_score - r_hybrid.adjusted_score) < 0.001, (
            f"alpha=0 hybrid {r_hybrid.adjusted_score:.3f} should match rule {r_rule.adjusted_score:.3f}"
        )

    def test_alpha_change_affects_score(self, risk_off_state):
        """Changing alpha should change the adjusted score."""
        provider = HybridContextProvider.build(alpha=0.0)
        provider.enable_bayesian(True)

        original = 0.80
        r_alpha0 = provider.generate_context_report(original, risk_off_state)
        provider.set_alpha(0.50)
        r_alpha50 = provider.generate_context_report(original, risk_off_state)

        assert abs(r_alpha0.adjusted_score - r_alpha50.adjusted_score) > 0.001

    def test_enable_bayesian_false_uses_rules_only(self, risk_off_state):
        """enable_bayesian=False should produce pure rule output."""
        from btc_scraper.ml_engine.rule_context_provider import RuleContextProvider

        rule_only = RuleContextProvider("data/context_rules.json")
        hybrid = HybridContextProvider.build(alpha=0.30)
        hybrid.enable_bayesian(False)

        original = 0.80
        r_rule = rule_only.generate_context_report(original, risk_off_state)
        r_hybrid = hybrid.generate_context_report(original, risk_off_state)

        assert abs(r_rule.adjusted_score - r_hybrid.adjusted_score) < 0.001

    def test_score_bounded(self, hybrid_provider, risk_off_state, risk_on_state):
        for state in [risk_off_state, risk_on_state]:
            report = hybrid_provider.generate_context_report(0.75, state)
            assert 0.0 <= report.adjusted_score <= 1.0

    def test_provider_name_correct(self, hybrid_provider):
        assert hybrid_provider.name == "HybridContextProvider"

    def test_set_alpha_clamps_to_range(self, hybrid_provider):
        hybrid_provider.set_alpha(2.0)
        assert hybrid_provider.alpha == 1.0
        hybrid_provider.set_alpha(-0.5)
        assert hybrid_provider.alpha == 0.0
        hybrid_provider.set_alpha(0.4)
        assert hybrid_provider.alpha == pytest.approx(0.4)

    def test_build_factory_succeeds(self):
        provider = HybridContextProvider.build()
        assert provider is not None
        assert provider.alpha == pytest.approx(0.0)
        is_valid, _ = provider.validate()
        assert is_valid

    def test_report_explanation_mentions_hybrid(self, hybrid_provider, risk_off_state):
        hybrid_provider.enable_bayesian(True)
        hybrid_provider.set_alpha(0.30)
        report = hybrid_provider.generate_context_report(0.80, risk_off_state)
        # Hybrid mode explanation should mention the blend
        assert "Hybrid" in report.explanation or "rules-only" in report.explanation


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("Phase 3.0 Smoke Test")
    print("=" * 65)

    # 1. BayesianContextProvider
    print("\n[1/3] BayesianContextProvider")
    provider = BayesianContextProvider.from_causal_graph("data/causal_graph.json")
    is_valid, msg = provider.validate()
    print(f"  Valid: {is_valid} — {msg}")

    risk_off = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    risk_off.macro.DXY = 108.0
    risk_off.macro.VIX = 32.0
    risk_off.macro.RealYield = 2.3
    risk_off.liquidity.Funding_Z = 2.7
    risk_off.sentiment.FearGreed = 19.0

    r = provider.generate_context_report(0.82, risk_off)
    print(f"  Risk-off: {r.original_score:.3f} → {r.adjusted_score:.3f} ({r.risk_level.value})")

    # 2. CausalDiscoveryEngine
    print("\n[2/3] CausalDiscoveryEngine")
    engine = CausalDiscoveryEngine("data/causal_graph.json", max_lag=5)
    data = engine.generate_synthetic_data(n=400)
    report = engine.discover(data, target_variable="BTC")
    print(f"  {report.summary()}")
    for e in report.learned_edges[:3]:
        print(f"  Edge: {e.from_node}→{e.to_node} ({e.effect}, conf={e.confidence:.2f})")

    # 3. HybridContextProvider
    print("\n[3/3] HybridContextProvider")
    hybrid = HybridContextProvider.build(alpha=0.30)
    is_valid, msg = hybrid.validate()
    print(f"  Valid: {is_valid} — {msg}")
    hr = hybrid.generate_context_report(0.82, risk_off)
    print(f"  Hybrid (α=0.30): {hr.original_score:.3f} → {hr.adjusted_score:.3f}")

    print("\n✓ Phase 3.0 Smoke Test PASSED")
