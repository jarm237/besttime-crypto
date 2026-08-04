---
applyTo: "**/*.py,**/pyproject.toml,**/pytest.ini,**/tox.ini,**/requirements*.txt"
---

# Python-specific instructions

## Language and typing

- Follow the Python version declared by the repository.
- Add type annotations to public functions, methods, classes, and module-level
  contracts.
- Prefer precise types over `Any`.
- Use `Protocol` for behavioral contracts when inheritance is unnecessary.
- Use `TypedDict`, dataclasses, or validated models for structured data.
- Preserve generic type parameters instead of erasing them.
- Use `collections.abc` types for public interfaces where appropriate.
- Avoid unnecessary runtime imports used only for typing.
- Respect the repository's postponed-annotation policy.

## Functions and modules

- Keep functions focused and explicit about inputs, outputs, and side effects.
- Avoid mutable default arguments.
- Avoid module-level initialization that performs network, database, filesystem,
  or environment-dependent work.
- Do not create circular imports to avoid restructuring dependencies.
- Keep private implementation details private.
- Preserve documented public APIs.

## Error handling

- Catch only exceptions that can be handled meaningfully.
- Never use a bare `except`.
- Do not log and suppress failures unless suppression is explicitly part of the
  application contract.
- Preserve exception causality with `raise NewError(...) from exc`.
- Do not expose infrastructure exceptions directly through domain or API layers.
- Include actionable context in logs without exposing secrets.

## Async code

- Never call blocking filesystem, database, HTTP, or CPU-heavy work directly on
  an event loop unless the library is explicitly asynchronous.
- Await coroutines exactly once.
- Do not create background tasks without ownership, cancellation, and error
  handling.
- Preserve timeout, cancellation, retry, and cleanup behavior.
- Use async context managers for async resources.
- Avoid mixing synchronous and asynchronous clients accidentally.

## Data and persistence

- Preserve transaction boundaries and idempotency guarantees.
- Do not perform per-row queries when a bulk query is available.
- Do not change serialization or database field names without checking every
  producer and consumer.
- Treat migrations as separate, reviewable changes.
- Avoid floating-point arithmetic for financial values; preserve the project's
  Decimal policy.

## Tests

- Use pytest conventions when pytest is configured.
- Keep tests deterministic and isolated.
- Do not depend on execution order.
- Mock external boundaries rather than the behavior being tested.
- Add regression tests before or alongside bug fixes.
- Cover success, failure, edge, timeout, retry, and cancellation behavior where
  relevant.
- Reuse established fixtures instead of creating duplicate setup logic.

## Validation

Use the commands declared by the repository. Prefer these when configured:

- `ruff format --check .`
- `ruff check .`
- `mypy .` or `pyright`
- `pytest`
- `python -m build`
