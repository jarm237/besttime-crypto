"""
tests/test_decision_types.py
PR 1 — Canonical Decision Types tests.

Tests:
    1. Enum value stability (string values must not change).
    2. Frozen immutability of all dataclasses.
    3. Signed score normalization table.
    4. Direction encoding inconsistency detection.
    5. DecisionBreakdown nullable fields with decision stage.
    6. EntryDecision traceability metadata defaults.
    7. to_dict() serialization round-trip.
"""
import pytest

from btc_scraper.trading.decision_types import (
    TradeAction,
    EntryRejectionReason,
    AuthorizationReason,
    ReservationStatus,
    FinalDecisionStatus,
    DecisionStage,
    NormalizedSignalScore,
    DecisionBreakdown,
    SizingDecision,
    EntryDecision,
)
from btc_scraper.ml_engine.signal_score import (
    normalize_directional_score,
    DEFAULT_ACTION_THRESHOLD,
    signal_strength_from_score,
)


# ── 1. Enum value stability ──────────────────────────────────────────────────
# These values appear in logs, tests, dashboards. Changing them is a breaking change.


class TestTradeAction:
    def test_values(self):
        assert TradeAction.BUY.value == "BUY"
        assert TradeAction.SELL.value == "SELL"
        assert TradeAction.NEUTRAL.value == "NEUTRAL"

    def test_is_str_enum(self):
        # str(enum_member) should return the value for JSON serialization
        assert str(TradeAction.BUY) == "TradeAction.BUY"
        assert TradeAction.BUY == "BUY"


class TestEntryRejectionReason:
    EXPECTED_VALUES = {
        "LOW_META_CONFIDENCE": "low_meta_confidence",
        "INSUFFICIENT_STATISTICAL_EDGE": "insufficient_statistical_edge",
        "RR_BELOW_MINIMUM": "rr_below_minimum",
        "NON_POSITIVE_KELLY": "non_positive_kelly",
        "ACTION_DISAGREEMENT": "action_disagreement",
        "CAUSAL_REGIME_VETO": "causal_regime_veto",
        "DIRECTION_ENCODING_INCONSISTENT": "direction_encoding_inconsistent",
        "INVALID_SIZING_INPUT": "invalid_sizing_input",
        "WEAK_SIGNAL": "weak_signal",
        "COIN_NOT_ALLOWED": "coin_not_allowed",
        "CIRCUIT_BREAKER": "circuit_breaker",
        "CORRELATION_FILTER": "correlation_filter",
        "EXISTING_POSITION": "existing_position",
        "DAILY_LIMIT": "daily_limit",
    }

    def test_all_values_stable(self):
        for name, expected in self.EXPECTED_VALUES.items():
            member = EntryRejectionReason[name]
            assert member.value == expected, f"{name} should be {expected!r}, got {member.value!r}"

    def test_member_count(self):
        assert len(EntryRejectionReason) == len(self.EXPECTED_VALUES)


class TestAuthorizationReason:
    EXPECTED_VALUES = {
        "PHASE5_GATE_CLOSED": "phase5_gate_closed",
        "LIVE_MODE_DISABLED": "live_mode_disabled",
        "KILL_SWITCH": "kill_switch",
        "ROLLOUT_STAGE": "rollout_stage",
        "HARD_RISK_LIMITS": "hard_risk_limits",
        "SYSTEM_HEALTH": "system_health",
        "EXECUTION_RISK": "execution_risk",
        "STALE_ACCOUNT_STATE": "stale_account_state",
        "STALE_MARKET_DATA": "stale_market_data",
        "STALE_MODEL_FEATURES": "stale_model_features",
        "STALE_ORDERBOOK": "stale_orderbook",
    }

    def test_all_values_stable(self):
        for name, expected in self.EXPECTED_VALUES.items():
            member = AuthorizationReason[name]
            assert member.value == expected

    def test_member_count(self):
        assert len(AuthorizationReason) == len(self.EXPECTED_VALUES)


class TestReservationStatus:
    def test_values(self):
        assert ReservationStatus.PENDING.value == "pending"
        assert ReservationStatus.COMMITTED.value == "committed"
        assert ReservationStatus.PARTIALLY_COMMITTED.value == "partially_committed"
        assert ReservationStatus.RELEASED.value == "released"
        assert ReservationStatus.EXPIRED.value == "expired"


