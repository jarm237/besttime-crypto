<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **besttime-crypto** (19348 symbols, 36357 relationships, 734 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact analysis before editing.** Use `impact({target: "symbolName", direction: "upstream"})` (MCP) or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .` (CLI fallback); report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/besttime-crypto/context` | Codebase overview, check index freshness |
| `gitnexus://repo/besttime-crypto/clusters` | All functional areas |
| `gitnexus://repo/besttime-crypto/processes` | All execution flows |
| `gitnexus://repo/besttime-crypto/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

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
