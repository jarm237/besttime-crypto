#!/usr/bin/env python3
"""Backfill trade provenance for paper, manual and test-created records.

This script is intentionally additive: it annotates records with stable fields
instead of moving/deleting historical data.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from bson import ObjectId
from pymongo import UpdateOne

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.core.db import db

MONGO_COLLECTIONS = (
    "positions",
    "closed_positions",
    "closed_trades",
    "trades",
    "orders",
    "virtual_trades",
)

JSON_LOGS = (
    REPO_ROOT / "btc_scraper" / "logs" / "auto_trade_log.json",
    REPO_ROOT / "logs" / "adaptive_signals.json",
)

ORDER_CREATOR_SYSTEM = "system"
ORDER_CREATOR_USER = "user"
ORDER_CREATOR_TEST = "test"
ORDER_CHANNEL_PAPER_RUNNER = "paper_runner"
ORDER_CHANNEL_LIVE_RUNNER = "live_runner"
ORDER_CHANNEL_TELEGRAM = "telegram"
ORDER_CHANNEL_UI = "ui"
ORDER_CHANNEL_CLI = "cli"
ORDER_CHANNEL_MANUAL = "manual"
ORDER_CHANNEL_TEST = "test"
ORDER_CHANNEL_UNKNOWN = "unknown"


def _stringify(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return value


def _infer_order_channel(created_by: str | None) -> str:
    source = str(created_by or "").strip().lower()
    if "telegram" in source or source in {"tele", "tg"}:
        return ORDER_CHANNEL_TELEGRAM
    if "ui" in source or "web" in source or "dashboard" in source:
        return ORDER_CHANNEL_UI
    if "cli" in source or "manage_positions" in source:
        return ORDER_CHANNEL_CLI
    if "pytest" in source or "test" in source:
        return ORDER_CHANNEL_TEST
    if source:
        return ORDER_CHANNEL_MANUAL
    return ORDER_CHANNEL_UNKNOWN


def classify_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical provenance metadata for a trade-like record."""
    existing = record.get("trade_origin")
    if existing:
        origin = str(existing)
    else:
        note = str(record.get("note") or "")
        mode = str(record.get("mode") or record.get("execution_mode") or "").upper()
        status = str(record.get("status") or "").lower()
        fill_source = str(record.get("fill_source") or "")
        source = str(record.get("source") or "")
        reason = str(record.get("reason") or record.get("reason_skip") or "")

        combined = " ".join([note, mode, status, fill_source, source, reason]).upper()

        if (
            "PYTEST" in combined
            or "TEST_FUNCTION" in combined
            or "UNIT_TEST" in combined
            or record.get("source_test_name")
            or record.get("is_test_record") is True
        ):
            origin = "test_function"
        elif (
            "DRY_RUN" in combined
            or "PAPER" in combined
            or fill_source == "real_paper"
            or record.get("is_paper") is True
        ):
            origin = "paper_mode"
        elif "[MANUAL]" in combined or mode == "MANUAL" or record.get("is_manual") is True:
            origin = "manual"
        elif mode in {"LIVE", "TESTNET"} or fill_source == "live":
            origin = "live"
        else:
            origin = "manual"

    if origin == "paper_mode":
        execution_mode = record.get("execution_mode") or "paper"
        fill_source = record.get("fill_source") or "real_paper"
    elif origin == "test_function":
        execution_mode = record.get("execution_mode") or "test"
        fill_source = record.get("fill_source")
    elif origin == "live":
        execution_mode = record.get("execution_mode") or "live"
        fill_source = record.get("fill_source") or "live"
    else:
        execution_mode = record.get("execution_mode") or "manual"
        fill_source = record.get("fill_source")

    created_by = record.get("created_by")
    if not created_by:
        if origin == "paper_mode":
            created_by = "auto_trader"
        elif origin == "test_function":
            created_by = "pytest"
        elif origin == "live":
            created_by = "auto_trader"
        else:
            created_by = "manual"

    existing_creator = record.get("order_creator")
    existing_channel = record.get("order_channel")
    if existing_creator:
        order_creator = str(existing_creator).strip().lower()
    elif origin in {"paper_mode", "live"}:
        order_creator = ORDER_CREATOR_SYSTEM
    elif origin == "test_function":
        order_creator = ORDER_CREATOR_TEST
    else:
        order_creator = ORDER_CREATOR_USER

    if existing_channel:
        order_channel = str(existing_channel).strip().lower()
    elif origin == "paper_mode":
        order_channel = ORDER_CHANNEL_PAPER_RUNNER
    elif origin == "live":
        order_channel = ORDER_CHANNEL_LIVE_RUNNER
    elif origin == "test_function":
        order_channel = ORDER_CHANNEL_TEST
    else:
        order_channel = _infer_order_channel(created_by)

    # Historical manual records have no reliable structured indicator of why
    # they were created.  Do not infer this from free-text notes: leave them
    # explicitly unknown so they cannot be treated as signal-following data.
    manual_decision_basis = None
    if origin == "manual":
        manual_decision_basis = str(record.get("manual_decision_basis") or "unknown").lower()
        if manual_decision_basis not in {"system_signal", "personal_discretion", "unknown"}:
            manual_decision_basis = "unknown"

    return {
        "trade_origin": origin,
        "execution_mode": execution_mode,
        "fill_source": fill_source,
        "created_by": created_by,
        "order_creator": order_creator,
        "order_channel": order_channel,
        "is_paper": origin == "paper_mode",
        "is_manual": origin == "manual",
        "is_test_record": origin == "test_function",
        "is_system_order": order_creator == ORDER_CREATOR_SYSTEM,
        "is_user_order": order_creator == ORDER_CREATOR_USER,
        "is_system_paper_order": (
            order_creator == ORDER_CREATOR_SYSTEM
            and order_channel == ORDER_CHANNEL_PAPER_RUNNER
        ),
        "is_user_telegram_order": (
            order_creator == ORDER_CREATOR_USER
            and order_channel == ORDER_CHANNEL_TELEGRAM
        ),
        "is_user_ui_order": (
            order_creator == ORDER_CREATOR_USER
            and order_channel == ORDER_CHANNEL_UI
        ),
        "manual_decision_basis": manual_decision_basis,
        "is_system_signal_manual": manual_decision_basis == "system_signal",
    }


