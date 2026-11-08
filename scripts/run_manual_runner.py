"""Script chạy Runner liên tục ở chế độ Thủ công (Foreground Manual Runner).

Chế độ:
1. --governed (Khuyên dùng cho P8 Evidence):
   - Tự động chuyển giao thực thi cho P8 Sealed Worktree (4efed1f)
   - Preflight kiểm tra read-only SQLite: Sealed commit, Clean worktree, Active Epoch, Artifact SHA
   - BTC_EVIDENCE_ELIGIBLE = true
   - BTC_DISABLE_RUNTIME_LOCK = 0 (bắt buộc runtime lock)
2. --governed --preflight-only:
   - Chỉ kiểm tra điều kiện preflight rồi thoát ngay (exit 0 nếu pass, 1 nếu fail)
   - Không chiếm runtime lock, không mở WebSocket/collector, không ghi evidence
3. --diagnostic (Mặc định khi debug lỗi runtime tại dev workspace):
   - BTC_EVIDENCE_ELIGIBLE = false
   - BTC_DISABLE_RUNTIME_LOCK = 1
   - Gắn nhãn DIAGNOSTIC_NON_ELIGIBLE
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

# Đảm bảo đường dẫn gốc thư mục được thêm vào sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from btc_scraper.ml_engine.p8_governance import (
    EXPECTED_DEPLOYMENT_ID,
    EXPECTED_EPOCH_ID,
    EXPECTED_PAPER_RUN_ID,
    EXPECTED_UNIVERSE_HASH,
    SEALED_ARTIFACT_SHA,
    SEALED_COMMIT_SHA,
    SEALED_WORKTREE_PATH,
    GovernanceError,
    P8AttestationPolicy,
)


def _is_pid_alive(pid: int) -> bool:
    """Check if process ID is alive on Windows/POSIX without signaling."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _inspect_worktree_cleanliness(worktree_path: Path) -> dict[str, list[str]]:
    """Return content changes that make a sealed worktree non-clean.

    ``git diff --quiet`` is content-aware, so timestamp/stat-cache drift does
    not create a false positive. Untracked files are checked separately
    because ``git diff HEAD`` deliberately omits them.
    """
    try:
        diff = subprocess.run(
            ["git", "-C", str(worktree_path), "diff", "--quiet", "HEAD", "--"],
            capture_output=True,
            text=True,
            check=False,
        )
        if diff.returncode not in {0, 1}:
            detail = (diff.stderr or diff.stdout).strip()
            raise RuntimeError(f"git diff failed with exit {diff.returncode}: {detail}")

        tracked_changes: list[str] = []
        if diff.returncode == 1:
            tracked_changes = subprocess.check_output(
                ["git", "-C", str(worktree_path), "diff", "HEAD", "--name-only", "--"],
                text=True,
            ).splitlines()

        untracked_files = subprocess.check_output(
            ["git", "-C", str(worktree_path), "ls-files", "--others", "--exclude-standard"],
            text=True,
        ).splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Failed to inspect sealed worktree: {exc}") from exc

    return {
        "tracked_changes": [path for path in tracked_changes if path],
        "untracked_files": [path for path in untracked_files if path],
    }


def validate_governed_preflight() -> dict[str, Any]:
    """Preflight check using P8AttestationPolicy read-only SQLite access to verify sealed governance."""
    checks: dict[str, Any] = {}

    # 1. Sealed worktree path existence
    if not SEALED_WORKTREE_PATH.exists():
        raise RuntimeError(f"Sealed worktree not found at: {SEALED_WORKTREE_PATH}")
    checks["sealed_worktree_exists"] = True

    # 2. Git commit verification
    try:
        current_commit = subprocess.check_output(
            ["git", "-C", str(SEALED_WORKTREE_PATH), "rev-parse", "HEAD"],
            text=True
        ).strip()
    except Exception as exc:
        raise RuntimeError(f"Failed to check git commit SHA: {exc}") from exc

    if current_commit != SEALED_COMMIT_SHA:
        raise RuntimeError(
            f"Sealed worktree commit mismatch: expected {SEALED_COMMIT_SHA}, found {current_commit}"
        )
    checks["sealed_commit_sha"] = current_commit

    # 3. Clean worktree check (content-aware & untracked-aware)
    cleanliness = _inspect_worktree_cleanliness(SEALED_WORKTREE_PATH)
    if cleanliness["tracked_changes"]:
        changed = "\n".join(cleanliness["tracked_changes"])
        raise RuntimeError(f"Sealed worktree has uncommitted content changes:\n{changed}")
    if cleanliness["untracked_files"]:
        untracked = "\n".join(cleanliness["untracked_files"])
        raise RuntimeError(f"Sealed worktree has untracked files:\n{untracked}")
    checks["worktree_clean"] = True

    # 4. Attestation check via P8AttestationPolicy
    policy = P8AttestationPolicy(SEALED_WORKTREE_PATH)
    attestation = policy.attest_store(policy.canonical_evidence_log, policy.canonical_reservation_db)

    if not attestation.is_valid:
        raise RuntimeError(f"Sealed attestation failed: {attestation.attestation_errors}")

    checks["active_epoch_id"] = attestation.active_epoch_id
    checks["active_epoch_commit"] = attestation.metadata.get("code_commit_sha")
    checks["artifact_sha256"] = attestation.metadata.get("artifact_sha256")

    # 5. Runtime Lock Inspection (Advisory Preflight)
    lock_path = SEALED_WORKTREE_PATH / "runtime" / "paper" / EXPECTED_DEPLOYMENT_ID / "state" / "runtime.lock"
    if lock_path.exists():
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_pid = int(lock_data.get("process_id") or 0)
            if lock_pid > 0 and _is_pid_alive(lock_pid):
                checks["lock_status"] = f"ADVISORY_ACTIVE_LOCK (PID {lock_pid} active - child RuntimeLock will acquire/verify)"
            else:
                checks["lock_status"] = f"RECOVERABLE_STALE_LOCK (PID {lock_pid} inactive)"
        except (json.JSONDecodeError, ValueError):
            checks["lock_status"] = "LOCK_FILE_INVALID"
    else:
        checks["lock_status"] = "NO_LOCK_FILE"

    checks["preflight_status"] = "PASS"
    return checks


