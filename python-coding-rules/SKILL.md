---
name: python-coding-rules
description: "Python coding rules for all agent-authored code: typeguard runtime checks, no union types without owner approval, dataclass over dict, jsonschema for external dicts. Triggers on: writing or reviewing a Python function, class, dataclass, or JSON boundary."
---

# python-coding-rules

Static-typing discipline for Python code that any OpenClaw agent reads or writes. Treat Python like a language that requires declared types.

## Scope

Applies to every Python file an agent edits, writes, or reviews under user instruction. The agent should self-check against this skill before committing a Python change.

## 1. Type hints + runtime checks

- Every function signature, every class attribute, every public method must have type hints.
- Decorate every module and class with `typeguard` so type hints are enforced at runtime, not just at type-check time.
- Standard usage:

  ```python
  from typeguard import typechecked, TypeCheckError

  @typechecked
  def parse_count(raw: str) -> int:
      return int(raw)
  ```

  Raise `TypeCheckError` for any caller that violates the declared types. Treat it as a programming error, not a recoverable condition.

- Type-check the project with `mypy --strict` (or `pyright --strict`) in CI. The agent must not disable strictness on a per-line basis (`# type: ignore` only with an inline comment explaining why, and never in fresh code).

## 2. No union types without owner approval

- Parameters, return types, and attributes must not use `Union[A, B]` / `A | B` unless the owner has explicitly approved that specific union in writing.
- `Optional[X]` / `X | None` is the only allowed "union-like" form, because the absence of a value is a real domain concept, not a type ambiguity.
- When a function would naturally take a union, split it into separate functions (one per type) or force the caller to commit to a concrete type at the boundary. Do not invent a union to satisfy the call site.

## 3. Dataclass over dict

- When the set of keys is known at write time, use `@dataclass` with typed fields. Do not use a plain `dict` for internal data.
- Use `__post_init__` to validate field types and value constraints beyond what the type hint can express (range checks, cross-field invariants, normalization).

  ```python
  from dataclasses import dataclass, field

  @dataclass(frozen=True)
  class StatusCounts:
      active: int
      disabled: int

      def __post_init__(self) -> None:
          if self.active < 0 or self.disabled < 0:
              raise ValueError("counts must be non-negative")
  ```

- Prefer `frozen=True` for value objects and for anything that crosses a function boundary. Mutable dataclasses are reserved for objects that own lifecycle state.
- `dict` is allowed only when the keys are not knowable ahead of time (e.g. the contents of a user-supplied JSON document, a CSV column → value map, an external API's free-form response).

## 4. External dicts: jsonschema first, then dataclass

- Code that consumes an external dict (JSON input, HTTP response body, file payload) must validate the payload against a `jsonschema` schema at the boundary, then immediately convert to a typed dataclass before the value leaves the boundary function.
- The boundary function's return type is a dataclass, not a dict. Callers downstream never see the raw dict.
- The `jsonschema` schema is the source of truth for the external contract. The dataclass is the source of truth for the internal model. Keep them in sync; if the schema gains a field, the dataclass gains a field on the same change.

## Review checklist

Before approving a Python change, the agent confirms:

- [ ] Every function and class has type hints on signature and attributes.
- [ ] The module is covered by `typeguard` (or `@typechecked` on every public function).
- [ ] No `Union` / `|` in any type hint except `Optional`/`None`, and no `Optional` added without a clear absent-vs-empty distinction.
- [ ] No new `dict` for data with knowable keys; existing `dict` payloads at external boundaries are validated with `jsonschema` and converted to a dataclass.
- [ ] `mypy --strict` (or equivalent) passes for the changed files.