def backfill_mongo(apply: bool) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for name in MONGO_COLLECTIONS:
        col = db[name]
        scanned = 0
        changed = 0
        counts: Counter[str] = Counter()
        sample = []
        pending_updates = []
        for doc in col.find({}):
            scanned += 1
            metadata = classify_record(doc)
            counts[metadata["trade_origin"]] += 1
            needs_update = any(doc.get(k) != v for k, v in metadata.items())
            if needs_update:
                changed += 1
                if len(sample) < 5:
                    sample.append({"_id": str(doc.get("_id")), "metadata": metadata})
                if apply:
                    set_doc = dict(metadata)
                    if not doc.get("provenance_backfilled_at"):
                        set_doc["provenance_backfilled_at"] = datetime.now(timezone.utc).isoformat()
                    pending_updates.append(UpdateOne({"_id": doc["_id"]}, {"$set": set_doc}))
                    if len(pending_updates) >= 100:
                        col.bulk_write(pending_updates, ordered=False)
                        pending_updates = []
        if apply and pending_updates:
            col.bulk_write(pending_updates, ordered=False)
        summary[name] = {
            "scanned": scanned,
            "changed": changed,
            "origin_counts": dict(counts),
            "sample": sample,
        }
    return summary


def backfill_json_logs(apply: bool) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for path in JSON_LOGS:
        if not path.exists():
            summary[str(path.relative_to(REPO_ROOT))] = {"exists": False}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else [data]
        changed = 0
        counts: Counter[str] = Counter()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            metadata = classify_record(rec)
            counts[metadata["trade_origin"]] += 1
            if any(rec.get(k) != v for k, v in metadata.items()):
                changed += 1
                if apply:
                    rec.update(metadata)
                    rec.setdefault("provenance_backfilled_at", datetime.now(timezone.utc).isoformat())
        if apply and changed:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        summary[str(path.relative_to(REPO_ROOT))] = {
            "exists": True,
            "scanned": len(records),
            "changed": changed,
            "origin_counts": dict(counts),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write metadata updates. Default is dry-run.")
    parser.add_argument(
        "--report",
        default="data/cleanup/trade_provenance_backfill_report.json",
        help="Path for JSON summary report.",
    )
    args = parser.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "applied": bool(args.apply),
        "mongo": backfill_mongo(apply=args.apply),
        "json_logs": backfill_json_logs(apply=args.apply),
    }

    report_path = REPO_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(_stringify(report), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(_stringify(report), indent=2, ensure_ascii=False))
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