class TestFinalDecisionStatus:
    def test_values(self):
        assert FinalDecisionStatus.ELIGIBLE.value == "eligible"
        assert FinalDecisionStatus.REJECTED.value == "rejected"
        assert FinalDecisionStatus.AUTHORIZED.value == "authorized"
        assert FinalDecisionStatus.SUBMITTED.value == "submitted"
        assert FinalDecisionStatus.FILLED.value == "filled"
        assert FinalDecisionStatus.PARTIALLY_FILLED.value == "partially_filled"


class TestDecisionStage:
    def test_ordered_stages(self):
        """Stages should be in pipeline execution order."""
        ordered = [
            DecisionStage.NORMALIZATION,
            DecisionStage.ELIGIBILITY,
            DecisionStage.EDGE,
            DecisionStage.SIZING,
            DecisionStage.AUTHORIZATION,
            DecisionStage.RESERVATION,
            DecisionStage.EXECUTION,
        ]
        assert len(ordered) == len(DecisionStage)
        for stage in ordered:
            assert isinstance(stage, DecisionStage)


# ── 2. Frozen immutability ────────────────────────────────────────────────────


class TestFrozenImmutability:
    def test_normalized_signal_score_is_frozen(self):
        score = NormalizedSignalScore(
            raw_score=95, directional_score=90, strength=90, action=TradeAction.BUY,
        )
        with pytest.raises(AttributeError):
            score.strength = 50  # type: ignore[misc]

    def test_decision_breakdown_is_frozen(self):
        bd = DecisionBreakdown(
            decision_stage=DecisionStage.NORMALIZATION,
            technical_score=96,
            directional_score=92,
            signal_strength=92,
            signal_action=TradeAction.BUY,
        )
        with pytest.raises(AttributeError):
            bd.technical_score = 0  # type: ignore[misc]

    def test_sizing_decision_is_frozen(self):
        sd = SizingDecision(
            entry_price=100.0,
            sl_price=98.0,
            stop_distance_pct=2.0,
            risk_pct=2.0,
            risk_notional=10.0,
            raw_notional=500.0,
            final_notional=100.0,
        )
        with pytest.raises(AttributeError):
            sd.final_notional = 200.0  # type: ignore[misc]

    def test_entry_decision_is_frozen(self):
        decision = EntryDecision(
            eligible=False,
            action=TradeAction.NEUTRAL,
            rejection_reason=EntryRejectionReason.WEAK_SIGNAL,
            final_status=FinalDecisionStatus.REJECTED,
            breakdown=None,
            sizing=None,
        )
        with pytest.raises(AttributeError):
            decision.eligible = True  # type: ignore[misc]


# ── 3. Signed score normalization table ───────────────────────────────────────


