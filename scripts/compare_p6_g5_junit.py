#!/usr/bin/env python3
"""Compare a pytest JUnit file against the frozen P6-G5 failure baseline."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _nodeid(classname: str, name: str) -> str:
    if classname.startswith("tests."):
        return f"{classname.replace('.', '/')}.py::{name}"
    return f"{classname}::{name}"


def _failure_category(message: str, text: str) -> str:
    joined = f"{message}\n{text}"
    if "KeyError" in joined:
        return "KeyError"
    if "AssertionError" in joined:
        return "AssertionError"
    first = joined.strip().splitlines()[0] if joined.strip() else "UNKNOWN"
    return first.split(":", 1)[0]


def _normalize(value: str) -> str:
    value = re.sub(r"/tmp/[^\s:]+", "/tmp/<tmp>", value)
    value = re.sub(r"0x[0-9a-fA-F]+", "0x<addr>", value)
    return " ".join(value.split())


def _failures(path: Path) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    failures: list[dict[str, Any]] = []
    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        if failure is None:
            continue
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        message = failure.attrib.get("message", "")
        text = failure.text or ""
        normalized = _normalize(f"{message}\n{text}")
        failures.append({
            "nodeid": _nodeid(classname, name),
            "classname": classname,
            "name": name,
            "failure_category": _failure_category(message, text),
            "normalized_failure": normalized,
        })
    return failures


def compare(baseline_path: Path, junit_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    actual_failures = _failures(junit_path)
    actual_by_node = {item["nodeid"]: item for item in actual_failures}
    expected_by_node = {item["nodeid"]: item for item in baseline["failures"]}

    missing = sorted(set(expected_by_node) - set(actual_by_node))
    unexpected = sorted(set(actual_by_node) - set(expected_by_node))
    signature_mismatches = []
    for nodeid, expected in expected_by_node.items():
        actual = actual_by_node.get(nodeid)
        if actual is None:
            continue
        if actual["failure_category"] != expected["failure_category"]:
            signature_mismatches.append({
                "nodeid": nodeid,
                "expected_category": expected["failure_category"],
                "actual_category": actual["failure_category"],
            })
            continue
        signature = str(expected["stable_signature"])
        haystack = actual["normalized_failure"]
        if all(part not in haystack for part in signature.split()):
            signature_mismatches.append({
                "nodeid": nodeid,
                "expected_signature": signature,
                "actual_excerpt": haystack[:240],
            })

    result = {
        "contract": "p6-g5-regression-comparison/v1",
        "baseline": str(baseline_path),
        "junit": str(junit_path),
        "junit_sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
        "expected_failure_count": int(baseline["expected_failure_count"]),
        "actual_failure_count": len(actual_failures),
        "missing_baseline_failures": missing,
        "unexpected_failures": unexpected,
        "signature_mismatches": signature_mismatches,
    }
    result["status"] = (
        "PASS"
        if (
            result["actual_failure_count"] == result["expected_failure_count"]
            and not missing
            and not unexpected
            and not signature_mismatches
        )
        else "FAIL"
    )
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: scripts/compare_p6_g5_junit.py <baseline.json> <pytest-junit.xml>",
            file=sys.stderr,
        )
        return 2
    result = compare(Path(argv[1]), Path(argv[2]))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
