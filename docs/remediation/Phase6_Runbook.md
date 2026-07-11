# Phase 6 Runbook — Live Production Operations

> **Project**: `besttime-crypto` — AI Quant Trading Platform  
> **Version**: Phase 6  
> **Status**: Operational reference for live production  
> **Live capital**: `BLOCKED` until `PHASE5_LIVE_READINESS_GATE = PASS`

---

## CRITICAL: Pre-Live Checklist

Before enabling live mode, **all** items below must be verified:

| # | Check | Method | Required State |
|---|-------|--------|----------------|
| 1 | API key has trade permission | Exchange dashboard | `YES` |
| 2 | Withdrawal is **DISABLED** | Exchange dashboard | `DISABLED` |
| 3 | IP whitelist is active | Exchange dashboard | `ENABLED` |
| 4 | Clock drift ≤ 250ms median | `live_checklist.run()` | `PASS` |
| 5 | Model snapshot exists & fresh | `live_checklist.run()` | `PASS` |
| 6 | Phase 5 live gate | `phase5_report_latest.json` | `PASS` |
| 7 | Rollback artifacts ≤ 48h old | `live_checklist.run()` | `PASS` |
| 8 | Kill-switch in `ARMED` state | `kill_switch_state.json` | `ARMED` |
| 9 | Live mode flag enabled | `live_mode_enabled.json` | `enabled: true` |
| 10 | Alert remote channel active | `AlertManager.has_remote_channel()` | `True` |

---

## 1. Startup Procedure

### Linux/macOS
```bash
# 1. Run full checklist (must specify acknowledged manual items if any)
export LIVE_ACKNOWLEDGED_MANUAL_ITEMS="api_key_permissions,ip_whitelist"
python -c "from btc_scraper.execution.live_checklist import LiveChecklist; import os; acks=[x.strip() for x in os.getenv('LIVE_ACKNOWLEDGED_MANUAL_ITEMS','').split(',') if x.strip()]; print(LiveChecklist(acknowledged_manual_items=acks).run().to_dict())"

# 2. Verify kill-switch is ARMED
cat data/kill_switch_state.json

# 3. Enable live mode (manual step)
echo '{"enabled": true, "enabled_at": "UTC_TIMESTAMP", "enabled_by": "OPERATOR"}' > data/live_mode_enabled.json

# 4. Start live monitor
python -c "from btc_scraper.execution.live_monitor import LiveMonitor; m=LiveMonitor(); m.start()"

# 5. Export environment variables for the live fail-closed check and start main trading loop
export LIVE_TRADING_ENABLED="true"
export AUTO_TRADE_DRY_RUN="false"
export LIVE_AUTHORIZATION_TOKEN="YOUR_SECRET_PRODUCTION_TOKEN"
python main_live.py
```

### Windows (PowerShell)
```powershell
# 1. Run full checklist (must specify acknowledged manual items if any)
$env:LIVE_ACKNOWLEDGED_MANUAL_ITEMS="api_key_permissions,ip_whitelist"
python -c "from btc_scraper.execution.live_checklist import LiveChecklist; import os; acks=[x.strip() for x in os.getenv('LIVE_ACKNOWLEDGED_MANUAL_ITEMS','').split(',') if x.strip()]; print(LiveChecklist(acknowledged_manual_items=acks).run().to_dict())"

# 2. Verify kill-switch is ARMED
Get-Content data/kill_switch_state.json

# 3. Enable live mode (manual step)
'{"enabled": true, "enabled_at": "UTC_TIMESTAMP", "enabled_by": "OPERATOR"}' | Out-File -Encoding utf8 data/live_mode_enabled.json

# 4. Start live monitor
python -c "from btc_scraper.execution.live_monitor import LiveMonitor; m=LiveMonitor(); m.start()"

# 5. Export environment variables for the live fail-closed check and start main trading loop
$env:LIVE_TRADING_ENABLED="true"
$env:AUTO_TRADE_DRY_RUN="false"
$env:LIVE_AUTHORIZATION_TOKEN="YOUR_SECRET_PRODUCTION_TOKEN"
python main_live.py
```

---

## 2. Shutdown Procedure (Graceful)

### Linux/macOS
```bash
# 1. Disable live mode (blocks new entries, allows exits to complete)
echo '{"enabled": false, "disabled_at": "UTC_TIMESTAMP", "disabled_by": "OPERATOR"}' > data/live_mode_enabled.json

# 2. Wait for open orders to complete (check live_monitor_snapshot.json)
cat data/execution/live_monitor_snapshot.json | python -c "import sys,json; d=json.load(sys.stdin); print('Open positions:', d['open_positions'])"

# 3. Stop services after all positions are closed
kill $(pgrep -f main_live.py)
```