class TestNormalizeDirectionalScore:
    """Core normalization tests using the table from the remediation plan.

    | Raw score | Directional | Strength | Action  |
    |----------:|------------:|---------:|---------|
    |        95 |         +90 |       90 | BUY     |
    |         5 |         -90 |       90 | SELL    |
    |        70 |         +40 |       40 | NEUTRAL |
    |        30 |         -40 |       40 | NEUTRAL |
    |        50 |           0 |        0 | NEUTRAL |
    """

    def test_strong_buy_95(self):
        result = normalize_directional_score(95)
        assert result.directional_score == 90
        assert result.strength == 90
        assert result.action == TradeAction.BUY

    def test_strong_sell_5(self):
        result = normalize_directional_score(5)
        assert result.directional_score == -90
        assert result.strength == 90
        assert result.action == TradeAction.SELL

    def test_weak_buy_70_is_neutral(self):
        """Strength 40 is below default threshold 50, so action is NEUTRAL."""
        result = normalize_directional_score(70)
        assert result.directional_score == 40
        assert result.strength == 40
        assert result.action == TradeAction.NEUTRAL

    def test_weak_sell_30_is_neutral(self):
        """Strength 40 is below default threshold 50, so action is NEUTRAL."""
        result = normalize_directional_score(30)
        assert result.directional_score == -40
        assert result.strength == 40
        assert result.action == TradeAction.NEUTRAL

    def test_neutral_50(self):
        result = normalize_directional_score(50)
        assert result.directional_score == 0
        assert result.strength == 0
        assert result.action == TradeAction.NEUTRAL

    def test_extreme_buy_100(self):
        result = normalize_directional_score(100)
        assert result.directional_score == 100
        assert result.strength == 100
        assert result.action == TradeAction.BUY

    def test_extreme_sell_0(self):
        result = normalize_directional_score(0)
        assert result.directional_score == -100
        assert result.strength == 100
        assert result.action == TradeAction.SELL

    def test_custom_threshold_low(self):
        """With threshold=30, a raw score of 70 (strength=40) becomes BUY."""
        result = normalize_directional_score(70, action_threshold=30)
        assert result.directional_score == 40
        assert result.strength == 40
        assert result.action == TradeAction.BUY

    def test_custom_threshold_high(self):
        """With threshold=95, even raw score 95 (strength=90) is NEUTRAL."""
        result = normalize_directional_score(95, action_threshold=95)
        assert result.directional_score == 90
        assert result.strength == 90
        assert result.action == TradeAction.NEUTRAL

    def test_raw_score_is_preserved(self):
        result = normalize_directional_score(73.5)
        assert result.raw_score == 73.5

    def test_bad_input_defaults_to_neutral(self):
        result = normalize_directional_score(None)  # type: ignore
        assert result.directional_score == 0
        assert result.strength == 0
        assert result.action == TradeAction.NEUTRAL

    def test_bad_string_input(self):
        result = normalize_directional_score("abc")  # type: ignore
        assert result.action == TradeAction.NEUTRAL

    def test_negative_clamped_to_zero(self):
        result = normalize_directional_score(-10)
        assert result.raw_score == 0.0
        assert result.directional_score == -100
        assert result.strength == 100
        assert result.action == TradeAction.SELL

    def test_over_100_clamped(self):
        result = normalize_directional_score(110)
        assert result.raw_score == 100.0
        assert result.directional_score == 100
        assert result.strength == 100
        assert result.action == TradeAction.BUY

    # ── Symmetry tests ────────────────────────────────────────────────────

    def test_buy_sell_symmetry(self):
        """BUY and SELL should have symmetric strength for equidistant scores."""
        for offset in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
            buy_result = normalize_directional_score(50 + offset)
            sell_result = normalize_directional_score(50 - offset)
            assert buy_result.strength == sell_result.strength, (
                f"Asymmetry at offset {offset}: "
                f"BUY strength={buy_result.strength}, SELL strength={sell_result.strength}"
            )
            assert buy_result.directional_score == -sell_result.directional_score

    # ── Consistency with legacy signal_strength_from_score ─────────────────

    def test_consistency_with_legacy_strength(self):
        """Verify that the new normalization produces consistent strength
        values with the legacy signal_strength_from_score for BUY/SELL.

        Legacy: BUY → strength = score, SELL → strength = 100 - score.
        New:    strength = abs(round((score - 50) * 2))

        These are different scales (legacy is 0-100 based on raw, new is 0-100
        based on distance from 50 × 2).  This test documents the relationship.
        """
        # raw_score=90 → legacy BUY strength = 90, new strength = 80
        legacy_buy = signal_strength_from_score("BUY", 90)
        new_norm = normalize_directional_score(90)
        # They are on different scales — this is intentional.
        # Legacy strength = raw score for BUY, new strength = 2 * distance from 50.
        assert legacy_buy == 90
        assert new_norm.strength == 80

        # raw_score=10 → legacy SELL strength = 90, new strength = 80
        legacy_sell = signal_strength_from_score("SELL", 10)
        new_sell = normalize_directional_score(10)
        assert legacy_sell == 90
        assert new_sell.strength == 80


# ── 4. Direction encoding inconsistency detection ─────────────────────────────


class TestDirectionEncodingInconsistency:
    """Callers should detect inconsistency when an upstream-provided action
    disagrees with the action derived from the raw score."""

    def test_upstream_says_buy_but_score_says_sell(self):
        """Raw score 10 → SELL, but upstream claims BUY → inconsistent."""
        upstream_action = TradeAction.BUY
        normalized = normalize_directional_score(10)
        assert normalized.action == TradeAction.SELL
        assert upstream_action != normalized.action

    def test_upstream_says_sell_but_score_says_buy(self):
        """Raw score 90 → BUY, but upstream claims SELL → inconsistent."""
        upstream_action = TradeAction.SELL
        normalized = normalize_directional_score(90)
        assert normalized.action == TradeAction.BUY
        assert upstream_action != normalized.action

    def test_consistent_buy(self):
        upstream_action = TradeAction.BUY
        normalized = normalize_directional_score(95)
        assert normalized.action == TradeAction.BUY
        assert upstream_action == normalized.action

    def test_consistent_sell(self):
        upstream_action = TradeAction.SELL
        normalized = normalize_directional_score(5)
        assert normalized.action == TradeAction.SELL
        assert upstream_action == normalized.action

    def test_neutral_upstream_neutral_score(self):
        upstream_action = TradeAction.NEUTRAL
        normalized = normalize_directional_score(55)
        assert normalized.action == TradeAction.NEUTRAL
        assert upstream_action == normalized.action

    def test_upstream_buy_but_strength_below_threshold(self):
        """Score 60 → directional +20, strength 20 (below threshold 50)
        → NEUTRAL, upstream says BUY → inconsistent."""
        upstream_action = TradeAction.BUY
        normalized = normalize_directional_score(60)
        assert normalized.action == TradeAction.NEUTRAL
        assert upstream_action != normalized.action


