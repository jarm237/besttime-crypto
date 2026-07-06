**Overview**
- **Purpose**: Hướng dẫn triển khai, lập lịch và kiểm tra (verify) cho pipeline huấn luyện/hiệu chỉnh model meta (`periodic_recalibration.py`).

**Prerequisites**
- **Python**: 3.8+ trên PATH (hoặc chỉnh `python` path trong scripts).
- **Git**: cấu hình credential (SSH key hoặc credential helper) nếu bật auto-commit.
- **Dependencies**: cài đặt từ `requirements.txt`.

Quick install:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Quick Verify (local)**
- Chạy đánh giá hiện tại:

```bash
python scripts/eval_meta_model.py
```
- Kiểm tra kết quả:
  - `logs/meta_model_eval_results.json` — metrics hiện tại.
  - Chạy kiểm tra ngưỡng:

```bash
python scripts/check_metrics_threshold.py
# sinh logs/metrics_check_result.json
```

**Packaging model (optional)**
- Tạo gói chứa artifact + evaluation:

```bash
python scripts/pack_model.py
# tạo file trong dist/package_*.tar.gz
```

**CI (GitHub Actions)**
- Một workflow mẫu đã được thêm: `.github/workflows/validate_model.yml`.
- Mỗi push trên `logs/**` và `scripts/**` sẽ chạy:
  - `eval_meta_model.py`
  - `check_metrics_threshold.py`
  - `build_label_quality_report.py`
  - `check_label_quality_threshold.py`
- Điều chỉnh ngưỡng trong `scripts/check_metrics_threshold.py` nếu muốn.
- Điều chỉnh ngưỡng label quality trong `scripts/check_label_quality_threshold.py` nếu muốn.

**Scheduling (Periodic Recalibration)**
- Windows (PowerShell helper): `scripts/setup_scheduled_task.ps1`.
  - Chạy PowerShell as Administrator rồi:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Workspaces\Vọc vạch\scripts\setup_scheduled_task.ps1" -Time 02:00 -Schedule DAILY -TaskName PeriodicRecalibration
```
  - Log: `logs/periodic_recalibration_task.log`.
  - Xóa task:

```powershell
schtasks /Delete /TN PeriodicRecalibration /F
```

- Ubuntu (cron): `scripts/setup_cron.sh` tự nhận diện repo root, ưu tiên `.venv/bin/python` nếu có, và chạy qua wrapper `scripts/run_periodic_recalibration.sh` để rotate log khi log hiện tại vượt ngưỡng dung lượng:

```bash
sudo apt update
sudo apt install -y cron
sudo systemctl enable --now cron

bash scripts/setup_cron.sh
crontab -l  # xem entry
```

- Đổi lịch chạy, bật auto-commit, hoặc gỡ cron job:

```bash
SCHEDULE="0 */6 * * *" bash scripts/setup_cron.sh
AUTO_COMMIT=1 bash scripts/setup_cron.sh
KEEP_LOGS=14 bash scripts/setup_cron.sh
MAX_LOG_SIZE_MB=25 bash scripts/setup_cron.sh
bash scripts/setup_cron.sh print
bash scripts/setup_cron.sh remove
```

- Mặc định giữ `7` file log gần nhất: `logs/periodic_recalibration_cron.log`, `.1`, `.2`, ... Có thể đổi bằng `KEEP_LOGS`.
- Mặc định chỉ rotate khi log đạt `10 MB`. Có thể đổi bằng `MAX_LOG_SIZE_MB`.

**Artifact retention policy**
- `scripts/run_periodic_recalibration.sh` tự gọi `scripts/cleanup_recalibration_artifacts.sh` sau mỗi lần recalibration thành công.
- Mặc định giữ lại:
  - `3` report mới nhất: `logs/recalibration_*.json` (không đụng `logs/recalibration_latest.json`).
  - `3` model mới nhất: `logs/meta_model_calibrated_periodic_*.joblib`.
- Biến môi trường liên quan:
  - `CLEANUP_ENABLED=1` (mặc định): bật/tắt cleanup sau khi chạy.
  - `KEEP_REPORTS=3` (mặc định): số report giữ lại.
  - `KEEP_MODELS=3` (mặc định): số model giữ lại.
- Chạy cleanup thủ công:

```bash
KEEP_REPORTS=5 KEEP_MODELS=5 bash scripts/cleanup_recalibration_artifacts.sh
DRY_RUN=1 KEEP_REPORTS=5 KEEP_MODELS=5 bash scripts/cleanup_recalibration_artifacts.sh
```

**Auto-commit / Push**
- `scripts/periodic_recalibration.py` có hỗ trợ auto-commit khi `AUTO_COMMIT=1`.
- Đảm bảo account chạy task có quyền git push (SSH key hoặc credential helper). Nếu cần chạy khi không có session người dùng, cung cấp `-User`/`-Password` cho scheduled task (cẩn thận với bảo mật).

**Verify scheduled run**
- Sau task chạy, kiểm tra:
  - `logs/recalibration_latest.json` (báo cáo),
  - `logs/meta_model_calibrated_*.joblib` (artifact),
  - `logs/periodic_recalibration_task.log` (stdout/stderr redirect).
- Nếu CI active, cũng kiểm tra GitHub Actions run kết quả trên repo.

**Troubleshooting**
- Permission denied khi tạo Scheduled Task: chạy PowerShell as Administrator.
- `git commit` thất bại: kiểm tra `git config user.name` / `user.email` và credential.
- Missing Python modules: `pip install -r requirements.txt`.

**Files of interest**
- **Evaluation**: [scripts/eval_meta_model.py](scripts/eval_meta_model.py)
- **Calibration**: [scripts/run_calibration_70_20_10.py](scripts/run_calibration_70_20_10.py)
- **Periodic run**: [scripts/periodic_recalibration.py](scripts/periodic_recalibration.py)
- **Scheduler helpers**: [scripts/setup_scheduled_task.ps1](scripts/setup_scheduled_task.ps1), [scripts/setup_cron.sh](scripts/setup_cron.sh), [scripts/run_periodic_recalibration.sh](scripts/run_periodic_recalibration.sh)
- **Cleanup helper**: [scripts/cleanup_recalibration_artifacts.sh](scripts/cleanup_recalibration_artifacts.sh)
- **CI workflow**: [.github/workflows/validate_model.yml](.github/workflows/validate_model.yml)

**Next steps (recommended)**
- Review/adjust thresholds in `scripts/check_metrics_threshold.py`.
- Configure git credentials for the account that will run scheduled tasks.
- (Optional) Add a small wrapper to rotate logs and keep only N last runs.

