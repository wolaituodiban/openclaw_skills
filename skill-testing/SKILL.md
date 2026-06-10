---
name: skill-testing
description: "Skill testing convention for OpenClaw skills that ship scripts. Triggers on: writing a tests/ directory, adding unit tests, adding integration tests, deciding unit vs integration split, naming test files to match script modules, asserting every return and raise branch of a function with exact value checks, asserting every CLI / multi-script output. Defines the tests/{unit,integration}/ layout, the basename-aligned naming rule, and the branch-and-output coverage rules."
---

# skill-testing

Minimal, language-agnostic convention for the `tests/` directory of an OpenClaw skill.

## Directory layout

```
<skill>/
├── SKILL.md
├── scripts/                 # production code, one file per module
│   ├── foo.<ext>
│   └── bar.<ext>
└── tests/
    ├── unit/                # one test file per script, basename-aligned
    │   ├── foo.<test-ext>
    │   └── bar.<test-ext>
    └── integration/         # one test file per flow
        └── <flow-name>.<test-ext>
```

**Naming rule**: the test file's basename (without extension) must equal the script file's basename. The extension follows the target language's test convention (e.g. `foo.test.js` / `foo_test.go` / `test_foo.py`). One script ↔ one unit test file, no abbreviations, no skipping.

## Unit tests — `tests/unit/`

Purpose: test **a single function** in isolation.

Rules:

1. One test file per script module. One test case per function in that module.
2. For each function, cover **every `return` branch** and **every error branch** (raise / throw / Result::Err / etc). No branch skipped, no branch approximated.
3. For every `return` value, assert the **exact value** with the framework's value-equality assertion (`assertEqual` / `assert.equal` / `t.Equal` / etc). No truthy checks, no presence checks, no partial matches. **逐值覆盖，不重不漏。**
4. For every error branch, assert both the error **type/class** and the error **message** matches the expectation. Use the framework's exception assertion with a message-match argument.
5. Do not mock the function under test. External boundaries (network, fs, clock, env) may be stubbed at the call site if needed, never inside the function itself.

## Integration tests — `tests/integration/`

Purpose: test a **script's CLI / entry point** and **multi-script / multi-skill cooperation** end-to-end.

Rules:

1. One test file per flow. Name describes the flow, not the module: `cli_smoke.<ext>`, `foo_bar_pipeline.<ext>`.
2. Drive the script through its real entry point as a separate process / binary / HTTP call. No in-process shortcut that bypasses the public CLI / `main` / handler.
3. **断言脚本的所有最终输出无误** — every value the script writes to its observable outputs (stdout, stderr, exit code, response body, result file, network reply) must be asserted exactly. If the script emits 3 lines on stdout, assert 3 lines and their exact contents. No "looks plausible", no regex fuzz, no spot-checks.
4. For multi-script flows, run the full pipeline in one test and assert the final output of the **last** step. Intermediate steps may be asserted too, but the last step is mandatory.
5. Mark integration tests so they can be skipped in CI when external deps are missing. Convention: an env-gated skip in the test entry / `conftest` / setup file when the env var `RUN_INTEGRATION_TESTS` is unset.

## Test runner

```
<test-runner> tests/unit/                              # fast, default in CI
RUN_INTEGRATION_TESTS=1 <test-runner>                 # everything
```

Add a tiny setup file (`conftest.py` / `setup.ts` / `setup_test.go` / etc) at the skill root only if the integration skip gate needs custom code. Keep it minimal.