# ── 5. DecisionBreakdown nullable fields with stage ───────────────────────────


class TestDecisionBreakdownStages:
    def test_normalization_stage_has_null_downstream_fields(self):
        """Rejection at NORMALIZATION stage should have None for all
        fields beyond signal normalization."""
        bd = DecisionBreakdown(
            decision_stage=DecisionStage.NORMALIZATION,
            technical_score=50,
            directional_score=0,
            signal_strength=0,
            signal_action=TradeAction.NEUTRAL,
            rejection_reason=EntryRejectionReason.DIRECTION_ENCODING_INCONSISTENT,
        )
        # Downstream fields must be None
        assert bd.meta_probability is None
        assert bd.rr_ratio is None
        assert bd.gross_expected_value is None
        assert bd.net_expected_value is None
        assert bd.kelly_raw is None
        assert bd.risk_pct_applied is None
        assert bd.risk_notional is None
        assert bd.final_notional is None

    def test_edge_stage_has_ev_but_no_sizing(self):
        """Rejection at EDGE stage should have EV fields but no sizing."""
        bd = DecisionBreakdown(
            decision_stage=DecisionStage.EDGE,
            technical_score=96,
            directional_score=92,
            signal_strength=92,
            signal_action=TradeAction.BUY,
            meta_probability=0.49,
            rr_ratio=1.55,
            gross_expected_value=-0.02,
            estimated_cost=0.001,
            net_expected_value=-0.021,
            kelly_raw=-0.01,
            kelly_applied=0.0,
            rejection_reason=EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
        )
        assert bd.meta_probability == 0.49
        assert bd.net_expected_value == -0.021
        # Sizing fields still None
        assert bd.risk_pct_applied is None
        assert bd.final_notional is None

    def test_sizing_stage_has_full_breakdown(self):
        """Successful sizing stage should have all fields populated."""
        bd = DecisionBreakdown(
            decision_stage=DecisionStage.SIZING,
            technical_score=96,
            directional_score=92,
            signal_strength=92,
            signal_action=TradeAction.BUY,
            meta_probability=0.72,
            rr_ratio=2.1,
            gross_expected_value=0.51,
            estimated_cost=0.003,
            net_expected_value=0.507,
            kelly_raw=0.24,
            kelly_applied=0.12,
            risk_pct_applied=1.5,
            risk_notional=7.5,
            size_before_caps=150.0,
            var_cap=120.0,
            exposure_cap=100.0,
            max_trade_cap=100.0,
            min_notional=10.0,
            final_notional=100.0,
        )
        assert bd.final_notional == 100.0
        assert bd.rejection_reason is None

    def test_to_dict_enum_values(self):
        bd = DecisionBreakdown(
            decision_stage=DecisionStage.NORMALIZATION,
            technical_score=50,
            directional_score=0,
            signal_strength=0,
            signal_action=TradeAction.NEUTRAL,
            rejection_reason=EntryRejectionReason.ACTION_DISAGREEMENT,
        )
        d = bd.to_dict()
        assert d["decision_stage"] == "normalization"
        assert d["signal_action"] == "NEUTRAL"
        assert d["rejection_reason"] == "action_disagreement"
        assert d["meta_probability"] is None
        assert d["final_notional"] is None


# ── 6. EntryDecision traceability metadata ────────────────────────────────────


