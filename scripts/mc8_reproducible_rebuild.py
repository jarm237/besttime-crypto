#!/usr/bin/env python3
"""MC8-G — Deterministic Release Rebuild.

Verifies that the release bundle construction is fully reproducible:
1. Backs up the current manifest.
2. Re-runs the bundle assembly.
3. Computes the SHA256 of the rebuilt manifest and compares it to the backup.
4. Asserts that the canonical release identity is byte-identical.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MANIFEST_PATH = REPO_ROOT / "model_coverage_mc8_release_manifest.json"
REPORT_PATH   = REPO_ROOT / "model_coverage_mc8_reproducibility_report.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(content, encoding="utf-8")
    sha_path = Path(str(path) + ".sha256")
    rel = path.relative_to(REPO_ROOT)
    sha_path.write_text(f"{_sha256_text(content)}  {rel}\n", encoding="utf-8")


def main() -> None:
    print("MC8-G: Deterministic Release Rebuild …")

    if not MANIFEST_PATH.exists():
        print(f"Error: Manifest {MANIFEST_PATH} not found.")
        sys.exit(1)

    original_sha = _sha256_file(MANIFEST_PATH)
    original_content = MANIFEST_PATH.read_text(encoding="utf-8")

    # Re-run bundle assembly
    print("Re-assembling release bundle...")
    subprocess.check_call(
        [sys.executable, "scripts/mc8_assemble_bundle.py"],
        cwd=str(REPO_ROOT),
    )

    rebuilt_sha = _sha256_file(MANIFEST_PATH)
    rebuilt_content = MANIFEST_PATH.read_text(encoding="utf-8")

    gates = {}
    gates["MC8-G-G1"] = {
        "gate": "rebuild_completed",
        "result": "PASS"
    }
    gates["MC8-G-G2"] = {
        "gate": "manifest_sha_matches",
        "original_sha": original_sha,
        "rebuilt_sha": rebuilt_sha,
        "result": "PASS" if original_sha == rebuilt_sha else "FAIL"
    }
    gates["MC8-G-G3"] = {
        "gate": "manifest_content_identical",
        "result": "PASS" if original_content == rebuilt_content else "FAIL"
    }

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    report = {
        "artifact": "model_coverage_mc8_reproducibility_report",
        "gates": gates,
        "overall_verdict": overall,
    }
    _write_json(REPORT_PATH, report)

    for gk, gv in gates.items():
        print(f"  {gk} {gv['gate']:<45} {gv['result']}")
    print(f"  Overall: {overall}")


if __name__ == "__main__":
    main()
