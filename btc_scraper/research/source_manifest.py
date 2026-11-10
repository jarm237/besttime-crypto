"""
btc_scraper/research/source_manifest.py
Milestone M5 / Phase G4 (P0-1): Reproducible Source Identity & Candidate Semantic Manifest.

Provides:
1. Semantic dependency tracking for research candidates independent of uncommitted Git working tree.
2. Normalized SHA-256 hashing of all candidate source code files.
3. Fail-closed verification that candidate execution matches frozen source definitions.
4. Explicit seal status ("SOURCE_SEAL_PENDING" / "SOURCE_REVISION_NOT_SEALED") to preserve
   Boundary A (zero unauthorized commits) while establishing cryptographic provenance.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Canonical semantic dependency files required to deterministically run and verify the candidate
CANDIDATE_SEMANTIC_DEPENDENCY_FILES: Tuple[str, ...] = (
    "btc_scraper/research/baseline_runner.py",
    "btc_scraper/research/candidate_freeze.py",
    "btc_scraper/research/candle_aggregator.py",
    "btc_scraper/research/experiment_contract.py",
    "btc_scraper/research/feature_contract.py",
    "btc_scraper/research/feature_factory.py",
    "btc_scraper/research/prospective_shadow_evaluator.py",
    "btc_scraper/research/shadow_consumer.py",
    "btc_scraper/research/source_manifest.py",
    "btc_scraper/research/strategy_registry.py",
)


def compute_file_sha256(file_path: Path) -> str:
    """Computes SHA-256 of file with normalized newline encoding (\\n) for cross-platform reproducibility."""
    if not file_path.exists():
        raise FileNotFoundError(f"Dependency file not found: {file_path}")
    # Read text with universal newlines to make hash independent of CRLF vs LF checkout
    text = file_path.read_text(encoding="utf-8")
    normalized_bytes = text.replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(normalized_bytes).hexdigest()


def compute_source_manifest(
    repo_root: Optional[Path] = None,
    dependency_files: Optional[Sequence[str]] = None,
    git_head: str = "5fee4753a7ed25e21cee3f3d2648d11b51c9ab64",
    is_dirty: bool = True,
) -> Dict[str, Any]:
    """
    Computes a deterministic cryptographic source manifest of all semantic candidate dependencies.
    """
    if repo_root is None:
        # Defaults to repo root based on this file's location
        repo_root = Path(__file__).resolve().parent.parent.parent

    files_to_hash = dependency_files or CANDIDATE_SEMANTIC_DEPENDENCY_FILES
    file_hashes: Dict[str, str] = {}

    for rel_path in sorted(files_to_hash):
        full_path = repo_root / rel_path
        file_hashes[rel_path] = compute_file_sha256(full_path)

    # Compute aggregate manifest hash over sorted items
    canonical_payload = json.dumps(file_hashes, sort_keys=True, separators=(",", ":"))
    manifest_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    seal_status = "SOURCE_SEAL_PENDING" if is_dirty else "SOURCE_SEALED"

    return {
        "manifest_version": "1.0.0",
        "manifest_hash": manifest_hash,
        "git_base_commit": git_head,
        "is_working_tree_dirty": is_dirty,
        "seal_status": seal_status,
        "file_hashes": file_hashes,
        "dependency_count": len(file_hashes),
    }


def verify_source_manifest(
    expected_manifest: Mapping[str, Any],
    repo_root: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """
    Verifies that the current files match the expected manifest.
    Returns (is_valid, list_of_discrepancies).
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    discrepancies: List[str] = []
    expected_file_hashes = expected_manifest.get("file_hashes", {})

    for rel_path, expected_hash in expected_file_hashes.items():
        full_path = repo_root / rel_path
        if not full_path.exists():
            discrepancies.append(f"Missing file: {rel_path}")
            continue
        actual_hash = compute_file_sha256(full_path)
        if actual_hash != expected_hash:
            discrepancies.append(
                f"Hash mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
            )

    return len(discrepancies) == 0, discrepancies


def get_class_source_hash(class_path: str, repo_root: Optional[Path] = None) -> str:
    """Returns normalized SHA-256 of the source file containing the specified class."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    # Map dotted python class path to file path
    parts = class_path.split(".")
    module_rel_path = "/".join(parts[:-1]) + ".py"
    target_file = repo_root / module_rel_path
    if not target_file.exists():
        raise FileNotFoundError(f"Source file for {class_path} not found at {target_file}")
    return compute_file_sha256(target_file)
