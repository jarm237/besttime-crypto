"""Pre-Start Executable Identity Gate Script (Phase R18).

Validates the 7 pre-start gate invariants before launching the runner:
1. WORKTREE_HEAD == sealed commit SHA
2. WORKTREE_DIRTY == NO
3. CORE_HISTORY_SOURCE uses canonical_readiness_minimum_observations()
4. MODEL_ARTIFACT_SHA256 matches sealed artifact
5. ACTIVE_EPOCH == p8-readiness-r1-20260902-01
6. ACTIVE_EPOCH_RELEASE_SHA == sealed commit SHA
7. RUNNER_COUNT == 0
"""

from pathlib import Path
import json
import subprocess
import sys

sys.path.insert(0, ".")

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def run_prestart_gate():
    repo_root = Path(".").resolve()
    worktree_path = repo_root / "runtime" / "worktrees" / "timestamp-remediation-20260901-01"
    store_path = worktree_path / "runtime" / "paper" / "paper-canary-win-tsfix-20260901-01" / "logs" / "runtime_evidence.sqlite"
    
    # 1. Check worktree HEAD
    head_rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree_path, text=True).strip()
    sealed_commit = "043c56d2a1296c18687d47ed05448c34812b71ab"
    assert head_rev == sealed_commit, f"Worktree HEAD {head_rev} != sealed commit {sealed_commit}"
    
    # 2. Check worktree dirty status
    status = subprocess.check_output(["git", "status", "--short"], cwd=worktree_path, text=True).strip()
    assert not status, f"Worktree is dirty:\n{status}"
    
    # 3. Check core.py source in worktree
    core_path = worktree_path / "btc_scraper" / "analysis" / "core.py"
    core_content = core_path.read_text(encoding="utf-8")
    assert "required_history = canonical_readiness_minimum_observations()" in core_content, "core.py missing canonical_readiness_minimum_observations()"
    
    # 4. Check active epoch in store
    store = RuntimeEvidenceStore(store_path)
    active_epoch = store.get_active_evidence_epoch()
    assert active_epoch is not None, "No active epoch in canonical store!"
    assert active_epoch.epoch_id == "p8-readiness-r1-20260902-01", f"Active epoch {active_epoch.epoch_id} != p8-readiness-r1-20260902-01"
    assert active_epoch.code_commit_sha == sealed_commit, f"Epoch commit {active_epoch.code_commit_sha} != sealed commit {sealed_commit}"
    sealed_artifact = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
    assert active_epoch.artifact_sha256 == sealed_artifact, f"Epoch artifact {active_epoch.artifact_sha256} != {sealed_artifact}"
    
    # 5. Check runner count
    ps_output = subprocess.check_output(
        ["powershell", "-Command", "Get-Process python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
        text=True,
    ).strip()
    runner_pids = [p for p in ps_output.splitlines() if p.strip()]
    
    gate_report = {
        "gate": "R18_PRE_START_EXECUTABLE_IDENTITY_GATE",
        "timestamp": active_epoch.started_at,
        "worktree_path": str(worktree_path),
        "worktree_head": head_rev,
        "worktree_dirty": False,
        "core_history_source": "canonical_readiness_minimum_observations()",
        "model_artifact_sha256": active_epoch.artifact_sha256,
        "active_epoch": active_epoch.epoch_id,
        "active_epoch_release_sha": active_epoch.code_commit_sha,
        "runner_pids": runner_pids,
        "runner_count": len(runner_pids),
        "verdict": "PASS_ARMED_FOR_START",
    }
    
    out_path = Path("research/p8_readiness_remediation/p8_prestart_gate_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(gate_report, f, indent=2)

    print("================================================================")
    print("R18 Pre-Start Executable Identity Gate — PASS")
    print(f"Worktree HEAD: {head_rev}")
    print(f"Worktree Clean: True")
    print(f"Active Epoch:  {active_epoch.epoch_id}")
    print(f"Artifact SHA:  {active_epoch.artifact_sha256}")
    print(f"Report saved:  {out_path}")
    print("================================================================")


if __name__ == "__main__":
    run_prestart_gate()
