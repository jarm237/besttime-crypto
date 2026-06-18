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

1. Edit `scripts/setup_cron.sh`, set `WORKDIR` to your repository path.
2. Run:

```bash
bash scripts/setup_cron.sh
```

Notes & prerequisites

- Ensure `python` (or `python3`) is on PATH of the account running the scheduler.
- If you rely on virtualenv, modify the action command to activate the environment prior to running the script.
- `AUTO_COMMIT=1` environment variable may be required for automatic push inside `periodic_recalibration.py`.
