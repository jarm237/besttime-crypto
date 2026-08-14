# AHDV-W1.4 FRED Probe Environment

Scope: unblock FRED probe classification without treating environment failure as source unavailability.

## Current Environment

| Check | Result |
| --- | --- |
| `FRED_API_KEY` present | `False` |
| `FRED_API_KEY == demo` | `False` |
| key length | `0` |

## Classification

`fred` is:

```text
PROBE_BLOCKED_ENVIRONMENT
```

not:

```text
H0_UNAVAILABLE
```

## Required Probe Setup

Set `FRED_API_KEY` in the probe environment and rerun only the FRED Wave 1 timestamps using FRED realtime vintage parameters:

```text
realtime_start = replay date
realtime_end   = replay date
observation_end <= replay date
```

FRED remains a high-priority source because vintage/ALFRED semantics can provide strong PIT evidence when configured correctly.

