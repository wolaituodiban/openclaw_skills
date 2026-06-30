# 05 — Dev plan: `local-image-gen`

Linear ordering of modules. The rule: a module's source code + tests are both complete and reviewed before the next module starts. The progress record in `memory/dev-doc-progress/local-image-gen.md` mirrors this plan's structure; updates to this file are mirrored there at every state transition. See `references/progress-tracking.md` for the record schema.

**Conformance notes:**

*v1 amend, 2026-07-01T01:14, owner python-coding-rules audit:* Test framework column added; mcp_server tests use `unittest` (per `python-coding-rules` §8), not `pytest`. The 05 v0 row above had no test-framework column and the mcp_server tests would have shipped with `pytest` per the 04 v0 spec, which violated §8. 03 and 04 have been amended to v1 to comply.

*v2 amend, 2026-07-01T01:34, owner restructure:* `mcp_server` 04-test-design was further amended from v2 → v3 (owner direction at 2026-07-01T01:25: "mcp_server tests go under `unit/mcp_server/`"). v3 is layout-only: 1 unit test file → 6 test files + 1 mixins module. Test count, test names, spec content unchanged. §1 / §2 / §3 below updated to reflect the v3 layout. Outstanding R2 FAIL (§3.3 Edge bucket = 2 tests, ≥3 required) is tracked in §4 risks and deferred to a follow-up 04 v4 amend.

## 1. Modules in implementation order

| # | Module | Depends on | Recursive sub-tree? | Doc status | Test framework | Estimated complexity |
|---|--------|-----------|---------------------|------------|----------------|----------------------|
| 1 | `local_image_gen.cache_resolver` | — | no | 03 ✓ PASS / 04 ✓ PASS | `unittest` (per `python-coding-rules` §8) | S |
| 2 | `local_image_gen.mcp_server` | module 1 (the public `walk_levels` + `resolve` surface) | no | 03 v1 R1 PASS / 04 v3 (layout amend; R3 pending) | `unittest` + `unittest.IsolatedAsyncioTestCase` (per `python-coding-rules` §8) | M |

`cache_resolver` goes first because (a) it is a pure leaf module per `02-architecture.md` §3.2 (no dependencies on other modules, std-lib only), and (b) `mcp_server.start_service` calls `cache_resolver.walk_levels()` for the lightweight existence pre-check and `cache_resolver.resolve()` for the model→path lookup per `02-architecture.md` §3.1. Without module 1 done and reviewed, module 2 cannot be tested for the cache-source contract.

`mcp_server` goes second because it is the integration module — it combines `cache_resolver` (module 1) with a vllm-omni subprocess (`subprocess.Popen` + CLI args + ready-poll) and a FastMCP tool surface (6 tools: `start_service`, `invoke_model`, `release_service`, `list_local_models`, `list_running_services`, `release_all_services`). All 6 tool definitions are in `02-architecture.md` §3.1; the integration surface is the largest piece of work in the POC.

The test framework is **`unittest` (stdlib only)** for both modules, per `python-coding-rules` §8. The 04 v0 spec used `pytest` + `pytest-asyncio` + `freezegun`; this was wrong and amended to `unittest` + `unittest.IsolatedAsyncioTestCase` + `unittest.mock` + `tempfile` + `unittest.mock.patch` for time control. No third-party test dependencies are added.

## 2. Per-module exit criteria

A module is "done" only when **all** of the following are true:

- [ ] All source files named in `02-architecture.md §5` exist for this module.
- [ ] All unit tests in the module's `04-test-design.md §3` pass.
- [ ] All integration tests in `04-test-design.md §4` that involve this module pass.
- [ ] Coverage targets in `04-test-design.md §5` are met.
- [ ] Sub-agent review of code + tests: PASS.
- [ ] Human review of code + tests: PASS.

**Module 1 (`cache_resolver`) exit criteria** — source: `local_image_gen/cache_resolver.py`; tests: `local_image_gen/tests/unit/test_cache_resolver.py`. 156 lines of 04-test-design covers 30+ test cases (5 `CacheLevel` + 11 `resolve` + 14 `walk_levels` + 11 internal helpers). Coverage targets: ≥ 95 % line, ≥ 90 % branch, 100 % public-function, 100 % internal-helper.

