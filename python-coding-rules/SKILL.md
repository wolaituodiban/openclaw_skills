---
name: python-coding-rules
description: "Python coding rules for all agent-authored code: typeguard runtime checks, no union types without owner approval, dataclass over dict, jsonschema for external dicts, no try blocks, no nested loops, four-function split (input/output/compute/orchestration), CLI convention, unittest with setUp/tearDown, prefer with. Triggers on: writing or reviewing a Python function, class, dataclass, CLI script, or test file."
---

# python-coding-rules

Static-typing discipline for Python code that any OpenClaw agent reads or writes. Treat Python like a language that requires declared types. Code is structured as small single-purpose functions composed by orchestration, with failures exposed (not caught) and clear debug information.

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

## 5. Exceptions: no try blocks, expose errors with debug info

- Do not wrap calls in `try` / `except` to "handle" errors. Let the exception propagate. The calling code (or the orchestration function) is responsible for knowing what to do — and if it does not, that is a real bug, not something to silently catch.
- Catch only at the boundary where the error can be turned into a user-facing action or a typed return value. Internal code lets exceptions propagate. The boundary is the only place a `try` is acceptable.
- When raising or re-raising, include debug information that lets the agent (or human) figure out which argument was wrong and how to fix it. The exception message must contain:
  - the function name and the bad value,
  - the constraint that was violated,
  - a pointer to the argument's expected format (a usage example, a docstring line, or a CLI `--help` snippet).
- Prefer a built-in exception type whose semantic matches the failure. If a function calls into another module, raise the underlying exception (or re-raise with `raise ... from err`) rather than wrap it in a new class. Do not invent a new exception class to translate an existing one.
- Define a new exception class only when no built-in type can carry the debug information. In that case, the new class subclasses the closest built-in (usually `ValueError`).

## 6. No nested loops; four-function split (input / output / compute / orchestration)

- A function must not contain a nested `for` or `while` loop. If a loop is needed inside another loop, split the inner loop into its own function and call it. Orchestration functions may contain flat `for` loops to fan out calls, but the body of the loop must be a single function call, not a block of logic.
- Every function does exactly one of four jobs:
  - **input** — reads an external source (file, network, stdin, env) and returns a typed value. Has no compute. No nested loops.
  - **output** — writes a typed value to an external sink. No compute. No nested loops.
  - **compute** — pure transformation on its inputs. Reads no external sources, writes no external sinks. May contain loops, but no nested loops.
  - **orchestration** — calls input, compute, output functions in order, possibly looping over a collection of items, possibly branching on results. The orchestration function does not itself open files, hit the network, or compute values. Its body is calls to other functions and the control flow that glues them together.
- The four categories compose: an orchestration function may call another orchestration function. A compute function may call another compute function. An input function does not call an output function and vice versa.
- Naming convention: prefix the function name with its category when the role is not obvious from the module layout (`read_config`, `compute_hash`, `write_report`, `run_pipeline`). Within a single-purpose module, the role is implied and the prefix may be omitted.
- **Trivial-output exemption.** A `print(...)` call (including `print(..., file=sys.stderr)` and bare `print(text)` for status / logging / listing values) is a single-sink call with no transformation. It may be inlined in the orchestration function — do not wrap it in a named output helper. The same rule applies to a flat `for` loop whose body is a single `print`, e.g. `for url in urls: print(url)`. Wrap in a named output function only when the output does more than emit a value: format conversion, encoding, retry, repeated fan-out with shared structure, or anything that would otherwise duplicate code. The same exemption does **not** extend to file writes, network responses, or any sink where the call site would need its own error handling.

## 7. CLI script structure

A script that exposes a CLI follows this layout:

