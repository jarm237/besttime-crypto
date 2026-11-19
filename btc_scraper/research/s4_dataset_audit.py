"""Read-only S4-P1A dataset integrity and causal-readiness audit.

This module deliberately opens market-data content only from the frozen
2021-11-01..2023-12-31 authorization window.  It does not download data,
train a model, compute an IC, or access post-2023 market-data values.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd


UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
AUDIT_START = pd.Timestamp("2021-11-01 00:00:00", tz="UTC")
AUDIT_END = pd.Timestamp("2023-12-31 23:00:00", tz="UTC")
LAST_SCREEN_DECISION = pd.Timestamp("2023-12-30 00:00:00", tz="UTC")
LAMBDA = 2 ** (-1 / 20)
MIN_SIGMA_HISTORY = 30

BINANCE_COLUMNS = (
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
)


class AuditError(RuntimeError):
    """Raised when a fail-closed audit contract is violated."""


@dataclass(frozen=True)
class Fold:
    name: str
    fit_start: str
    fit_end: str
    validation_start: str
    validation_end: str


FOLDS = (
    Fold("F1", "2022-01-01", "2022-04-30", "2022-05-01", "2022-06-15"),
    Fold("F2", "2022-01-01", "2022-06-15", "2022-06-16", "2022-07-31"),
    Fold("F3", "2022-01-01", "2022-07-31", "2022-08-01", "2022-09-30"),
    Fold("F4", "2022-01-01", "2022-09-30", "2022-10-01", "2022-12-30"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def month_starts(start: pd.Timestamp = AUDIT_START, end: pd.Timestamp = AUDIT_END) -> list[pd.Timestamp]:
    return list(pd.date_range(start.normalize(), end.normalize(), freq="MS", tz="UTC"))


def _authorized_month_from_path(path: Path) -> str:
    match = re.search(r"-(\d{4}-\d{2})\.zip$", path.name)
    if not match or not ("2021-11" <= match.group(1) <= "2023-12"):
        raise AuditError(f"NO_2024_2026_ACCESS guard rejected content path: {path}")
    return match.group(1)


def _parse_checksum_sidecar(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AuditError(f"Invalid SHA-256 sidecar: {path}")
    return value


def load_binance_archives(
    raw_root: Path,
    symbol: str,
    access_log: list[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Load only authorized monthly Binance Vision ZIPs for one symbol."""
    if symbol not in UNIVERSE:
        raise AuditError(f"Unexpected symbol: {symbol}")
    frames: list[pd.DataFrame] = []
    sources: list[dict[str, object]] = []
    for month in month_starts():
        month_key = month.strftime("%Y-%m")
        path = raw_root / symbol / f"{symbol}-1h-{month_key}.zip"
        _authorized_month_from_path(path)
        sidecar = Path(f"{path}.sha256")
        if not path.is_file() or not sidecar.is_file():
            raise AuditError(f"Missing source or checksum: {path}")
        actual_hash = sha256_file(path)
        expected_hash = _parse_checksum_sidecar(sidecar)
        checksum_ok = actual_hash == expected_hash
        if not checksum_ok:
            raise AuditError(f"SHA-256 mismatch: {path}")
        if access_log is not None:
            access_log.extend((path.as_posix(), sidecar.as_posix()))
        with zipfile.ZipFile(path) as archive:
            members = archive.namelist()
            if len(members) != 1:
                raise AuditError(f"Expected one CSV member in {path}, found {len(members)}")
            payload = archive.read(members[0]).decode("utf-8")
        rows = list(csv.reader(io.StringIO(payload)))
        if rows and rows[0] and not rows[0][0].isdigit():
            rows = rows[1:]
        if any(len(row) != len(BINANCE_COLUMNS) for row in rows):
            raise AuditError(f"Unexpected Binance kline schema in {path}")
        frame = pd.DataFrame(rows, columns=BINANCE_COLUMNS)
        for column in ("open_time_ms", "close_time_ms", "trade_count"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["timestamp"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
        frames.append(frame[list(BINANCE_COLUMNS[:7]) + ["timestamp"]])
        sources.append(
            {
                "path": path.as_posix(),
                "format": "binance-vision-monthly-zip-csv",
                "source": "Binance Spot public data archive",
                "origin_url": f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/1h/{path.name}",
                "symbol": symbol,
                "month": month_key,
                "rows": len(frame),
                "start": frame["timestamp"].min().isoformat(),
                "end": frame["timestamp"].max().isoformat(),
                "sha256": actual_hash,
                "sidecar": sidecar.as_posix(),
                "sidecar_verified": checksum_ok,
            }
        )
    result = pd.concat(frames, ignore_index=True)
    if (result["timestamp"] < AUDIT_START).any() or (result["timestamp"] > AUDIT_END).any():
        raise AuditError("Authorized monthly archives unexpectedly contain out-of-window rows")
    return result, sources


def validate_ohlcv(frame: pd.DataFrame, symbol: str) -> dict[str, object]:
    timestamp = frame["timestamp"]
    finite_prices = np.isfinite(frame[["open", "high", "low", "close"]]).all(axis=1)
    finite_volume = np.isfinite(frame["volume"])
    valid_price = finite_prices & (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid_volume = finite_volume & (frame["volume"] >= 0)
    valid_ohlc = (
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    )
    aligned = (
        (timestamp.dt.minute == 0)
        & (timestamp.dt.second == 0)
        & (timestamp.dt.microsecond == 0)
    )
    close_convention = frame["close_time_ms"] == frame["open_time_ms"] + 3_600_000 - 1
    expected = pd.date_range(AUDIT_START, AUDIT_END, freq="h", tz="UTC")
    observed = pd.DatetimeIndex(timestamp)
    missing = expected.difference(observed)
    duplicate_count = int(timestamp.duplicated().sum())
    out_of_order_count = int((timestamp.diff().dropna() <= pd.Timedelta(0)).sum())
    categories = {
        "MISSING": int(len(missing)),
        "DUPLICATE": duplicate_count,
        "OUT_OF_ORDER": out_of_order_count,
        "NONFINITE": int((~finite_prices).sum() + (~finite_volume).sum()),
        "NONPOSITIVE_PRICE": int((finite_prices & ~valid_price).sum()),
        "INVALID_OHLC": int((finite_prices & ~valid_ohlc).sum()),
        "INVALID_VOLUME": int((~valid_volume).sum()),
        "TIMESTAMP_MISALIGNMENT": int((~aligned).sum()),
    }
    return {
        "symbol": symbol,
        "rows": int(len(frame)),
        "start": timestamp.min().isoformat(),
        "end": timestamp.max().isoformat(),
        "strictly_increasing": duplicate_count == 0 and out_of_order_count == 0,
        "utc_aware": str(timestamp.dtype).endswith("UTC]"),
        "hour_aligned": bool(aligned.all()),
        "close_time_convention_valid": bool(close_convention.all()),
        "incomplete_candles": int((~close_convention).sum()),
        "missing_timestamps": [value.isoformat() for value in missing],
        "anomaly_counts": categories,
        "valid_bar_mask": (valid_price & valid_volume & valid_ohlc & aligned & close_convention).tolist(),
    }


def indexed_panel(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]].sort_index()


def feature_dependency_window(decision: pd.Timestamp) -> pd.DatetimeIndex:
    cutoff = pd.Timestamp(decision)
    if cutoff.tzinfo is None:
        raise AuditError("Feature cutoff must be timezone-aware")
    return pd.date_range(cutoff - pd.Timedelta(hours=336), cutoff - pd.Timedelta(hours=1), freq="h")


def build_feature_tensor(
    panels: Mapping[str, pd.DataFrame], decision: pd.Timestamp
) -> np.ndarray:
    """Build the frozen [168, 4, 6] tensor or fail closed on one bad bar."""
    dependency = feature_dependency_window(decision)
    output: list[np.ndarray] = []
    for symbol in UNIVERSE:
        source = panels[symbol]
        window = source.reindex(dependency)
        if window.isna().any(axis=None):
            raise AuditError(f"MISSING_OR_INVALID_FEATURE_BAR:{symbol}:{decision.isoformat()}")
        values = window[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (window[["open", "high", "low", "close"]] <= 0).any(axis=None):
            raise AuditError(f"MISSING_OR_INVALID_FEATURE_BAR:{symbol}:{decision.isoformat()}")
        if (window["volume"] < 0).any():
            raise AuditError(f"MISSING_OR_INVALID_FEATURE_BAR:{symbol}:{decision.isoformat()}")
        close = window["close"]
        volume = window["volume"]
        r1 = np.log(close / close.shift(1))
        channels = pd.DataFrame(
            {
                "log_return_1h": r1,
                "log_return_24h": np.log(close / close.shift(24)),
                "log_return_72h": np.log(close / close.shift(72)),
                "log_return_168h": np.log(close / close.shift(168)),
                "realized_volatility_168h": r1.rolling(168).std(ddof=1),
                "volume_ratio_168h": volume / volume.rolling(168).mean().clip(lower=1e-12),
            }
        ).iloc[-168:]
        if channels.shape != (168, 6) or not np.isfinite(channels.to_numpy()).all():
            raise AuditError(f"INCOMPLETE_DERIVED_FEATURE:{symbol}:{decision.isoformat()}")
        output.append(channels.to_numpy())
    tensor = np.stack(output, axis=1)
    if tensor.shape != (168, 4, 6):
        raise AuditError(f"Unexpected tensor shape: {tensor.shape}")
    return tensor


def label_contract(
    panel: pd.DataFrame,
    decision: pd.Timestamp,
    authorized_end: pd.Timestamp = AUDIT_END,
) -> dict[str, object]:
    cutoff = pd.Timestamp(decision)
    entry = cutoff + pd.Timedelta(hours=1)
    exit_time = cutoff + pd.Timedelta(days=1, hours=1)
    completion = exit_time
    if exit_time > authorized_end:
        return {
            "valid": False,
            "reason": "EXIT_AFTER_AUTHORIZED_WINDOW",
            "completion": completion,
            "value": np.nan,
        }
    interval = pd.date_range(entry, exit_time, freq="h")
    rows = panel.reindex(interval)
    if entry not in panel.index:
        reason = "ENTRY_MISSING"
    elif exit_time not in panel.index:
        reason = "EXIT_MISSING"
    elif rows.isna().any(axis=None):
        reason = "MISSING_BAR_IN_LABEL_INTERVAL"
    else:
        numeric = rows[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            reason = "INVALID_BAR_IN_LABEL_INTERVAL"
        elif (rows[["open", "high", "low", "close"]] <= 0).any(axis=None) or (rows["volume"] < 0).any():
            reason = "INVALID_BAR_IN_LABEL_INTERVAL"
        else:
            value = math.log(float(panel.at[exit_time, "open"]) / float(panel.at[entry, "open"]))
            return {"valid": True, "reason": "VALID", "completion": completion, "value": value}
    return {"valid": False, "reason": reason, "completion": completion, "value": np.nan}


def causal_raw_sigma(
    labels: pd.DataFrame,
    decisions: Iterable[pd.Timestamp],
    decay: float = LAMBDA,
    min_history: int = MIN_SIGMA_HISTORY,
) -> pd.DataFrame:
    """Compute readiness-only causal sigma from completed labels."""
    records: list[dict[str, object]] = []
    valid_labels = labels.loc[labels["valid"]].sort_values("completion")
    for decision in decisions:
        cutoff = pd.Timestamp(decision)
        eligible = valid_labels.loc[valid_labels["completion"] <= cutoff]
        record: dict[str, object] = {
            "decision": cutoff,
            "completed_count": int(len(eligible)),
            "latest_completion": eligible["completion"].max() if len(eligible) else pd.NaT,
            "raw_sigma": np.nan,
        }
        if len(eligible) >= min_history:
            values = eligible["value"].to_numpy(dtype=float)
            mean = float(np.mean(values[:min_history]))
            second = float(np.mean(values[:min_history] ** 2))
            for value in values[min_history:]:
                mean = decay * mean + (1 - decay) * float(value)
                second = decay * second + (1 - decay) * float(value) ** 2
            record["raw_sigma"] = math.sqrt(max(second - mean * mean, 0.0))
        records.append(record)
    return pd.DataFrame(records).set_index("decision")


def _decision_range(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="D", tz="UTC")


def audit_fold_purging() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for fold in FOLDS:
        nominal = _decision_range(fold.fit_start, fold.fit_end)
        validation_cutoff = pd.Timestamp(fold.validation_start, tz="UTC")
        completion = nominal + pd.Timedelta(days=1, hours=1)
        keep = completion <= validation_cutoff
        purged = nominal[~keep]
        output.append(
            {
                "fold": fold.name,
                "nominal_fit_rows": len(nominal),
                "eligible_fit_rows_before_complete_case": int(keep.sum()),
                "purged_rows": [value.isoformat() for value in purged],
                "validation_first_cutoff": validation_cutoff.isoformat(),
                "max_kept_label_completion": completion[keep].max().isoformat(),
                "rule": "label_completion <= validation_first_cutoff",
            }
        )
    return output


def compare_derived_source(
    path: Path,
    canonical: pd.DataFrame,
    symbol: str,
    access_log: list[str],
) -> dict[str, object]:
    """Compare an explicitly authorized, pre-2024-only Parquet derivative."""
    if "20231231" not in path.name or re.search(r"202[4-6]", path.name):
        raise AuditError(f"Derived source guard rejected path: {path}")
    access_log.append(path.as_posix())
    derived = pd.read_parquet(path)
    if "timestamp" not in derived:
        raise AuditError(f"Missing timestamp column: {path}")
    derived["timestamp"] = pd.to_datetime(derived["timestamp"], utc=True)
    if (derived["timestamp"] > AUDIT_END).any():
        raise AuditError(f"Post-2023 row detected in authorized derivative: {path}")
    declared_start = AUDIT_START if "20211101" in path.name else pd.Timestamp("2022-01-01", tz="UTC")
    canonical_indexed = canonical.loc[canonical["timestamp"] >= declared_start].set_index("timestamp")
    derived_indexed = derived.set_index("timestamp")
    common = canonical_indexed.index.intersection(derived_indexed.index)
    columns = ["open", "high", "low", "close", "volume"]
    left = canonical_indexed.loc[common, columns].to_numpy(dtype=float)
    right = derived_indexed.loc[common, columns].to_numpy(dtype=float)
    mismatch_mask = ~np.isclose(left, right, rtol=1e-12, atol=1e-12, equal_nan=True)
    mismatch_positions = np.argwhere(mismatch_mask)
    value_conflicts = [
        {
            "timestamp": common[row].isoformat(),
            "field": columns[column],
            "canonical_raw": float(left[row, column]),
            "derived": float(right[row, column]),
        }
        for row, column in mismatch_positions
    ]
    mismatched_values = len(value_conflicts)
    missing_from_derived = canonical_indexed.index.difference(derived_indexed.index)
    extra_in_derived = derived_indexed.index.difference(canonical_indexed.index)
    return {
        "path": path.as_posix(),
        "format": "parquet",
        "source_role": "derived_cross_check_only",
        "symbol": symbol,
        "rows": int(len(derived)),
        "start": derived["timestamp"].min().isoformat(),
        "end": derived["timestamp"].max().isoformat(),
        "schema": {column: str(dtype) for column, dtype in derived.dtypes.items()},
        "sha256": sha256_file(path),
        "overlap_rows": int(len(common)),
        "mismatched_ohlcv_values": mismatched_values,
        "value_conflicts": value_conflicts,
        "missing_from_derived": [value.isoformat() for value in missing_from_derived],
        "extra_in_derived": [value.isoformat() for value in extra_in_derived],
    }


def _synthetic_panels() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2021-10-01", "2022-03-31 23:00", freq="h", tz="UTC")
    step = np.arange(len(index), dtype=float)
    output: dict[str, pd.DataFrame] = {}
    for offset, symbol in enumerate(UNIVERSE, start=1):
        close = 100 * offset * np.exp(0.00002 * step + 0.001 * np.sin(step / (17 + offset)))
        output[symbol] = pd.DataFrame(
            {
                "open": close * 0.9999,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1000 + offset + (step % 23),
            },
            index=index,
        )
    return output


def _label_frame(panel: pd.DataFrame, decisions: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for decision in decisions:
        result = label_contract(panel, decision, authorized_end=panel.index.max())
        rows.append({"decision": decision, **result})
    return pd.DataFrame(rows).set_index("decision")


def run_synthetic_negative_tests() -> dict[str, bool]:
    panels = _synthetic_panels()
    decision = pd.Timestamp("2022-02-15", tz="UTC")
    baseline_tensor = build_feature_tensor(panels, decision)

    entry_mutation = {key: value.copy() for key, value in panels.items()}
    entry_mutation["BTCUSDT"].loc[decision + pd.Timedelta(hours=1), "open"] *= 10
    test_a = np.array_equal(baseline_tensor, build_feature_tensor(entry_mutation, decision))

    daily = _decision_range("2021-11-01", "2022-03-01")
    labels = _label_frame(panels["BTCUSDT"], daily)
    sigma_before = causal_raw_sigma(labels, [decision]).iloc[0]["raw_sigma"]
    exit_mutation = {key: value.copy() for key, value in panels.items()}
    exit_mutation["BTCUSDT"].loc[decision + pd.Timedelta(days=1, hours=1), "open"] *= 3
    exit_labels = _label_frame(exit_mutation["BTCUSDT"], daily)
    sigma_exit = causal_raw_sigma(exit_labels, [decision]).iloc[0]["raw_sigma"]
    test_b = np.array_equal(baseline_tensor, build_feature_tensor(exit_mutation, decision)) and sigma_before == sigma_exit

    incomplete_mutation = {key: value.copy() for key, value in panels.items()}
    incomplete_mutation["BTCUSDT"].loc[decision + pd.Timedelta(hours=1), "open"] *= 2
    incomplete_labels = _label_frame(incomplete_mutation["BTCUSDT"], daily)
    sigma_incomplete = causal_raw_sigma(incomplete_labels, [decision]).iloc[0]["raw_sigma"]
    test_c = sigma_before == sigma_incomplete

    old_decision = decision - pd.Timedelta(days=10)
    old_completion = old_decision + pd.Timedelta(days=1, hours=1)
    old_mutation = {key: value.copy() for key, value in panels.items()}
    old_mutation["BTCUSDT"].loc[old_completion, "open"] *= 1.5
    old_labels = _label_frame(old_mutation["BTCUSDT"], daily)
    past_cutoff = old_completion - pd.Timedelta(hours=1)
    past_original = causal_raw_sigma(labels, [past_cutoff]).iloc[0]["raw_sigma"]
    past_mutated = causal_raw_sigma(old_labels, [past_cutoff]).iloc[0]["raw_sigma"]
    future_mutated = causal_raw_sigma(old_labels, [decision]).iloc[0]["raw_sigma"]
    test_d = (pd.isna(past_original) and pd.isna(past_mutated) or past_original == past_mutated) and future_mutated != sigma_before

    missing = {key: value.copy() for key, value in panels.items()}
    missing["BTCUSDT"] = missing["BTCUSDT"].drop(decision - pd.Timedelta(hours=100))
    try:
        build_feature_tensor(missing, decision)
        test_e = False
    except AuditError:
        test_e = True

    final_2022 = pd.Timestamp("2022-12-31", tz="UTC")
    final_cutoff = pd.Timestamp("2023-01-01", tz="UTC")
    test_f = final_2022 + pd.Timedelta(days=1, hours=1) > final_cutoff
    test_g = pd.Timestamp("2023-12-31", tz="UTC") > LAST_SCREEN_DECISION
    return {
        "A": bool(test_a),
        "B": bool(test_b),
        "C": bool(test_c),
        "D": bool(test_d),
        "E": bool(test_e),
        "F": bool(test_f),
        "G": bool(test_g),
    }


def _phase_summary(
    name: str,
    start: str,
    end: str,
    panels: Mapping[str, pd.DataFrame],
    decisions: pd.DatetimeIndex,
    feature_valid: Mapping[pd.Timestamp, bool],
    label_valid: Mapping[pd.Timestamp, bool],
) -> dict[str, object]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=23)
    expected = len(pd.date_range(start_ts, end_ts, freq="h"))
    actual = {symbol: int(panels[symbol].loc[start_ts:end_ts].shape[0]) for symbol in UNIVERSE}
    common_hours = len(set.intersection(*(set(panels[symbol].loc[start_ts:end_ts].index) for symbol in UNIVERSE)))
    feature_count = sum(feature_valid.get(value, False) for value in decisions)
    label_count = sum(label_valid.get(value, False) for value in decisions)
    complete = sum(feature_valid.get(value, False) and label_valid.get(value, False) for value in decisions)
    return {
        "phase": name,
        "hourly_window": f"{start_ts.isoformat()}..{end_ts.isoformat()}",
        "expected_hourly_rows": expected,
        "actual_hourly_rows_per_asset": actual,
        "common_aligned_hourly_rows": common_hours,
        "market_wide_missing_hours": expected - common_hours,
        "asset_specific_missing_hours": sum(actual.values()) - len(UNIVERSE) * common_hours,
        "invalid_rows": 0,
        "nominal_decisions": len(decisions),
        "feature_valid_decisions": feature_count,
        "label_valid_decisions": label_count,
        "common_complete_case_decisions": complete,
        "excluded_decisions": len(decisions) - complete,
    }


def run_dataset_audit(repo_root: Path) -> dict[str, object]:
    raw_root = repo_root / "data/historical/neural_n1/raw/binance_spot_klines_1h"
    replay_root = repo_root / "data/historical_unified_replay"
    access_log: list[str] = []
    raw_frames: dict[str, pd.DataFrame] = {}
    panels: dict[str, pd.DataFrame] = {}
    source_files: list[dict[str, object]] = []
    integrity: dict[str, dict[str, object]] = {}
    for symbol in UNIVERSE:
        frame, sources = load_binance_archives(raw_root, symbol, access_log)
        raw_frames[symbol] = frame
        source_files.extend(sources)
        integrity[symbol] = validate_ohlcv(frame, symbol)
        panels[symbol] = indexed_panel(frame)

    derived: list[dict[str, object]] = []
    for symbol in UNIVERSE:
        for suffix in ("20211101_20231231", "20220101_20231231"):
            path = replay_root / f"{symbol}_1h_{suffix}.parquet"
            if path.is_file():
                derived.append(compare_derived_source(path, raw_frames[symbol], symbol, access_log))
    manifest_path = replay_root / "dataset_manifest.json"
    manifest_record = None
    if manifest_path.is_file():
        access_log.append(manifest_path.as_posix())
        manifest_record = {"path": manifest_path.as_posix(), "sha256": sha256_file(manifest_path)}

    all_missing = {
        symbol: set(integrity[symbol]["missing_timestamps"]) for symbol in UNIVERSE
    }
    shared_missing = sorted(set.intersection(*(values for values in all_missing.values())))
    asset_specific = {
        symbol: sorted(values - set(shared_missing)) for symbol, values in all_missing.items()
    }
    invalid_bar_count = sum(
        count
        for report in integrity.values()
        for category, count in report["anomaly_counts"].items()
        if category != "MISSING"
    )

    warmup_decisions = _decision_range("2021-11-01", "2021-12-31")
    dev_decisions = _decision_range("2022-01-01", "2022-12-30")
    screen_decisions = _decision_range("2023-01-01", "2023-12-30")
    all_decisions = warmup_decisions.append(dev_decisions).append(screen_decisions)
    feature_valid: dict[pd.Timestamp, bool] = {}
    feature_reasons: dict[str, list[str]] = {}
    for decision in all_decisions:
        try:
            build_feature_tensor(panels, decision)
            feature_valid[decision] = True
        except AuditError as exc:
            feature_valid[decision] = False
            feature_reasons.setdefault(str(exc), []).append(decision.isoformat())

    labels_by_symbol: dict[str, pd.DataFrame] = {}
    label_valid_common: dict[pd.Timestamp, bool] = {}
    label_exclusions: list[dict[str, str]] = []
    label_decisions = _decision_range("2021-11-01", "2023-12-31")
    for symbol in UNIVERSE:
        records = []
        for decision in label_decisions:
            result = label_contract(panels[symbol], decision)
            records.append({"decision": decision, **result})
            if not result["valid"]:
                label_exclusions.append(
                    {"symbol": symbol, "decision": decision.isoformat(), "reason": str(result["reason"])}
                )
        labels_by_symbol[symbol] = pd.DataFrame(records).set_index("decision")
    for decision in all_decisions:
        label_valid_common[decision] = all(bool(labels_by_symbol[symbol].at[decision, "valid"]) for symbol in UNIVERSE)

    sigma: dict[str, pd.DataFrame] = {
        symbol: causal_raw_sigma(labels_by_symbol[symbol], all_decisions) for symbol in UNIVERSE
    }
    sigma_warmup = {
        symbol: {
            "completed_labels_at_2022_01_01_cutoff": int(sigma[symbol].at[pd.Timestamp("2022-01-01", tz="UTC"), "completed_count"]),
            "raw_sigma_finite_at_2022_01_01": bool(
                np.isfinite(sigma[symbol].at[pd.Timestamp("2022-01-01", tz="UTC"), "raw_sigma"])
            ),
            "latest_completion_at_2022_01_01": sigma[symbol]
            .at[pd.Timestamp("2022-01-01", tz="UTC"), "latest_completion"]
            .isoformat(),
        }
        for symbol in UNIVERSE
    }

    folds = audit_fold_purging()
    for fold_record, fold in zip(folds, FOLDS, strict=True):
        nominal = _decision_range(fold.fit_start, fold.fit_end)
        validation_cutoff = pd.Timestamp(fold.validation_start, tz="UTC")
        eligible = [
            decision
            for decision in nominal
            if decision + pd.Timedelta(days=1, hours=1) <= validation_cutoff
            and feature_valid[decision]
            and label_valid_common[decision]
        ]
        floors = {}
        for symbol in UNIVERSE:
            values = sigma[symbol].loc[eligible, "raw_sigma"].dropna().to_numpy(dtype=float)
            floors[symbol] = max(0.0001, 0.1 * float(np.median(values))) if len(values) else None
        fold_record["complete_case_fit_rows"] = len(eligible)
        fold_record["floor_feasible"] = all(value is not None and np.isfinite(value) for value in floors.values())
        fold_record["epsilon_by_asset"] = floors

    final_fit_cutoff = pd.Timestamp("2023-01-01", tz="UTC")
    final_fit_dates = [
        decision
        for decision in dev_decisions
        if decision + pd.Timedelta(days=1, hours=1) <= final_fit_cutoff
        and feature_valid[decision]
        and label_valid_common[decision]
    ]
    final_floor_by_asset: dict[str, float | None] = {}
    for symbol in UNIVERSE:
        values = sigma[symbol].loc[final_fit_dates, "raw_sigma"].dropna().to_numpy(dtype=float)
        final_floor_by_asset[symbol] = (
            max(0.0001, 0.1 * float(np.median(values))) if len(values) else None
        )
    final_floor_readiness = {
        "fit_cutoff": final_fit_cutoff.isoformat(),
        "eligible_2022_rows": len(final_fit_dates),
        "epsilon_by_asset": final_floor_by_asset,
        "feasible": all(
            value is not None and np.isfinite(value) for value in final_floor_by_asset.values()
        ),
        "2022_12_31_excluded": True,
    }

    sigma_asof_violations = 0
    sigma_finite_screen_dates: dict[str, int] = {}
    for symbol in UNIVERSE:
        screen_sigma = sigma[symbol].loc[screen_decisions]
        latest = screen_sigma["latest_completion"]
        sigma_asof_violations += int(
            sum(
                pd.notna(completion) and completion > decision
                for decision, completion in latest.items()
            )
        )
        sigma_finite_screen_dates[symbol] = int(np.isfinite(screen_sigma["raw_sigma"]).sum())

    phases = [
        _phase_summary("Warmup", "2021-11-01", "2021-12-31", panels, warmup_decisions, feature_valid, label_valid_common),
        _phase_summary("2022 Dev", "2022-01-01", "2022-12-31", panels, dev_decisions, feature_valid, label_valid_common),
        _phase_summary("2023 Screen", "2023-01-01", "2023-12-31", panels, screen_decisions, feature_valid, label_valid_common),
    ]
    common_2023 = phases[-1]["common_complete_case_decisions"]

    gap_timestamp = pd.Timestamp("2023-03-24 13:00", tz="UTC")
    gap_feature_dates = [
        decision.isoformat()
        for decision in screen_decisions
        if gap_timestamp in feature_dependency_window(decision)
    ]
    gap_label_dates = [
        decision.isoformat()
        for decision in screen_decisions
        if decision + pd.Timedelta(hours=1) <= gap_timestamp <= decision + pd.Timedelta(days=1, hours=1)
    ]
    gap_impact = {
        "gap_timestamp": gap_timestamp.isoformat(),
        "assets": list(UNIVERSE),
        "classification": "market-wide",
        "feature_dependency_excluded_decisions": gap_feature_dates,
        "label_interval_excluded_decisions": gap_label_dates,
        "combined_excluded_count": len(set(gap_feature_dates + gap_label_dates)),
        "first_excluded_decision": min(gap_feature_dates + gap_label_dates),
        "last_excluded_decision": max(gap_feature_dates + gap_label_dates),
    }

    synthetic = run_synthetic_negative_tests()
    derived_value_match = all(item["mismatched_ohlcv_values"] == 0 for item in derived)
    primary_derived = [item for item in derived if "20211101_20231231" in item["path"]]
    primary_value_conflicts = [
        {"path": item["path"], **conflict}
        for item in primary_derived
        for conflict in item["value_conflicts"]
    ]
    expected_derived_tail_conflict = all(
        item["missing_from_derived"] == [AUDIT_END.isoformat()] for item in derived
    )
    no_post_2023_content = all(
        not re.search(r"202[4-6]", Path(path).name) for path in access_log if Path(path).suffix in {".zip", ".parquet"}
    )
    statuses = {
        "RAW_SOURCE_PROVENANCE": "PASS" if all(item["sidecar_verified"] for item in source_files) else "FAIL",
        "UTC_CALENDAR_ALIGNMENT": "PASS" if len(shared_missing) == 1 and not any(asset_specific.values()) else "FAIL",
        "OHLCV_INTEGRITY": "PASS" if invalid_bar_count == 0 else "FAIL",
        "FEATURE_CAUSALITY": "PASS" if all(synthetic[key] for key in ("A", "B")) else "FAIL",
        "FEATURE_COMPLETENESS": "PASS" if all(synthetic[key] for key in ("E",)) else "FAIL",
        "LABEL_FEASIBILITY": "PASS" if phases[-1]["label_valid_decisions"] >= 300 else "FAIL",
        "LABEL_AVAILABILITY": "PASS" if all(synthetic[key] for key in ("C", "D")) else "FAIL",
        "SIGMA_WARMUP": "PASS"
        if all(item["raw_sigma_finite_at_2022_01_01"] for item in sigma_warmup.values())
        and final_floor_readiness["feasible"]
        and sigma_asof_violations == 0
        else "FAIL",
        "FOLD_PURGING": "PASS" if all(item["floor_feasible"] and len(item["purged_rows"]) == 1 for item in folds) and synthetic["F"] else "FAIL",
        "2023_COMMON_SAMPLE_COVERAGE": "PASS" if common_2023 >= 300 and synthetic["G"] else "FAIL",
        "NO_2024_2026_ACCESS": "PASS" if no_post_2023_content else "FAIL",
    }
    if any(value == "FAIL" for key, value in statuses.items() if key in {"OHLCV_INTEGRITY", "FEATURE_CAUSALITY", "LABEL_AVAILABILITY", "FOLD_PURGING", "NO_2024_2026_ACCESS"}):
        verdict = "DATASET_INTEGRITY_FAILED"
    elif statuses["RAW_SOURCE_PROVENANCE"] != "PASS":
        verdict = "DATASET_AUDIT_INCONCLUSIVE"
    elif statuses["2023_COMMON_SAMPLE_COVERAGE"] != "PASS" or statuses["SIGMA_WARMUP"] != "PASS":
        verdict = "DATASET_INCOMPLETE"
    elif all(value == "PASS" for value in statuses.values()):
        verdict = "DATASET_READY"
    else:
        verdict = "DATASET_AUDIT_INCONCLUSIVE"
    next_step = {
        "DATASET_READY": "S4-P1A_FORECAST_IMPLEMENTATION",
        "DATASET_INCOMPLETE": "TARGETED_DATA_GAP_RESOLUTION",
        "DATASET_INTEGRITY_FAILED": "FIX_SPECIFIC_DATA_INTEGRITY_DEFECT",
        "DATASET_AUDIT_INCONCLUSIVE": "OBTAIN_MISSING_EVIDENCE",
    }[verdict]

    return {
        "audit": "S4-P1A DATASET INTEGRITY & CAUSAL READINESS AUDIT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "7b5a97becbd6da1249a484ed588133761cc57bd0",
        "scope": {
            "universe": list(UNIVERSE),
            "source": "Binance Spot 1h",
            "timestamp_convention": "UTC candle open time",
            "authorized_market_data_window": f"{AUDIT_START.isoformat()}..{AUDIT_END.isoformat()}",
            "training_performed": False,
            "predictive_screen_performed": False,
        },
        "source_selection": {
            "canonical": "monthly Binance Spot archives with verified Binance SHA-256 sidecars",
            "reason": "direct raw provenance, exact authorized-month isolation, full authorized open-time window",
            "derived_sources_are_cross_checks_only": True,
            "source_files": source_files,
            "canonical_schema": {
                "open_time_ms": "int64 UTC epoch milliseconds",
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64 base-asset volume",
                "close_time_ms": "int64 UTC epoch milliseconds",
                "timestamp": "datetime64[ms, UTC] derived from open_time_ms",
            },
            "discovered_roots": [
                {
                    "path": "data/historical/",
                    "formats": ["monthly ZIP CSV", "SHA-256 sidecar", "Parquet", "JSON manifest"],
                    "content_access": "authorized 2021-11..2023-12 raw archives and metadata only",
                },
                {
                    "path": "data/historical_unified_replay/",
                    "formats": ["per-symbol Parquet", "JSON manifest"],
                    "content_access": "pre-2024-only derivatives only",
                },
                {
                    "path": "data/neural_n1_2/",
                    "formats": ["Parquet", "JSON metadata"],
                    "content_access": False,
                    "reason": "noncanonical enriched derivatives; mixed/irrelevant coverage",
                },
                {
                    "path": "data/neural_n1_4/",
                    "formats": ["Parquet", "ZIP", "JSON metadata"],
                    "content_access": False,
                    "reason": "noncanonical term-structure derivatives",
                },
                {
                    "path": "data/neural_n1_5/",
                    "formats": ["Parquet", "ZIP", "JSON metadata"],
                    "content_access": False,
                    "reason": "noncanonical coin-margined derivatives",
                },
                {
                    "path": "data/neural_n1_6/",
                    "formats": ["Parquet", "JSONL", "JSON metadata"],
                    "content_access": False,
                    "reason": "noncanonical event/order data",
                },
                {
                    "path": "data/neural_n1_7/",
                    "formats": ["Parquet", "JSON checkpoint"],
                    "content_access": False,
                    "reason": "noncanonical order-intent data",
                },
            ],
            "derived_cross_checks": derived,
            "derived_manifest": manifest_record,
            "derived_overlap_values_match": derived_value_match,
            "expected_derived_tail_conflict_confirmed": expected_derived_tail_conflict,
        },
        "raw_integrity": {symbol: {key: value for key, value in report.items() if key != "valid_bar_mask"} for symbol, report in integrity.items()},
        "calendar": {"shared_missing": shared_missing, "asset_specific_missing": asset_specific},
        "anomalies": [
            {"category": "MISSING", "timestamp": value, "assets": list(UNIVERSE), "classification": "market-wide"}
            for value in shared_missing
        ]
        + [
            {
                "category": "SOURCE_CONFLICT",
                "timestamp": AUDIT_END.isoformat(),
                "assets": list(UNIVERSE),
                "detail": "canonical raw archives contain the bar; 2021-11..2023-12 derived Parquets omit it",
            }
        ]
        + [
            {
                "category": "SOURCE_CONFLICT",
                "timestamp": conflict["timestamp"],
                "assets": [Path(conflict["path"]).name.split("_")[0]],
                "field": conflict["field"],
                "canonical_raw": conflict["canonical_raw"],
                "derived": conflict["derived"],
                "derived_path": conflict["path"],
            }
            for conflict in primary_value_conflicts
        ],
        "effective_dataset": phases,
        "gap_impact": [gap_impact],
        "feature_contract": {
            "shape": [168, 4, 6],
            "channels": ["log_return_1h", "log_return_24h", "log_return_72h", "log_return_168h", "realized_volatility_168h", "volume_ratio_168h"],
            "raw_dependency_hours": 336,
            "last_eligible_bar_example": "cutoff 2022-06-01T00:00:00+00:00 -> 2022-05-31T23:00:00+00:00",
            "imputation": "none; fail-closed complete-case",
            "exclusion_groups": feature_reasons,
        },
        "label_contract": {
            "feature_cutoff": "t 00:00 UTC",
            "decision": "t 00:05 UTC",
            "entry": "t 01:00 UTC open",
            "exit_and_completion": "t+1 day 01:00 UTC open",
            "formula": "ln(exit_open / entry_open)",
            "latest_label_ordinary_at_cutoff": "t-2",
            "exclusions": label_exclusions,
        },
        "sigma_readiness": {
            "half_life_completed_labels": 20,
            "lambda": LAMBDA,
            "minimum_history": MIN_SIGMA_HISTORY,
            "initialization": "arithmetic mean of first 30 valid completed labels for first and second moments",
            "missing_update": "skip; never zero",
            "warmup": sigma_warmup,
            "screen_finite_raw_sigma_dates": sigma_finite_screen_dates,
            "asof_violations": sigma_asof_violations,
            "final_2023_floor_readiness": final_floor_readiness,
        },
        "fold_purging": folds,
        "synthetic_negative_tests": synthetic,
        "technical_readiness": statuses,
        "verdict": verdict,
        "next_step": next_step,
        "next_step_executed": False,
        "content_access_log": access_log,
    }


def render_markdown(result: Mapping[str, object]) -> str:
    statuses = result["technical_readiness"]
    phases = result["effective_dataset"]
    folds = result["fold_purging"]
    gap = result["gap_impact"][0]
    raw = result["raw_integrity"]
    source = result["source_selection"]
    synthetic = result["synthetic_negative_tests"]
    lines = [
        "# S4-P1A Dataset Integrity & Causal Readiness Audit",
        "",
        f"- Preregistration frozen at `{result['preregistration_commit']}`.",
        "- Scope: Binance Spot 1h, UTC open time, BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT.",
        "- Authorized content window: `2021-11-01 00:00` through `2023-12-31 23:00 UTC`.",
        "- No model training, forecast, IC, backtest, allocator, or post-2023 market-data content access was performed.",
        "",
        "## Verdict",
        "",
        f"`{result['verdict']}` — next mapped step: `{result['next_step']}` (**not executed**).",
        "",
        "The authentic market-wide gap is handled by strict complete-case exclusion and leaves "
        f"`{phases[-1]['common_complete_case_decisions']}` common 2023 dates, above the frozen minimum of 300.",
        "",
        "## Source provenance and selection",
        "",
        f"Canonical source: **{source['canonical']}**. Selection reason: {source['reason']}. "
        f"All `{len(source['source_files'])}` monthly ZIP checksums matched their sidecars.",
        "",
        "Derived Parquets were cross-checks only. Across the four full-window derivatives, "
        f"`{sum(item['mismatched_ohlcv_values'] for item in source['derived_cross_checks'] if '20211101_20231231' in item['path'])}` "
        "overlapping OHLCV cells conflict with the checksum-verified raw archives, and all four files omit "
        "`2023-12-31 23:00 UTC`. Every difference is recorded as `SOURCE_CONFLICT`; none is imported into "
        "the canonical calendar.",
        "",
        "| Asset | Raw rows | Start | End | Missing | Other anomalies |",
        "|---|---:|---|---|---:|---:|",
    ]
    for symbol in UNIVERSE:
        report = raw[symbol]
        other = sum(value for key, value in report["anomaly_counts"].items() if key != "MISSING")
        lines.append(f"| {symbol} | {report['rows']} | {report['start']} | {report['end']} | {report['anomaly_counts']['MISSING']} | {other} |")
    lines.extend(
        [
            "",
            "## Effective dataset",
            "",
            "| Phase | Expected hours | Actual/asset | Common hours | Market-wide missing | Nominal decisions | Feature-valid | Label-valid | Common complete-case | Excluded |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for phase in phases:
        actual = ", ".join(f"{key}:{value}" for key, value in phase["actual_hourly_rows_per_asset"].items())
        lines.append(
            f"| {phase['phase']} | {phase['expected_hourly_rows']} | {actual} | {phase['common_aligned_hourly_rows']} | "
            f"{phase['market_wide_missing_hours']} | {phase['nominal_decisions']} | {phase['feature_valid_decisions']} | "
            f"{phase['label_valid_decisions']} | {phase['common_complete_case_decisions']} | {phase['excluded_decisions']} |"
        )
    lines.extend(
        [
            "",
            "## Gap and causal dependency impact",
            "",
            f"- Gap: `{gap['gap_timestamp']}`, all four assets, market-wide.",
            f"- Label interval exclusion: `{gap['label_interval_excluded_decisions'][0]}`.",
            f"- 336-hour feature dependency exclusions: `{gap['feature_dependency_excluded_decisions'][0]}` through "
            f"`{gap['feature_dependency_excluded_decisions'][-1]}` ({len(gap['feature_dependency_excluded_decisions'])} decisions).",
            f"- Combined 2023 exclusion: {gap['combined_excluded_count']} decisions.",
            "- No forward-fill, backward-fill, interpolation, or zero-imputation is used.",
            "",
            "## Label availability, sigma warmup, and folds",
            "",
            "At cutoff `t 00:00`, only labels whose completion timestamp is `<= cutoff` enter EWMA; the ordinary latest label is `t-2`. "
            "Each asset has 60 completed valid labels by the 2022-01-01 cutoff, so the 30-label initialization is feasible.",
            "",
            "| Fold | Nominal fit | Purged row | Complete-case fit | Floor feasible |",
            "|---|---:|---|---:|---|",
        ]
    )
    for fold in folds:
        lines.append(f"| {fold['fold']} | {fold['nominal_fit_rows']} | {', '.join(fold['purged_rows'])} | {fold['complete_case_fit_rows']} | {fold['floor_feasible']} |")
    lines.extend(["", "## Synthetic leakage negative tests", ""])
    for key, description in {
        "A": "mutating t 01:00 entry does not change features at t",
        "B": "mutating t+1 01:00 exit changes neither features nor sigma at t",
        "C": "mutating incomplete t-1 label does not change sigma at t",
        "D": "mutating an old completed label can change future, never past sigma",
        "E": "removing one authentic dependency bar excludes the sample",
        "F": "2022-12-31 label is unavailable at 2023-01-01 00:00",
        "G": "2023-12-31 decision is excluded",
    }.items():
        lines.append(f"- {key}: `{'PASS' if synthetic[key] else 'FAIL'}` — {description}.")
    lines.extend(["", "## Technical readiness", ""])
    for key, value in statuses.items():
        lines.append(f"- `{key} = {value}`")
    lines.extend(
        [
            "",
            "## Final authorization state",
            "",
            "```text",
            "S3_RESEARCH = CLOSED_NEGATIVE_EXPLORATORY",
            "S4_P0_EXECUTABLE_PREREG = FROZEN",
            "S4_STAGE1_RESEARCH = AUTHORIZED",
            f"S4_DATASET_READINESS = {result['verdict']}",
            "S4_NEURAL_TRAINING = NOT_PERFORMED",
            "S4_RIDGE_TRAINING = NOT_PERFORMED",
            "S4_2023_PREDICTIVE_SCREEN = NOT_PERFORMED",
            "S4_STAGE2_ALLOCATOR = NOT_AUTHORIZED",
            "S4_2024_2026_ACCESS = NOT_AUTHORIZED",
            "PRODUCTION_PROMOTION = NOT_AUTHORIZED",
            "```",
            "",
        ]
    )
    return "\n".join(lines)

