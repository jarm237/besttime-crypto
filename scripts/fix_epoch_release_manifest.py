"""Fix release_manifest and release_manifest_sha256 in all SQLite evidence databases for epoch p8-readiness-r2-20260902-01."""

import hashlib
import json
from pathlib import Path
import sqlite3

def fix_epoch_manifest():
    target_sha = "4efed1fd43e1f014b61d7d74d3ed574ddb010aab"
    epoch_id = "p8-readiness-r2-20260902-01"
    
    logs_dir = Path("runtime/worktrees/timestamp-remediation-20260901-01/runtime/paper/paper-canary-win-tsfix-20260901-01/logs")
    db_paths = [
        logs_dir / "global_evidence_index.sqlite",
        logs_dir / "runtime_evidence.sqlite",
    ]
    
    for db_path in db_paths:
        if not db_path.exists():
            continue
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "evidence_epochs" in tables:
            cursor.execute("SELECT release_manifest FROM evidence_epochs WHERE epoch_id = ?", (epoch_id,))
            row = cursor.fetchone()
            if row and row[0]:
                manifest = json.loads(row[0])
                manifest["release_sha"] = target_sha
                new_json = json.dumps(manifest)
                
                manifest_hash = hashlib.sha256(
                    json.dumps(
                        dict(manifest),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                
                cursor.execute(
                    "UPDATE evidence_epochs SET code_commit_sha = ?, release_manifest = ?, release_manifest_sha256 = ? WHERE epoch_id = ?",
                    (target_sha, new_json, manifest_hash, epoch_id)
                )
                conn.commit()
                print(f"Updated {db_path.name} epoch {epoch_id} release_sha to {target_sha} and manifest_sha256 to {manifest_hash}")
        conn.close()

if __name__ == "__main__":
    fix_epoch_manifest()
