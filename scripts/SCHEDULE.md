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

---

## Parse.bot ETF Flow Scheduled Jobs

ETF flow data is daily data and must **not** be fetched inside every 15-minute scan. Jobs are triggered automatically by `AlternativeDataScheduler` based on Vietnam timezone (`Asia/Ho_Chi_Minh`).

### Cron Schedule

| Job | Cron | Time (VN) | Symbols |
|:---|:---|:---|:---|
| `fetch_parsebot_etf_recent` | `0 6,7,8,9 * * 2-6` | 06:00–09:00 Tue–Sat | BTC, ETH, SOL |
| `fetch_parsebot_etf_all` | `30 9 * * 2-6` | 09:30 Tue–Sat | BTC, ETH |
| `fetch_parsebot_fund_info` | `0 10 * * *` | 10:00 daily | FUND |

### Manual CLI trigger (dry-run)

```powershell
# Run all jobs in dry-run mode
.venv\Scripts\python scripts\fetch_parsebot_etf_jobs.py --job run-all --dry-run

# Run specific job
.venv\Scripts\python scripts\fetch_parsebot_etf_jobs.py --job recent
.venv\Scripts\python scripts\fetch_parsebot_etf_jobs.py --job all
.venv\Scripts\python scripts\fetch_parsebot_etf_jobs.py --job fund
```

### Environment

```env
PARSEBOT_ENABLED=true
PARSEBOT_API_KEY=<your_key>
PARSEBOT_BASE_URL=<your_endpoint_from_dashboard>
ETF_FLOW_TIMEZONE=Asia/Ho_Chi_Minh
ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA=false
```

### Auto-scheduling

When `PARSEBOT_ENABLED=true`, `AlternativeDataScheduler._collect()` automatically calls the appropriate job function at the correct local time on each collection cycle — no OS cron or Windows Task Scheduler required.