**Module 2 (`mcp_server`) exit criteria** — source: `local_image_gen/mcp_server.py`; tests: `local_image_gen/tests/unit/mcp_server/` (unit, per v3 layout) + `local_image_gen/tests/integration/test_mcp_server.py` (integration via FastMCP stdio JSON-RPC). Coverage targets: ≥ 95 % line, ≥ 90 % branch, 100 % public-tool coverage. Unit test tree per `04-test-design.md §2`:

```
tests/unit/mcp_server/
├── _mixins.py                       ← shared _MockPopenMixin
├── test_list_local_models.py        ← §3.1 (14 tests)
├── test_start_service.py            ← §3.2 (20 tests)
├── test_list_running_services.py    ← §3.3 (10 tests)
├── test_invoke_model.py             ← §3.4 (30 tests)
├── test_release_service.py          ← §3.5 (11 tests)
└── test_helpers.py                  ← §4.1–§4.11 (43 tests)
```

One `unittest.TestCase` / `unittest.IsolatedAsyncioTestCase` class per public tool (5 classes, all inheriting `_MockPopenMixin` from `_mixins.py`) + 11 helper test classes in `test_helpers.py`. No `pytest` in `requirements.txt` / `pyproject.toml`.

## 3. Per-module review log

Append entries as they happen. Format: `<artifact> | sub-agent: PASS <ts> | human: PASS <ts>`.

### Module 1 — `local_image_gen.cache_resolver`

- `local_image_gen/cache_resolver.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/test_cache_resolver.py` | sub-agent: PASS <ts> | human: PASS <ts>

### Module 2 — `local_image_gen.mcp_server`

