# Repository instructions

This is a Python repository.

Use GitNexus when repository-wide architectural context, dependency analysis,
execution-flow tracing, or change-impact analysis is required.

## GitNexus tool selection

Before editing code:

1. Use `list_repos` only when the target repository is ambiguous.
2. Use `query` when the implementation location or execution flow is unknown.
3. Use `context` for the primary modules, classes, functions, methods, or
   protocols being modified.
4. Use `impact` before changing public, exported, inherited, registered, shared,
   or widely reused behavior.
5. Use `trace` when the relationship between two known symbols is unclear.
6. Use `detect_changes` once after the final implementation.
7. Do not call every GitNexus tool by default.
8. Do not repeatedly re-index between individual edits.

## Python workflow

Before changing behavior:

1. Identify the public API and existing callers.
2. Identify configuration, dependency-injection, registration, or plugin wiring.
3. Inspect relevant tests and fixtures.
4. Preserve backward compatibility unless the task explicitly changes it.
5. Make the smallest coherent change.

After changing code:

1. Run the formatter check.
2. Run linting.
3. Run static type checking.
4. Run the relevant tests.
5. Run the full test suite when shared or foundational behavior changed.
6. Run `gitnexus detect-changes`.
7. Refresh the GitNexus index after final source changes.

## General engineering rules

- Do not use broad exception handling such as `except Exception` unless the
  boundary genuinely requires it.
- Never silently swallow an exception.
- Preserve the original exception using `raise ... from exc` when translating it.
- Do not use mutable values as default arguments.
- Do not add `# type: ignore` merely to hide a typing problem.
- Do not introduce `Any` where a concrete type, Protocol, TypedDict, dataclass,
  or generic type can express the contract.
- Keep I/O boundaries separate from domain logic.
- Preserve idempotency, transactions, retries, logging, tracing, and correlation
  behavior.
- Avoid hidden global state and import-time side effects.
- Update tests whenever behavior changes.
- Do not claim completion when tests or static checks are failing.