### Windows (PowerShell)
```powershell
# 1. Disable live mode (blocks new entries, allows exits to complete)
'{"enabled": false, "disabled_at": "UTC_TIMESTAMP", "disabled_by": "OPERATOR"}' | Out-File -Encoding utf8 data/live_mode_enabled.json

# 2. Wait for open orders to complete (check live_monitor_snapshot.json)
Get-Content data/execution/live_monitor_snapshot.json | python -c "import sys,json; d=json.load(sys.stdin); print('Open positions:', d['open_positions'])"

# 3. Stop services after all positions are closed
Stop-Process -Name "python" -Force  # Or close the terminal running main_live.py
```

---

## 3. Emergency Stop (Kill-Switch Trigger)

### Manual trigger via signal file

#### Linux/macOS
```bash
# Fastest method — creates signal file picked up within 1 loop iteration
touch data/.kill_signal
```

#### Windows (PowerShell)
```powershell
# Fastest method — creates signal file picked up within 1 loop iteration
New-Item -ItemType File -Path data/.kill_signal -Force
```

### Via API endpoint

```bash
curl -X POST http://localhost:8000/api/live/kill-switch/trigger \
  -H "Content-Type: application/json" \
  -d '{"trigger": "manual_emergency", "operator": "OPERATOR_NAME", "reason": "REASON"}'
```

### Expected behavior

After trigger:
1. State changes to `HALTED` (written atomically)
2. **Type A triggers** (model_unavailable, data_stale): blocks new entries only
3. **Type B triggers** (execution_anomaly, position_mismatch_minor): cancels open orders  
4. **Type C triggers** (daily_loss_breach, manual_emergency): cancels orders + closes positions
5. CRITICAL alert sent via Telegram + local log

---

## 4. Kill-Switch Reset Protocol

> ⚠️ **Never reset without verifying the root cause is resolved.**

### Step 1: Read current state

#### Linux/macOS
```bash
cat data/kill_switch_state.json
```

#### Windows (PowerShell)
```powershell
Get-Content data/kill_switch_state.json
```

Verify:
- `trigger`: understand what caused the halt
- `trigger_value` vs `threshold`: confirm breach is resolved
- `requires_manual_reset`: if `true`, operator acknowledgment needed

### Step 2: Resolve root cause

| Trigger | Resolution |
|---------|-----------|
| `daily_loss_breach` | Review trades; confirm loss is acceptable; adjust limits if needed |
| `execution_anomaly` | Check exchange connectivity and order logs |
| `position_mismatch_minor` | Reconcile positions with exchange; fix discrepancy |
| `position_mismatch_severe` | **Full manual review required** before reset |
| `model_unavailable` | Restart model service; confirm predictions are loading |
| `data_stale` | Check data collector; confirm alt data flow is restored |

### Step 3: Generate reset token

```python
from btc_scraper.execution.kill_switch import KillSwitch
ks = KillSwitch()
ks.notify_dependency_recovered()  # moves HALTED → RECOVERY_PENDING
token = ks.generate_reset_token()
print("Reset token:", token)
```

### Step 4: Execute reset

```python
ks.reset(
    token=token,
    reason="Root cause resolved: [describe resolution]",
    operator="OPERATOR_NAME",
    positions_acknowledged=True,  # confirm you have reviewed open positions
)
```

### Step 5: Verify

#### Linux/macOS
```bash
cat data/kill_switch_state.json  # should show state: ARMED
cat data/execution/live_monitor_snapshot.json  # confirm system health
```

#### Windows (PowerShell)
```powershell
Get-Content data/kill_switch_state.json  # should show state: ARMED
Get-Content data/execution/live_monitor_snapshot.json  # confirm system health
```

---

## 5. Rollback Procedure

### When to rollback

- Execution bug causing unexpected fills
- Model producing grossly wrong signals
- Data pipeline corruption
- Config error discovered after enabling live

### Steps

#### Linux/macOS
```bash
# 1. Trigger emergency stop immediately
touch data/.kill_signal

# 2. Wait 5 seconds for halt to propagate
sleep 5

# 3. Verify HALTED
cat data/kill_switch_state.json

# 4. Manually close any remaining positions on exchange dashboard

# 5. Restore previous model snapshot
cp data/rollback/model_config_YYYYMMDD.json data/feature_store/
cp data/rollback/execution_config_YYYYMMDD.json config/

# 6. Document incident in audit log
python -c "
from btc_scraper.execution.live_audit_log import LiveAuditLog
log = LiveAuditLog()
log.record('ROLLBACK', {'reason': 'DESCRIBE', 'from_config': 'X', 'to_config': 'Y'}, operator='NAME')
"

# 7. Follow Kill-Switch Reset Protocol before re-enabling
```