def main():
    parser = argparse.ArgumentParser(description="Continuous Foreground Manual Runner")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--governed",
        action="store_true",
        help="Run in governed evidence-eligible mode (requires sealed worktree 4efed1f, active epoch, evidence_eligible=true)",
    )
    mode_group.add_argument(
        "--diagnostic",
        action="store_true",
        help="Run in diagnostic mode (bypass runtime lock, evidence_eligible=false)",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Perform preflight verification and exit without launching continuous runner loop or creating evidence",
    )
    args = parser.parse_args()

    is_governed = args.governed or (not args.diagnostic and os.getenv("BTC_EVIDENCE_ELIGIBLE", "").lower() == "true")

    # Handle --preflight-only
    if args.preflight_only:
        print("=" * 75)
        print("   BESTTIME CRYPTO - RUNNER PREFLIGHT VERIFICATION")
        print("=" * 75)
        print(f"[MODE] Mode: {'GOVERNED' if is_governed else 'DIAGNOSTIC'}")
        if is_governed:
            try:
                res = validate_governed_preflight()
                print(f"[PREFLIGHT PASS] Sealed Worktree: {SEALED_WORKTREE_PATH}")
                print(f"[PREFLIGHT PASS] Sealed Commit:   {res['sealed_commit_sha']}")
                print(f"[PREFLIGHT PASS] Active Epoch:    {res['active_epoch_id']}")
                print(f"[PREFLIGHT PASS] Artifact SHA:    {res['artifact_sha256']}")
                print(f"[PREFLIGHT PASS] Lock Inspection: {res['lock_status']}")
                print("=" * 75)
                sys.exit(0)
            except Exception as exc:
                print(f"[PREFLIGHT FAIL] {exc}", file=sys.stderr)
                print("=" * 75, file=sys.stderr)
                sys.exit(1)
        else:
            print("[PREFLIGHT PASS] Diagnostic mode preflight passed.")
            print("=" * 75)
            sys.exit(0)

    # Logging directory setup
    logs_dir = PROJECT_ROOT / "logs" / "manual_runs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = logs_dir / f"manual_runner_{timestamp_str}.log"

    if is_governed:
        try:
            preflight = validate_governed_preflight()
            print(f"[GOVERNANCE] Active Evidence Epoch Validated: {preflight['active_epoch_id']}")
        except Exception as exc:
            print(f"[GOVERNANCE ERROR] Sealed preflight validation failed: {exc}", file=sys.stderr)
            print("[GOVERNANCE ERROR] Cannot run in --governed mode without a valid sealed worktree and ACTIVE epoch.", file=sys.stderr)
            print("[HINT] Run with --diagnostic for debugging runtime errors.", file=sys.stderr)
            sys.exit(1)

        # Build isolated child environment for sealed execution
        child_env = dict(os.environ)

        for path_var in [
            "BTC_RUNTIME_ROOT",
            "BTC_DATA_DIR",
            "BTC_LOG_DIR",
            "BTC_MODEL_DIR",
            "BTC_STATE_DIR",
            "BTC_EXECUTION_DATA_DIR",
            "BTC_PREDICTION_AUDIT_DIR",
            "BTC_RUNTIME_EVIDENCE_PATH",
            "BTC_RESERVATION_DB_PATH",
            "BTC_RUNTIME_LOCK_PATH",
        ]:
            child_env.pop(path_var, None)

        child_env["PYTHONPATH"] = str(SEALED_WORKTREE_PATH)
        child_env["PYTHONNOUSERSITE"] = "1"
        child_env["BTC_DEPLOYMENT_ID"] = EXPECTED_DEPLOYMENT_ID
        child_env["BTC_PAPER_RUN_ID"] = EXPECTED_PAPER_RUN_ID
        child_env["BTC_ANALYSIS_UNIVERSE"] = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
        child_env["AUTO_TRADE_COINS"] = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
        child_env["BTC_EVIDENCE_ELIGIBLE"] = "true"
        child_env["BTC_DISABLE_RUNTIME_LOCK"] = "0"
        child_env["BTC_RUNTIME_ENVIRONMENT"] = "paper"
        child_env["LIVE_TRADING_ENABLED"] = "false"
        child_env["AUTO_TRADE_DRY_RUN"] = "true"

        print("=" * 75)
        print("   BESTTIME CRYPTO - CONTINUOUS FOREGROUND RUNNER (SEALED GOVERNED MODE)")
        print("=" * 75)
        print(f"[MODE] Mode:             GOVERNED (SEALED EVIDENCE ELIGIBLE)")
        print(f"[WORKTREE] Worktree:     {SEALED_WORKTREE_PATH}")
        print(f"[COMMIT] Commit SHA:     {preflight['sealed_commit_sha']}")
        print(f"[EPOCH] Active Epoch:    {preflight['active_epoch_id']}")
        print(f"[LOG] File log lưu tại:  {log_file_path}")
        print(f"[ENV] Evidence Eligible: true")
        print(f"[ENV] Runtime Lock:      ENABLED")
        print("[NOTE] Bot đang chạy LIÊN TỤC trên Terminal trong Sealed Worktree.")
        print("[NOTE] Nhấn Ctrl+C để dừng runner bất kỳ lúc nào.")
        print("=" * 75 + "\n")

        cmd = [sys.executable, str(SEALED_WORKTREE_PATH / "main.py")]

        with open(log_file_path, "w", encoding="utf-8") as f_log:
            proc = subprocess.Popen(
                cmd,
                cwd=str(SEALED_WORKTREE_PATH),
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                for line in proc.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    f_log.write(line)
                    f_log.flush()
                proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                print("\n\n[STOP] Đã dừng Governed Runner theo yêu cầu người dùng (Ctrl+C).")
                print(f"[LOG] File log đã được lưu tại: {log_file_path}")
                print("=" * 75)

        # Propagate child exit code
        ret_code = proc.returncode if proc.returncode is not None else 1
        if ret_code != 0:
            print(f"[GOVERNANCE ERROR] Governed runner process exited with code {ret_code}", file=sys.stderr)
        sys.exit(ret_code)

    else:
        # Diagnostic Mode (Dev workspace execution)
        os.environ["BTC_DEPLOYMENT_ID"] = EXPECTED_DEPLOYMENT_ID
        os.environ["BTC_PAPER_RUN_ID"] = EXPECTED_PAPER_RUN_ID
        os.environ["BTC_ANALYSIS_UNIVERSE"] = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
        os.environ["AUTO_TRADE_COINS"] = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
        os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
        os.environ["BTC_DISABLE_RUNTIME_LOCK"] = "1"
        os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
        os.environ["LIVE_TRADING_ENABLED"] = "false"
        os.environ["AUTO_TRADE_DRY_RUN"] = "true"

        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        print("=" * 75)
        print("   BESTTIME CRYPTO - CONTINUOUS FOREGROUND RUNNER (DIAGNOSTIC MODE)")
        print("=" * 75)
        print(f"[MODE] Mode:             DIAGNOSTIC (NON-ELIGIBLE)")
        print(f"[LOG] File log lưu tại:  {log_file_path}")
        print(f"[ENV] Evidence Eligible: false")
        print(f"[ENV] Runtime Lock:      BYPASSED")
        print(f"[ENV] Analysis Universe: {os.getenv('BTC_ANALYSIS_UNIVERSE')}")
        print("[NOTE] Bot đang chạy LIÊN TỤC trên Terminal (Diagnostic Mode).")
        print("[NOTE] Nhấn Ctrl+C để dừng runner bất kỳ lúc nào.")
        print("=" * 75 + "\n")

        sys.argv = ["main.py"]

        class TeeStream:
            def __init__(self, original_stream, log_file):
                self.original_stream = original_stream
                self.log_file = log_file

            def write(self, buf):
                try:
                    self.original_stream.write(buf)
                    self.original_stream.flush()
                except Exception:
                    pass
                try:
                    self.log_file.write(buf)
                    self.log_file.flush()
                except Exception:
                    pass

            def flush(self):
                try:
                    self.original_stream.flush()
                except Exception:
                    pass
                try:
                    self.log_file.flush()
                except Exception:
                    pass

        with open(log_file_path, "w", encoding="utf-8") as f_log:
            orig_stdout = sys.stdout
            orig_stderr = sys.stderr
            sys.stdout = TeeStream(orig_stdout, f_log)
            sys.stderr = TeeStream(orig_stderr, f_log)
            try:
                from main import main as run_main
                run_main()
            except KeyboardInterrupt:
                print("\n\n[STOP] Đã dừng Runner theo yêu cầu người dùng (Ctrl+C).")
                print(f"[LOG] File log đã được lưu tại: {log_file_path}")
                print("=" * 75)
            finally:
                sys.stdout = orig_stdout
                sys.stderr = orig_stderr


if __name__ == "__main__":
    main()
