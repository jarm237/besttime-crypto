from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.s4_dataset_audit import (
    AUDIT_END,
    AuditError,
    LAMBDA,
    build_feature_tensor,
    causal_raw_sigma,
    feature_dependency_window,
    label_contract,
    run_synthetic_negative_tests,
)


def _panel(start: str = "2021-12-01", periods: int = 24 * 90) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="h", tz="UTC")
    step = np.arange(periods, dtype=float)
    close = 100 * np.exp(0.0001 * step + 0.001 * np.sin(step / 13))
    return pd.DataFrame(
        {
            "open": close * 0.9999,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": 1000 + step % 31,
        },
        index=index,
    )


def test_feature_contract_uses_exactly_336_closed_hours() -> None:
    panel = _panel()
    panels = {symbol: panel.copy() for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")}
    decision = pd.Timestamp("2022-01-15", tz="UTC")
    dependency = feature_dependency_window(decision)
    assert len(dependency) == 336
    assert dependency[-1] == decision - pd.Timedelta(hours=1)
    assert build_feature_tensor(panels, decision).shape == (168, 4, 6)
    panels["BTCUSDT"] = panels["BTCUSDT"].drop(decision - pd.Timedelta(hours=200))
    with pytest.raises(AuditError, match="MISSING_OR_INVALID_FEATURE_BAR"):
        build_feature_tensor(panels, decision)


def test_label_interval_and_authorized_end_fail_closed() -> None:
    panel = _panel("2023-10-01", 24 * 100)
    decision = pd.Timestamp("2023-11-01", tz="UTC")
    valid = label_contract(panel, decision)
    assert valid["valid"] is True
    assert valid["completion"] == pd.Timestamp("2023-11-02 01:00", tz="UTC")
    missing = label_contract(panel.drop(decision + pd.Timedelta(hours=13)), decision)
    assert missing["reason"] == "MISSING_BAR_IN_LABEL_INTERVAL"
    forbidden = label_contract(panel, pd.Timestamp("2023-12-31", tz="UTC"), AUDIT_END)
    assert forbidden["reason"] == "EXIT_AFTER_AUTHORIZED_WINDOW"


def test_sigma_uses_only_completed_labels_and_skips_missing() -> None:
    decisions = pd.date_range("2021-11-01", periods=35, freq="D", tz="UTC")
    labels = pd.DataFrame(
        {
            "valid": True,
            "value": np.linspace(-0.02, 0.03, len(decisions)),
            "completion": decisions + pd.Timedelta(days=1, hours=1),
        },
        index=decisions,
    )
    cutoff = pd.Timestamp("2021-12-03", tz="UTC")
    result = causal_raw_sigma(labels, [cutoff])
    assert result.iloc[0]["completed_count"] == 31
    assert result.iloc[0]["latest_completion"] <= cutoff
    assert np.isfinite(result.iloc[0]["raw_sigma"])
    assert LAMBDA == pytest.approx(2 ** (-1 / 20))
    labels.loc[decisions[5], "valid"] = False
    skipped = causal_raw_sigma(labels, [cutoff])
    assert skipped.iloc[0]["completed_count"] == 30


def test_all_precommitted_negative_leakage_tests_pass() -> None:
    assert run_synthetic_negative_tests() == {key: True for key in "ABCDEFG"}