- `local_image_gen/mcp_server.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/_mixins.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/test_list_local_models.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/test_start_service.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/test_list_running_services.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/test_invoke_model.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/test_release_service.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/unit/mcp_server/test_helpers.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `local_image_gen/tests/integration/test_mcp_server.py` | sub-agent: PASS <ts> | human: PASS <ts>

## 4. Risks to the plan

| Risk | Mitigation |
|------|------------|
| Module 1 (`cache_resolver`) spec interface in 02 §3.2 turns out wrong for module 2 (e.g. `resolve` needs a different return shape, or `walk_levels` needs to also return L5) | acceptable — module 2 review gate surfaces the gap, fix module 1 first, re-run module 1 review, then continue module 2 |
| Module 2 (`mcp_server`) integration test reveals a vllm-omni readiness-poll timeout mismatch (cold-start > 30 s default) | acceptable — bump `start_service(timeoutMs=...)` default to observed cold-start time (per 01-requirements.md §8 cold-start POC calibration); re-approve FR-3 default timeout in 01-requirements; re-run module 2 review |
| Q1 / Q2 / Q3 / Q4 in `03-design.md §8` are left Open at module 1 review time | acceptable — 04 §8 marks the corresponding tests `xfail(strict=True)`; resolution happens at human Gate 2 for module 1, before module 2 starts |
| `python3-devel` missing in WSL env (blocks POC end-to-end image generation per memory/dev-doc-progress/2026-06-30) | acceptable for module 1 (no vllm-omni dependency); blocks module 2 integration test until `sudo dnf install python3-devel` is run by owner — not the agent's call |
| `01-requirements.md` NFR-4 log field list (added in 2026-06-30 trim) is not yet reflected in module 2 source structure | acceptable — module 2 source must wire up the per-event log fields exactly as enumerated; if a field is impractical to emit, module 2 review surface surfaces the gap before module 2 is declared done |
| 03 / 04 v0 had `python-coding-rules` violations: 03 §3.1 "Raises" sections said "I/O errors caught and treated as no service" (§5 violation — exceptions should propagate to the FastMCP framework boundary), and 04 §2 "Test layout" specified `pytest + pytest-asyncio` (§8 violation — only `unittest` is allowed) | mitigated — 03 v1 and 04 v1 amend: §3.1 / §3.2 / §3.3 / §3.4 / §3.5 "Raises" sections now name the concrete exception classes that propagate; §2 "Test layout" is now `unittest` + `IsolatedAsyncioTestCase` + `tempfile` + `unittest.mock.patch` for time control. The 04 R1 review (which was in flight when the audit fired) will need to be re-run against v1 to confirm the amend is complete. |
| 04 §3.3 `list_running_services` Edge bucket has only 2 tests (R1 v0 MAJOR: ≥3 required). Open at 04 v3 sign-off | deferred — 04 v3 amend (2026-07-01T01:25) was layout-only, did not address the bucket-size gap. A 04 v4 amend will add the 3rd Edge test (candidate: in-memory cache `status: "loading"` returns `"loading"` branch, since `status: "ready"` is already covered). Owner to confirm whether to fold v4 into R3 review or take R3 as-is and address the gap separately. |
| 04 v3 restructure (1 unit file → 6 test files + 1 mixins module) could mis-split tests if the per-tool boundary drawn in 04 §2 turns out wrong (e.g. `invoke_model` and `list_running_services` share enough mock setup that splitting them causes duplication rather than reduction) | acceptable — if duplication surfaces during module 2 implementation, revisit 04 §2 layout and amend v4+; the per-tool split is a convention, not a hard constraint. The shared `_MockPopenMixin` in `_mixins.py` is the primary deduplication mechanism. |

## 5. Done criteria for the whole project

When the last module is approved, what final checks run before declaring the project complete:

- [ ] Full test suite green (`python -m unittest discover -v` from `local_image_gen/`).
- [ ] No open `Open questions` in any 01–04 doc (or all are explicitly deferred with owner sign-off — Q1-Q4 in 03 §8 + 04 §8 fall in this category and are explicitly deferred pending owner Gate 2).
- [ ] Integration smoke test against `01-requirements.md` acceptance criteria: end-to-end `start_service` → `invoke_model` → `release_service` against a real vllm-omni subprocess with a real on-disk model, returning one base64-encoded image. Requires `python3-devel` installed + a real vllm-omni venv.
- [ ] README.md exists with one-paragraph usage and one curl example.
- [ ] `dev-doc/01-requirements.md` → `04-test-design.md` are all marked as "Gate 2 PASS" in `review-log.md` for their final revisions.
- [ ] Human sign-off.

## 6. Notes on the dev-doc-driven convention

- Per `dev-doc-driven` skill rule #1: **no code before the full doc chain (01-05) is approved for the relevant module**. Module 1 code is blocked on 03 + 04 PASS for `cache_resolver`; module 2 code is blocked on 03 + 04 PASS for `mcp_server` (the `mcp_server` 03 + 04 do not exist yet — they will be written before module 2 starts, NOT before module 1).
- Per rule #2: every artifact (01, 02, 03, 04, 05) gets two reviews in order: sub-agent → human. The 03 + 04 for `mcp_server` will follow the same sub-agent R1 → R2 pattern that `cache_resolver` just walked (sub-agent catches schema + spec divergences; human reviews the PASS).
- Per rule #8: progress is mirrored to `memory/dev-doc-progress/local-image-gen.md` at every state transition. This 05 is the source of truth; the memory file is the change log.
- Per `python-coding-rules` §8: **all tests use `unittest`** (stdlib only). The 04 v0 spec used `pytest`; 04 v1 amend uses `unittest` + `unittest.IsolatedAsyncioTestCase` + `unittest.mock`. The 05 Done criteria calls `python -m unittest discover`, not `pytest`.
- Per `python-coding-rules` §5: **no `try` blocks except at recognized boundaries** (FastMCP framework's request handler, `_release_subprocess` for the timeout-signal → kill action, `_poll_ready` for the retry loop's per-iteration HTTP-error catch). The 03 v0 spec had "Raises: does not raise under normal operation. I/O errors on `service.json` read are caught and treated as 'no service running'" — that text is wrong and amended in 03 v1 to enumerate the concrete exception classes that propagate to the FastMCP framework boundary.
