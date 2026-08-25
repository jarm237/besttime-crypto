<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **besttime-crypto** (19492 symbols, 32733 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/besttime-crypto/context` | Codebase overview, check index freshness |
| `gitnexus://repo/besttime-crypto/clusters` | All functional areas |
| `gitnexus://repo/besttime-crypto/processes` | All execution flows |
| `gitnexus://repo/besttime-crypto/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Mandatory GitNexus workflow

These repository rules apply to every software-engineering task that reads,
debugs, plans, reviews, modifies, or tests repository code.

## Task startup

1. Confirm that the working directory belongs to the intended Git repository.
2. From the repository root, run:

   ```bash
   ./scripts/gitnexus-ensure-fresh.sh
   ```

3. Use GitNexus before broad text search or cross-module manual browsing:
   query relevant concepts and execution flows, inspect symbol context, trace
   callers and callees, and run upstream impact analysis for shared symbols.
4. Do not begin cross-module edits using only `grep`, `rg`, `find`, or manual
   file browsing.

## Before editing

Before modifying a function, class, method, contract, schema, repository,
service, runtime component, or shared configuration:

1. Inspect the target with GitNexus `context`.
2. Run GitNexus `impact` in the upstream direction.
3. Identify direct and indirect callers, affected execution flows and modules,
   relevant tests, and persistence/API boundaries.
4. Warn the user before editing when the reported blast radius is HIGH or
   CRITICAL.

Context analysis is still required for a small isolated symbol edit, although
repository-wide exploration is not.

## Debugging

For bugs and failures, use GitNexus to locate the relevant execution flow,
trace from its entry point to the failing symbol, inspect callers, callees, and
data dependencies, then validate graph findings against source, logs, and
tests.

## Besttime-crypto critical paths

Upstream impact analysis is mandatory before modifying inference contracts,
artifact compatibility, the model registry, runtime stores, orchestration,
decisions/order planning, execution/fills, recovery/reconciliation, the
account ledger, or promotion/deployment gates.

For those areas, trace the complete applicable lineage:

```text
cycle -> feature snapshot -> prediction -> final decision -> order
      -> execution -> fill -> ledger -> reconciliation
```

## After editing source code

1. Run targeted tests and static checks. Run the full invariant or end-to-end
   suite when a shared contract changes.
2. Refresh the index:

   ```bash
   ./scripts/gitnexus-refresh.sh
   ```

3. Run GitNexus change detection against the appropriate base branch (normally
   `main`) and confirm only expected symbols, execution flows, and persistence
   boundaries changed. This machine has multiple indexed repositories, so pass
   the repository explicitly:

   ```bash
   node .gitnexus/run.cjs detect-changes \
     --repo besttime-crypto --scope compare --base-ref main
   ```
4. In the final report, list the GitNexus tools used, affected symbols and
   flows, tests/checks run, and any unresolved dynamic relationships.

## Exceptions and fallback

GitNexus is not required for tasks unrelated to repository code, such as
translation, general questions, or standalone documentation edits. If the
GitNexus MCP tools are unavailable, report that explicitly; use the equivalent
GitNexus CLI commands when possible, and continue with source-only inspection
only when the task can be completed safely.
