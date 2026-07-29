# 11 Final Remediation Plan

This file points to the consolidated remediation plan for the initial assessment:

- `BTC_Scraper_Remediation_Plan.md`
- `BTC_Scraper_Module_Scorecard.md`
- `BTC_Scraper_Test_Evidence.md`

## Recommended Waves

```text
Wave 1: test environment, compile blocker, prediction contract, execution dispatch - DONE
Wave 1b: test artifact isolation - DONE for code and isolated guard-enabled full-suite proof; production process restart/rehearsal pending
Wave 2: ML runtime restart/replay matrix - DONE for baseline persisted recovery
Wave 3: deterministic live exchange outage drills - DONE for fake-adapter baseline
Wave 4: runtime ownership and process isolation - DONE for code/test baseline
Wave 5: restart the running production process with the Parse.bot owned-path fix and repeat the in-place guard rehearsal
Wave 6: feature and collector point-in-time/replay evidence
Wave 7: production/paper data-log lifecycle taxonomy beyond owned runtime roots
Wave 8: exchange-integrated outage rehearsal and UI/Telegram operations
Wave 9: classify agents/causal/RL as research or gated production contributors
```

## Definition Of Done For Full Assessment

- 100% package groups have reviewed scorecards.
- All runtime entry points are labeled supported/research/deprecated.
- Full tests run and evidence is captured.
- Training/inference parity is proven.
- Backtest/runtime differences are listed.
- Paper/live differences are listed, including deterministic outage baseline versus exchange-integrated drill gaps.
- Runtime ownership is rehearsed with clean guard-enabled full-suite evidence.
- P0/P1 items have acceptance tests.
- At least one happy-path paper E2E and restart/replay path passes.
- Every module has a disposition: `KEEP`, `REFACTOR`, `REWRITE`, `DEPRECATE`, `RESEARCH_ONLY`, `PAPER_READY`, `PRODUCTION_READY`, or `BLOCKED`.
