Setup periodic recalibration (Windows Task Scheduler and cron)

Windows (PowerShell helper)

1. Edit and review `scripts/setup_scheduled_task.ps1` if needed. By default it:
   - Runs daily at 02:00 (change `-Time` arg to modify)
   - Calls `python scripts/periodic_recalibration.py` from the workspace root
   - Redirects stdout/stderr to `logs/periodic_recalibration_task.log`

2. To create the scheduled task now (requires admin or appropriate privilege):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_scheduled_task.ps1 -Time 02:00 -Schedule DAILY -TaskName PeriodicRecalibration
```

3. To remove the task:

```powershell
schtasks /Delete /TN PeriodicRecalibration /F
```

Linux / macOS (cron)

1. On Ubuntu, make sure cron is installed and running:

```bash
sudo apt update
sudo apt install -y cron
sudo systemctl enable --now cron
```

2. Install the default cron entry (daily at 02:00). The helper auto-detects the repository root, prefers `.venv/bin/python` when available, and calls a wrapper that rotates cron logs only when the current log exceeds the configured size threshold:

```bash
bash scripts/setup_cron.sh
crontab -l
```

3. Optional overrides:

```bash
SCHEDULE="0 */6 * * *" bash scripts/setup_cron.sh
AUTO_COMMIT=1 bash scripts/setup_cron.sh
KEEP_LOGS=14 bash scripts/setup_cron.sh
MAX_LOG_SIZE_MB=25 bash scripts/setup_cron.sh
LOGFILE="$PWD/logs/recalibration_ubuntu.log" bash scripts/setup_cron.sh
bash scripts/setup_cron.sh print
bash scripts/setup_cron.sh remove
```

Artifact retention policy

- Runner `scripts/run_periodic_recalibration.sh` automatically triggers `scripts/cleanup_recalibration_artifacts.sh` after each successful recalibration run.
- Default retention is:
   - Keep latest `3` report files: `logs/recalibration_*.json` (excluding `logs/recalibration_latest.json`).
   - Keep latest `3` model files: `logs/meta_model_calibrated_periodic_*.joblib`.
- Cleanup is controlled by environment variables in the runner:
   - `CLEANUP_ENABLED=1` (default): enable cleanup step.
   - `KEEP_REPORTS=3` (default): number of report files to retain.
   - `KEEP_MODELS=3` (default): number of model artifacts to retain.
- Manual cleanup example:

```bash
KEEP_REPORTS=5 KEEP_MODELS=5 bash scripts/cleanup_recalibration_artifacts.sh
DRY_RUN=1 KEEP_REPORTS=5 KEEP_MODELS=5 bash scripts/cleanup_recalibration_artifacts.sh
```

Notes & prerequisites

- Ensure `python3` is installed. If the repo has `.venv`, the helper uses `.venv/bin/python` automatically.
- Cron runs with a minimal environment, so prefer absolute paths and environment variables passed inline as shown above.
- By default the runner keeps `7` rotated logs: `periodic_recalibration_cron.log`, `.1`, `.2`, ... You can change this with `KEEP_LOGS`.
- Rotation only happens when the active log reaches `10 MB` by default. Change that threshold with `MAX_LOG_SIZE_MB`.
- `AUTO_COMMIT=1` environment variable may be required for automatic push inside `periodic_recalibration.py`.