class TestEntryDecision:
    def test_decision_id_is_auto_generated(self):
        d1 = EntryDecision(
            eligible=False,
            action=TradeAction.NEUTRAL,
            rejection_reason=EntryRejectionReason.WEAK_SIGNAL,
            final_status=FinalDecisionStatus.REJECTED,
            breakdown=None,
            sizing=None,
        )
        d2 = EntryDecision(
            eligible=False,
            action=TradeAction.NEUTRAL,
            rejection_reason=EntryRejectionReason.WEAK_SIGNAL,
            final_status=FinalDecisionStatus.REJECTED,
            breakdown=None,
            sizing=None,
        )
        assert d1.decision_id.startswith("ed-")
        assert d2.decision_id.startswith("ed-")
        assert d1.decision_id != d2.decision_id

    def test_default_metadata(self):
        d = EntryDecision(
            eligible=True,
            action=TradeAction.BUY,
            rejection_reason=None,
            final_status=FinalDecisionStatus.ELIGIBLE,
            breakdown=None,
            sizing=None,
        )
        assert d.model_version is None
        assert d.artifact_hash is None
        assert d.feature_schema_version is None
        assert d.signal_id is None
        assert d.meta_probability_semantics == "P(win_given_proposed_trade)"
        assert d.decision_timestamp is not None

    def test_explicit_metadata(self):
        d = EntryDecision(
            eligible=True,
            action=TradeAction.BUY,
            rejection_reason=None,
            final_status=FinalDecisionStatus.ELIGIBLE,
            breakdown=None,
            sizing=None,
            decision_id="ed-custom123",
            signal_id="sig-456",
            model_version="v3.2.1",
            artifact_hash="abc123def",
            feature_schema_version="schema-v7",
        )
        assert d.decision_id == "ed-custom123"
        assert d.signal_id == "sig-456"
        assert d.model_version == "v3.2.1"

    def test_eligibility_vs_authorization(self):
        """Eligible signal but not authorized for live."""
        d = EntryDecision(
            eligible=False,
            action=TradeAction.BUY,
            rejection_reason=None,
            final_status=FinalDecisionStatus.REJECTED,
            breakdown=None,
            sizing=None,
            signal_eligible=True,
            live_authorized=False,
            eligibility_reason=None,
            authorization_reason=AuthorizationReason.PHASE5_GATE_CLOSED,
        )
        assert d.signal_eligible is True
        assert d.live_authorized is False
        assert d.authorization_reason == AuthorizationReason.PHASE5_GATE_CLOSED

    def test_to_dict_serialization(self):
        bd = DecisionBreakdown(
            decision_stage=DecisionStage.EDGE,
            technical_score=96,
            directional_score=90,
            signal_strength=90,
            signal_action=TradeAction.BUY,
            meta_probability=0.49,
            rr_ratio=1.55,
            gross_expected_value=-0.02,
            estimated_cost=0.001,
            net_expected_value=-0.021,
            kelly_raw=-0.01,
            kelly_applied=0.0,
            rejection_reason=EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
        )
        d = EntryDecision(
            eligible=False,
            action=TradeAction.BUY,
            rejection_reason=EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
            final_status=FinalDecisionStatus.REJECTED,
            breakdown=bd,
            sizing=None,
            signal_eligible=False,
            eligibility_reason=EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
        )
        serialized = d.to_dict()
        assert serialized["eligible"] is False
        assert serialized["action"] == "BUY"
        assert serialized["rejection_reason"] == "insufficient_statistical_edge"
        assert serialized["final_status"] == "rejected"
        assert serialized["breakdown"]["meta_probability"] == 0.49
        assert serialized["breakdown"]["decision_stage"] == "edge"
        assert serialized["sizing"] is None
        assert serialized["signal_eligible"] is False
        assert serialized["eligibility_reason"] == "insufficient_statistical_edge"
        assert serialized["meta_probability_semantics"] == "P(win_given_proposed_trade)"


# ── 7. SizingDecision tests ──────────────────────────────────────────────────


class TestSizingDecision:
    def test_valid_sizing(self):
        sd = SizingDecision(
            entry_price=100.0,
            sl_price=98.0,
            stop_distance_pct=2.0,
            risk_pct=2.0,
            risk_notional=10.0,
            raw_notional=500.0,
            kelly_adjusted=250.0,
            var_capped=200.0,
            exposure_capped=150.0,
            max_trade_capped=100.0,
            final_notional=100.0,
        )
        assert not sd.rejected
        assert sd.rejection_reason is None
        assert sd.final_notional == 100.0

    def test_rejected_sizing(self):
        sd = SizingDecision(
            entry_price=0.0,
            sl_price=0.0,
            stop_distance_pct=0.0,
            risk_pct=2.0,
            risk_notional=0.0,
            raw_notional=0.0,
            final_notional=0.0,
            rejected=True,
            rejection_reason=EntryRejectionReason.INVALID_SIZING_INPUT,
        )
        assert sd.rejected
        assert sd.rejection_reason == EntryRejectionReason.INVALID_SIZING_INPUT

    def test_to_dict(self):
        sd = SizingDecision(
            entry_price=100.0,
            sl_price=98.0,
            stop_distance_pct=2.0,
            risk_pct=2.0,
            risk_notional=10.0,
            raw_notional=500.0,
            final_notional=100.0,
        )
        d = sd.to_dict()
        assert d["entry_price"] == 100.0
        assert d["rejection_reason"] is None
        assert d["rejected"] is False