#### Windows (PowerShell)
```powershell
# 1. Trigger emergency stop immediately
New-Item -ItemType File -Path data/.kill_signal -Force

# 2. Wait 5 seconds for halt to propagate
Start-Sleep -Seconds 5

# 3. Verify HALTED
Get-Content data/kill_switch_state.json

# 4. Manually close any remaining positions on exchange dashboard

# 5. Restore previous model snapshot
Copy-Item data/rollback/model_config_YYYYMMDD.json data/feature_store/
Copy-Item data/rollback/execution_config_YYYYMMDD.json config/

# 6. Document incident in audit log
python -c "
from btc_scraper.execution.live_audit_log import LiveAuditLog
log = LiveAuditLog()
log.record('ROLLBACK', {'reason': 'DESCRIBE', 'from_config': 'X', 'to_config': 'Y'}, operator='NAME')
"

# 7. Follow Kill-Switch Reset Protocol before re-enabling
```

---

## 6. Exchange Outage Handling

When exchange API is unavailable:

1. Kill-switch auto-triggers `exchange_api_instability` (Type B — cancel orders, keep positions)
2. Monitor `live_monitor_snapshot.json` for exchange health
3. Do NOT manually reset until connectivity is stable for ≥ 5 minutes
4. When exchange recovers:
   - Run reconciliation: verify positions match exchange state
   - If positions match: follow Reset Protocol
   - If positions mismatch: see Position Mismatch below

---

## 7. Database Outage Handling

When MongoDB/local DB is unavailable:

1. Kill-switch auto-triggers `db_degraded` (Type A — blocks new entries)
2. Existing positions are unaffected (no forced close)
3. When DB recovers:
   - Verify all fills were persisted (check fill logs vs DB)
   - Replay any missing fills via `SQLiteEventSpool.replay()`
   - Follow Kill-Switch Reset Protocol

---

## 8. Position Mismatch Resolution

#### Linux/macOS
```bash
# 1. Get current exchange positions
python -c "from btc_scraper.execution.exchange_adapter import ReadOnlyExchangeAdapter; ..."

# 2. Get internal position state
cat data/execution/live_monitor_snapshot.json

# 3. Compare — identify discrepancies
# 4. For minor mismatch (rounding, timing): update internal state, reset kill-switch
# 5. For severe mismatch (missing position): full manual reconciliation before reset
```

#### Windows (PowerShell)
```powershell
# 1. Get current exchange positions
python -c "from btc_scraper.execution.exchange_adapter import ReadOnlyExchangeAdapter; ..."

# 2. Get internal position state
Get-Content data/execution/live_monitor_snapshot.json

# 3. Compare — identify discrepancies
# 4. For minor mismatch (rounding, timing): update internal state, reset kill-switch
# 5. For severe mismatch (missing position): full manual reconciliation before reset
```

---

## 9. Controlled Rollout — Stage Transitions

### Check promotion eligibility

```python
from btc_scraper.execution.controlled_rollout import ControlledRollout
cr = ControlledRollout()
print(cr.evaluate_promotion())
```

### Promote

```python
success = cr.promote()
# Automatically updates HardRiskLimits to new stage limits
```

### Manual demotion (if needed)

```python
cr.demote(reason="Observed slippage above acceptable limit")
```

---

## 10. Daily Loss Circuit Breaker

The `HardRiskLimits` tracks two loss windows simultaneously:

| Window | Metric | Stage 1 Limit | Stage 2 Limit |
|--------|--------|--------------|--------------|
| Calendar day | Realized + Unrealized + Fees | $5 | $10 |
| Rolling 24h | Same | $7 | $14 |

When either limit is breached:
1. New entries are blocked automatically
2. Exits and reduces are still allowed
3. At threshold (75% of limit), WARNING alert is sent

---

## 11. Emergency Close All Positions

```python
from btc_scraper.execution.kill_switch import KillSwitch
ks = KillSwitch()
ks.trigger("manual_emergency")
# Type C action: cancels orders + closes all positions via exchange adapter
```

For direct manual close without kill-switch:

#### Linux/macOS
```bash
# Via exchange dashboard: close all positions manually
# Then update internal state:
echo '{"enabled": false}' > data/live_mode_enabled.json
```

#### Windows (PowerShell)
```powershell
# Via exchange dashboard: close all positions manually
# Then update internal state:
'{"enabled": false}' | Out-File -Encoding utf8 data/live_mode_enabled.json
```

---

## 12. Monitoring Checklist (Every 30 Minutes During Live)

- [ ] `kill_switch_state.json` → state = `ARMED`
- [ ] `live_monitor_snapshot.json` → system_health.ready = `true`
- [ ] Daily equity change within limits
- [ ] No new CRITICAL alerts in `logs/alerts.log`
- [ ] Position counts match expectations
- [ ] Rollout stage unchanged

---

## 13. Incident Documentation Template

After every incident, document in audit log:

```python
from btc_scraper.execution.live_audit_log import LiveAuditLog
log = LiveAuditLog()
log.record(
    event_type="INCIDENT",
    payload={
        "incident_type": "TYPE",
        "description": "WHAT HAPPENED",
        "resolution": "HOW RESOLVED",
        "duration_minutes": 0,
        "positions_affected": [],
        "financial_impact_usdt": 0.0,
    },
    operator="OPERATOR_NAME",
    reason="BRIEF REASON",
)
```
