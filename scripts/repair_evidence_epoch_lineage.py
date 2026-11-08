#!/usr/bin/env python3
"""
Governed Evidence Epoch Hash Repair Script.

Non-destructively recalculates and updates `release_manifest_sha256` for SQLite evidence epoch records
without altering release_manifest payloads, artifact_sha256, model_version, or historical epoch identities.

Usage:
    python scripts/repair_evidence_epoch_lineage.py --dry-run
    python scripts/repair_evidence_epoch_lineage.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch


def calculate_manifest_sha256(raw_manifest: str | dict) -> tuple[dict, str]:
    if isinstance(raw_manifest, str):
        manifest_dict = json.loads(raw_manifest)
    else:
        manifest_dict = dict(raw_manifest)

    canonical_json = json.dumps(
        manifest_dict,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    computed_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return manifest_dict, computed_hash


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def repair_sqlite_file(
    db_path: Path,
    apply: bool = False,
    include_snapshots: bool = False,
    backup_dir: Path | None = None,
) -> dict:
    if not include_snapshots and (".aborted-" in db_path.name or "aborted-" in str(db_path)):
        return {"scanned": 0, "repaired": 0, "skipped": 1, "errors": 0}

    stats = {"scanned": 0, "repaired": 0, "skipped": 0, "errors": 0}

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "evidence_epochs" not in tables:
            conn.close()
            return stats

        # Fetch columns from evidence_epochs
        cur.execute("PRAGMA table_info(evidence_epochs)")
        col_names = [col[1] for col in cur.fetchall()]

        cur.execute("SELECT * FROM evidence_epochs")
        rows = cur.fetchall()

        updates = []

        for row in rows:
            stats["scanned"] += 1
            row_dict = dict(zip(col_names, row))
            epoch_id = row_dict.get("epoch_id")
            raw_manifest = row_dict.get("release_manifest")
            current_hash = row_dict.get("release_manifest_sha256")

            # Parse JSON string fields from SQLite row
            if isinstance(raw_manifest, str) and raw_manifest.strip():
                try:
                    manifest_dict, expected_hash = calculate_manifest_sha256(raw_manifest)
                except Exception:
                    stats["errors"] += 1
                    continue
            elif isinstance(raw_manifest, dict):
                manifest_dict, expected_hash = calculate_manifest_sha256(raw_manifest)
            else:
                stats["skipped"] += 1
                continue

            if current_hash == expected_hash:
                stats["skipped"] += 1
                continue

            # Verify if setting expected_hash makes EvidenceEpoch valid
            candidate_payload = dict(row_dict)
            candidate_payload["release_manifest"] = manifest_dict
            candidate_payload["release_manifest_sha256"] = expected_hash
            
            raw_pause = candidate_payload.get("runtime_pause_policy")
            if isinstance(raw_pause, str) and raw_pause.strip():
                try:
                    candidate_payload["runtime_pause_policy"] = json.loads(raw_pause)
                except Exception:
                    pass

            raw_universe = candidate_payload.get("analysis_universe")
            if isinstance(raw_universe, str) and raw_universe.strip():
                if raw_universe.strip().startswith("[") or raw_universe.strip().startswith("("):
                    try:
                        candidate_payload["analysis_universe"] = tuple(json.loads(raw_universe))
                    except Exception:
                        candidate_payload["analysis_universe"] = tuple(
                            s.strip().strip('"').strip("'").strip("[").strip("]") for s in raw_universe.split(",") if s.strip()
                        )
                else:
                    candidate_payload["analysis_universe"] = tuple(
                        s.strip() for s in raw_universe.split(",") if s.strip()
                    )

            # Filter candidate_payload to dataclass fields
            from dataclasses import fields as dc_fields
            valid_field_names = {f.name for f in dc_fields(EvidenceEpoch)}
            candidate_payload = {k: v for k, v in candidate_payload.items() if k in valid_field_names}

            try:
                epoch_obj = EvidenceEpoch.from_mapping(candidate_payload)
                epoch_obj.validate()
            except Exception as val_err:
                print(f"  ⚠️ Epoch '{epoch_id}' in {display_path(db_path)} fails validation even with computed hash: {val_err}")
                stats["errors"] += 1
                continue

            updates.append((epoch_id, current_hash, expected_hash))

        if updates:
            print(f"[{'APPLY' if apply else 'DRY-RUN'}] {display_path(db_path)}: {len(updates)} epoch hash(es) to repair.")
            for epoch_id, old_h, new_h in updates:
                print(f"  - Epoch '{epoch_id}': old={old_h[:8] if old_h else 'None'} -> new={new_h[:8]}")

            if apply:
                # Perform atomic backup before mutation
                target_backup_dir = backup_dir if backup_dir is not None else (REPO_ROOT / "logs" / "backups")
                target_backup_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                backup_path = target_backup_dir / f"{db_path.stem}_{timestamp}.sqlite.bak"
                
                bconn = sqlite3.connect(backup_path)
                conn.backup(bconn)
                bconn.close()

                # Ensure audit table exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS epoch_repair_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        epoch_id TEXT NOT NULL,
                        old_hash TEXT,
                        new_hash TEXT NOT NULL,
                        database_path TEXT NOT NULL,
                        repaired_at TEXT NOT NULL
                    )
                """)

                now_iso = datetime.now(timezone.utc).isoformat()
                for epoch_id, old_h, new_h in updates:
                    cur.execute(
                        "UPDATE evidence_epochs SET release_manifest_sha256=? WHERE epoch_id=?",
                        (new_h, epoch_id),
                    )
                    cur.execute(
                        "INSERT INTO epoch_repair_audit (epoch_id, old_hash, new_hash, database_path, repaired_at) VALUES (?, ?, ?, ?, ?)",
                        (epoch_id, old_h or "", new_h, str(db_path), now_iso),
                    )

                conn.commit()
                stats["repaired"] += len(updates)

        conn.close()
    except Exception as exc:
        print(f"  ⚠️ Error inspecting/updating {db_path}: {exc}")
        stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Governed Evidence Epoch Hash Repair")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--dry-run", action="store_true", default=True, help="Scan and report without mutating (default)")
    group.add_argument("--apply", action="store_true", help="Perform atomic backup and apply hash updates")
    parser.add_argument("--include-snapshots", action="store_true", help="Include .aborted-* and snapshot databases")
    args = parser.parse_args()

    apply_changes = args.apply

    print(f"=== Governed Evidence Epoch Hash Repair (Mode: {'APPLY' if apply_changes else 'DRY-RUN'}) ===")
    
    # Target global_evidence_index.sqlite databases
    sqlite_files = list(REPO_ROOT.glob("**/global_evidence_index.sqlite"))

    total_scanned = 0
    total_repaired = 0
    total_errors = 0

    for db_path in sqlite_files:
        res = repair_sqlite_file(db_path, apply=apply_changes, include_snapshots=args.include_snapshots)
        total_scanned += res["scanned"]
        total_repaired += res["repaired"]
        total_errors += res["errors"]

    print(f"\n[REPAIR COMPLETE] Scanned {total_scanned} epoch(s). Repaired: {total_repaired}. Errors: {total_errors}.")
    if not apply_changes and total_scanned > 0:
        print("💡 Run with '--apply' to execute hash updates with automatic SQLite backup.")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