```python
"""One-line description of what the script does.

Usage example:
    python -m scripts.foo --input path/to/x --output path/to/y
"""

import argparse
from typing import NoReturn


def foo(input_path: str, output_path: str) -> None:
    """All script logic lives in a function with the same name as the script."""
    data = _read_input(input_path)
    result = _compute(data)
    _write_output(result, output_path)


def main() -> NoReturn:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to the input file (JSON payload).")
    parser.add_argument("--output", required=True, help="Path to write the computed result to.")
    args = parser.parse_args()
    foo(args.input, args.output)


if __name__ == "__main__":
    main()
```

Rules:

- The module-level docstring at the top of the script is exactly one line describing the function, followed by a `Usage example:` block. The docstring is passed to `argparse.ArgumentParser(description=__doc__)`, so what you write there is what the user sees in `--help`.
- All file reading, computation, and file writing live in a function whose name matches the script's basename (a script `foo.py` defines `def foo(...)`). This function takes parsed values as parameters; it does not see `argparse.Namespace` and does not call `parse_args()`.
- `main()` contains the argparse setup, the `parse_args()` call, and exactly one call to the script-named function with the parsed values. No other logic, no try/except, no print.
- Every `add_argument` call must include a `help=` string that names the value, its format, and what the function does with it. The help text is the user's first read of the contract; it should be specific enough to act on without reading the script body.
- Helpers are private (underscore-prefixed) when the script is the only caller. The script-named function is the only public call surface besides `main()`.

## 8. Unittest convention

- All tests use the `unittest` standard library module. Do not introduce `pytest`, `nose`, or other test frameworks.
- Use the unittest lifecycle methods. `setUp` / `tearDown` run around every test method. `setUpClass` / `tearDownClass` run once for the whole class — use them for shared resources that are expensive to create.
- Use `tempfile` to create temporary files and directories in `setUp` / `setUpClass`. Store the path on `self` and clean it up in `tearDown` / `tearDownClass` (e.g. `shutil.rmtree(self.tmpdir)`). Do not leak temp files.
- Every test method asserts the exact expected return value. Use `assertEqual` / `assertRaisesRegex` / etc.

## 9. Use `with` for cleanup

- When a construct supports the context-manager protocol (`with` block), use it. This applies to file handles, locks, sockets, database connections, temporary directory managers, and any other resource that exposes `__enter__` / `__exit__`.
- This is a universal rule: prefer `with` over manual `try` / `finally` cleanup patterns. Combined with §5 (no `try`), `with` is the only acceptable way to scope a resource.

  ```python
  with tempfile.TemporaryDirectory() as tmpdir:
      path = Path(tmpdir) / "data.json"
      data = read_json(path)
      ...
  ```

- Do not use `with` for objects whose context-manager protocol does nothing useful (a `with` around a plain `dict` or `int` is noise; trust the type hint instead).

## Review checklist

Before approving a Python change, the agent confirms:

- [ ] Every function and class has type hints on signature and attributes.
- [ ] The module is covered by `typeguard` (or `@typechecked` on every public function).
- [ ] No `Union` / `|` in any type hint except `Optional`/`None`, and no `Optional` added without a clear absent-vs-empty distinction.
- [ ] No new `dict` for data with knowable keys; existing `dict` payloads at external boundaries are validated with `jsonschema` and converted to a dataclass.
- [ ] No `try` / `except` blocks inside the module except at a recognized boundary (CLI entry, network handler). Every raised exception carries the function name, the bad value, the violated constraint, and a usage pointer.
- [ ] No function contains a nested `for` or `while` loop. Every function belongs to one of the four categories (input, output, compute, orchestration) and does only that one job.
- [ ] CLI scripts follow §7: module-level docstring, script-named function, `main()` is exactly one line.
- [ ] Tests use `unittest` only. `setUp` / `tearDown` / `setUpClass` / `tearDownClass` are used as appropriate. `tempfile` resources are created in setup and removed in teardown.
- [ ] Resources that support the context-manager protocol are used with `with`.
- [ ] `mypy --strict` (or equivalent) passes for the changed files.
