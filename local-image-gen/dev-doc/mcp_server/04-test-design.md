# 04 — Test design: `local_image_gen.mcp_server`

Paired 1:1 with `03-design.md`. Mirrors the structure of `assets/examples/04-test-design.md` (8 §-headings; per-public-function test sections with Happy / Error / Edge sub-buckets). All test cases are derived from `03-design.md` §3 Behavior (numbered steps) and `02-architecture.md` §3.1 frozen spec.

**Conformance notes:**

*v1 amend, 2026-07-01T01:14, owner python-coding-rules audit:*
- Per `python-coding-rules` §8 (unittest only), this design uses `unittest` + `unittest.IsolatedAsyncioTestCase` + `tempfile` (not pytest, not pytest-asyncio, not freezegun). The 04 v0 spec text that read "pytest + pytest-asyncio" is **wrong** and amended in v1.
- Per `python-coding-rules` §5 (no try blocks), this design's "Error path" tests assert that the named exception is **raised** (not caught + converted to a partial result). The 04 v0 "Error path" tests for `list_local_models` / `list_running_services` / `invoke_model` that asserted "result is partial / no service" are **wrong** and replaced with `assertRaises` tests in v1.

*v3 amend, 2026-07-01T01:25, owner restructure — split 1 unit test file into 7:*
- 130 tests in one file was too large to be practical (single `test_mcp_server.py` would be ~3000+ lines). Per owner direction, the unit test surface is split into **6 test files + 1 shared mixins module** under `unit/mcp_server/`, keyed by the function under test (one file per public tool, one consolidated file for the 11 internal helpers). The 04 design document itself remains a single artifact (this file); the split is reflected in the §2 directory tree, the §2 test-class → file mapping, and the per-§-heading file-path annotations added in v3.
- `_MockPopenMixin` is hoisted out of any individual test file into `unit/mcp_server/_mixins.py` so the 5 public-function test files can share it. Internal-helper test files (§4.1–§4.11) do not use the mixin.
- Test class / test name / test count per public function and per helper are **unchanged from v2**; v3 is a layout-only amend. (R2 had reported one outstanding R1 v0 MAJOR: §3.3 `list_running_services` Edge bucket has 2 tests where ≥3 is required. That MAJOR is **not** fixed in v3 — owner direction was to restructure first, address the bucket-size gap in a follow-up amend.)

*v4 amend, 2026-07-01T03:11, deferred MAJOR resolution:*
- §3.3 Edge bucket raised from 2 to 3 tests via `test_list_running_services_returns_loading_status_when_poll_pending`. New test covers the `status ∈ {"loading", "ready"}` enum from 03 §3.3 — the cold-cache→ready default only applies when the cache is genuinely cold; an explicit non-ready value (`"loading"`) must pass through unchanged. **No spec-content change.** Total test count: §3.1=14, §3.2=20, §3.3=10 → 11, §3.4=30, §3.5=11, §4.1–§4.11=45 → **131** (+1). All other sections unchanged.

## 1. Scope

Tests cover every public tool function (5) and every internal helper (11) of `local_image_gen.mcp_server`. Subprocess management (`subprocess.Popen`) and HTTP calls (vllm-omni over HTTP via `openai.OpenAI` sync client) are mocked via `unittest.mock.patch` and `unittest.mock.MagicMock` / `AsyncMock`. The `cache_resolver` module is mocked at its import boundary via `unittest.mock.patch`. Stdlib functions (asyncio, base64, json, os, pathlib, secrets, socket, subprocess, sys, tempfile, time) are **not** mocked — they are exercised against the actual Python runtime.

What this design does **not** cover:
- Integration with a real vllm-omni subprocess (covered by `tests/integration/test_mcp_server.py`, gated on the WSL env having `python3-devel` + a real vllm-omni venv per 02 §3.1).
- End-to-end stdio JSON-RPC negotiation (the framework's responsibility, not this module's).
- Cache-resolution internals (covered by `cache_resolver/04-test-design.md`).
- `openai` Python client's internal multipart construction (trusted library code).

## 2. Test layout

Per v3 owner direction, the unit test surface for this module is split **per function under test** and lives under `tests/unit/mcp_server/` (so it can be discovered independently of any other unit-test packages added to the skill later, e.g. `tests/unit/cache_resolver/`). The integration test remains a single file at `tests/integration/test_mcp_server.py`. `unit/mcp_server/` also hosts a shared `_mixins.py` for cross-file test scaffolding.

```
tests/
├── unit/
│   └── mcp_server/                          ← this design's unit tests
│       ├── _mixins.py                       ← shared test scaffolding (MockPopen + helpers)
│       ├── test_list_local_models.py        ← §3.1 (14 tests, class TestListLocalModels)
│       ├── test_start_service.py            ← §3.2 (20 tests, class TestStartService)
│       ├── test_list_running_services.py    ← §3.3 (11 tests, class TestListRunningServices)
│       ├── test_invoke_model.py             ← §3.4 (30 tests, class TestInvokeModel)
│       ├── test_release_service.py          ← §3.5 (11 tests, class TestReleaseService)
│       └── test_helpers.py                  ← §4.1–§4.11 (45 tests, 11 classes)
└── integration/
    └── test_mcp_server.py                   ← stdio JSON-RPC end-to-end (separate design)
```

**Why the split is keyed by function under test (not by test class or by bucket):**

1. **One file per public tool** (`list_local_models` / `start_service` / `list_running_services` / `invoke_model` / `release_service`). Each is the natural seam of the module's public surface; each is the unit a future maintainer reaches for when they break that tool. The 11 internal helpers (§4.1–§4.11) share a single `test_helpers.py` because they are small (3–5 tests each) and individually do not warrant their own file.
2. **`_MockPopenMixin` is hoisted to `unit/mcp_server/_mixins.py`**. The mixin is needed by all 5 public-function test files (each Popen-mocking test for `list_local_models` / `start_service` / `list_running_services` / `invoke_model` / `release_service` reuses the same per-test pid / poll / wait / terminate configuration). Putting it in any one of the 5 test files would force the other 4 to import across test-file boundaries (ugly). Putting it in `test_helpers.py` would conflate Popen infrastructure with helper tests. A dedicated `_mixins.py` is the standard Python test-layout convention for shared scaffolding across an `unittest` discovery tree.
3. **`invoke_model` has 30 tests in one file** — that is the largest single-tool bucket in this design. We keep it in one file (`test_invoke_model.py`) because all 30 tests target the same public function and its 9-arg signature; splitting further (e.g. by generate-vs-edit) would split one public function across two files and make it harder to find tests when the signature changes.

**File-to-class mapping** (replaces the single-file class list in v2):

| File | Class(es) | Tests | Notes |
|---|---|---|---|
| `unit/mcp_server/_mixins.py` | `class _MockPopenMixin` | (scaffolding) | Provides a `setUp` helper that builds a `MockPopen` configured with the per-test pid, exit code, and poll/wait behavior. Reused by all 5 public-function test files. |
| `unit/mcp_server/test_list_local_models.py` | `class TestListLocalModels(_MockPopenMixin, unittest.TestCase)` | 14 (§3.1) | Sync tests. |
| `unit/mcp_server/test_start_service.py` | `class TestStartService(_MockPopenMixin, unittest.IsolatedAsyncioTestCase)` | 20 (§3.2) | Async tests. |
| `unit/mcp_server/test_list_running_services.py` | `class TestListRunningServices(_MockPopenMixin, unittest.TestCase)` | 11 (§3.3) | Sync tests. |
| `unit/mcp_server/test_invoke_model.py` | `class TestInvokeModel(_MockPopenMixin, unittest.IsolatedAsyncioTestCase)` | 30 (§3.4) | Async tests. |
| `unit/mcp_server/test_release_service.py` | `class TestReleaseService(_MockPopenMixin, unittest.TestCase)` | 11 (§3.5) | Sync tests. |
| `unit/mcp_server/test_helpers.py` | `class TestValidateStateDir(unittest.TestCase)` (5) + `class TestPickFreePort(unittest.TestCase)` (4) + `class TestSpawnVllmOmni(unittest.TestCase)` (4) + `class TestPollReady(unittest.TestCase)` (4) + `class TestReadServiceJson(unittest.TestCase)` (4) + `class TestWriteServiceJson(unittest.TestCase)` (4) + `class TestPruneStaleServiceJson(unittest.TestCase)` (4) + `class TestReleaseSubprocess(unittest.TestCase)` (3) + `class TestRouteInvoke(unittest.TestCase)` (5) + `class TestBuildEditMultipart(unittest.TestCase)` (3) + `class TestDecodeAndPersist(unittest.TestCase)` (5) | 45 (§4.1–§4.11) | Sync tests, no Popen mixin. |

**Cross-file test class reuse:** all 5 public-function test classes inherit from `_MockPopenMixin` (`from ._mixins import _MockPopenMixin` at the top of each file). The 11 internal-helper test classes do not.

Module-import-time patching: at the top of each test file, `import local_image_gen.mcp_server as srv` once, then patch `srv.subprocess.Popen`, `srv.openai.OpenAI`, etc. via `unittest.mock.patch` (in `setUp` / `setUpClass`) for each test that needs it. The patching target names do not change between v2 and v3 — only the file the patch is set up in changes.

Test framework: `unittest` (stdlib) + `unittest.IsolatedAsyncioTestCase` (Python 3.8+, async test bodies). Each async test class subclasses `IsolatedAsyncioTestCase`; each test method is `async def test_*(self) -> None` and is run via the framework's async loop. **No pytest. No pytest-asyncio. No freezegun.** Time control uses `unittest.mock.patch('local_image_gen.mcp_server.time.monotonic', return_value=<fixed>)`.

The `MockPopen` configured in `setUp` (in `_mixins.py`) has `.pid`, `.terminate()`, `.kill()`, `.wait()`, and `.poll()` all configured per-test. Tests assert exact expected return values via `assertEqual` / `assertRaisesRegex` / `assertRaises` / `assertIn` (per `python-coding-rules` §8).

Temp files: each test file's `setUp` uses `with tempfile.TemporaryDirectory() as tmpdir:` (per §9) and stores the path on `self.tmpdir`. `tearDown` is implicit (context manager). `service.json` paths in tests are `self.tmpdir / "service.json"`. `filename` in `invoke_model` tests is `self.tmpdir / "out.png"`.

**Discovery:** `python -m unittest discover -s tests/unit/mcp_server` (or `python -m unittest discover -s tests` for both unit and integration). Each test file has a unique `Test*` class; no name collisions across the 7 files.

## 3. Unit tests per public function

### 3.1 `list_local_models() -> list[dict]` → `unit/mcp_server/test_list_local_models.py`

**Happy path.**

- `test_list_local_models_no_models_visible_returns_empty_list` — `cache_resolver.walk_levels()` returns 4 `CacheLevel`s with no `models--*` / `models/<org>/<repo>/` subdirectories; `service.json` absent. Asserts `result == []`.
- `test_list_local_models_hf_layout_enumerates_models` — `self.tmpdir` contains one `models--org--repo/` subdir under the L1 root; `service.json` absent. Asserts result has one entry `{model: "org/repo", current_load_status: "not_loaded"}`.
- `test_list_local_models_ms_layout_enumerates_models` — same as above but `models/<org>/<repo>/` (MS layout).
- `test_list_local_models_service_ready_marks_model_loaded` — one model visible; `service.json` exists with `{model: "org/repo", pid: <alive-pid>, status: "ready"}`. Asserts `current_load_status == "loaded"`.
- `test_list_local_models_service_loading_marks_model_loading` — same as above with `status: "loading"`. Asserts `current_load_status == "loading"`.
- `test_list_local_models_single_service_invariant_holds` — two models visible, one matches `service.json["model"]` and PID alive, other does not. Asserts at most one entry has `current_load_status ∈ {"loading", "loaded"}`.
- `test_list_local_models_results_sorted_by_model` — three models visible in non-sorted order; `service.json` absent. Asserts result is sorted by `model`.

**Error path** (per §5 — exceptions propagate to the FastMCP framework; tests assert the exception is raised, not that it is caught and turned into a partial result).

- `test_list_local_models_raises_oserror_when_service_json_unreadable` — `service.json` exists but `os.open` raises `PermissionError` (mocked via `unittest.mock.patch('local_image_gen.mcp_server.open', side_effect=PermissionError("perm denied"))`). Asserts `self.assertRaises(PermissionError, srv.list_local_models)`.
- `test_list_local_models_raises_jsondecodeerror_when_service_json_malformed` — `service.json` exists with invalid JSON. Asserts `self.assertRaises(json.JSONDecodeError, srv.list_local_models)`.
- `test_list_local_models_raises_cache_resolver_error_when_all_levels_fail` — `cache_resolver.walk_levels()` raises `CacheResolverError`. Asserts `self.assertRaises(CacheResolverError, srv.list_local_models)`.
- `test_list_local_models_prunes_stale_service_json_returns_enumeration` — `service.json` exists with dead PID. Asserts `service.json` is removed and result is the disk enumeration. (Stale-state cleanup is not an exception path; it is the normal flow.)

**Edge path.**

- `test_list_local_models_empty_string_model_field_treated_as_not_loaded` — `service.json` exists with `model: ""` and PID alive. Asserts no entry gets `current_load_status ∈ {"loading", "loaded"}` (empty model name does not match any visible model).
- `test_list_local_models_visibility_dedup_keeps_first_level` — same model visible at L1 and L2; `service.json` absent. Asserts result has one entry (the L1 one wins per 5-level chain first-hit-wins).
- `test_list_local_models_visibility_dedup_keeps_first_level_across_all_5_levels_when_present` — same model visible at L1, L2, L3, L4, and L5 (all 5 levels); `service.json` absent. Asserts result has exactly one entry (the L1 one wins; the L2-L5 duplicates are deduped, not appended).

### 3.2 `start_service(model, cache_dir=None, timeoutMs=None) -> dict` → `unit/mcp_server/test_start_service.py`

**Happy path.**

- `test_start_service_spawns_vllm_omni_with_resolved_path` — `cache_resolver.resolve("org/repo", cache_dir=None)` returns `("/snapshots/org/repo", "hf_env")`. `_poll_ready` returns `True` on first call. Asserts `srv.subprocess.Popen` called with `["vllm", "serve", "/snapshots/org/repo", "--omni", "--port", str(<port>), "--host", "127.0.0.1", "--api-key", <bearer>]` (exact arg list).
- `test_start_service_writes_service_json_atomically` — same as above. Asserts `self.tmpdir / "service.json"` exists with `{model: "org/repo", pid, port, started_at, bearer_token, cache_source: "hf_env", model_path: "/snapshots/org/repo"}` after the call.
- `test_start_service_returns_success_dict` — same. Asserts return value has all 7 expected keys.
- `test_start_service_picks_free_port_via_socket_bind` — patched `_pick_free_port` returns 4711. Asserts the spawned CLI's `--port` argument is `4711`.
- `test_start_service_generates_bearer_token_via_secrets` — patched `secrets.token_urlsafe` returns `"fixed-token-32-bytes-long-xxxxxxxx"`. Asserts the spawned CLI's `--api-key` is the same string and `service.json["bearer_token"]` is the same.
- `test_start_service_timeoutMs_overrides_default` — `timeoutMs=10`. Asserts `_poll_ready` is called with `deadline_s = <start-time> + 10`.
- `test_start_service_no_timeoutMs_uses_default_120` — no override. Asserts `_poll_ready` is called with `deadline_s = <start-time> + 120`.
- `test_start_service_passes_cache_dir_to_resolver` — `cache_dir="/custom/cache"`. Asserts `cache_resolver.resolve("org/repo", cache_dir="/custom/cache")` is called.

**Error path** (per §5 — exception-class returns are explicit `dict` shapes, not raised exceptions; the tests assert the exact return shape).

- `test_start_service_returns_model_not_found_when_resolver_returns_none` — `cache_resolver.resolve` returns `None`. Asserts return value is `{error: {code: "model_not_found", ...}}`, no `Popen` call, no `service.json` write.
- `test_start_service_returns_service_already_running` — `service.json` exists with PID alive. Asserts return value is `{error: {code: "service_already_running", ...}}` and the existing `model` is surfaced in the message.
- `test_start_service_prunes_stale_service_json_then_resolves` — `service.json` exists with dead PID. Asserts `service.json` is removed before `resolve` is called, then the call proceeds normally.
- `test_start_service_returns_subprocess_launch_failed_on_nonzero_exit` — Popen's `.poll()` returns `1` before `_poll_ready` succeeds. Asserts return value is `{error: {code: "subprocess_launch_failed", message: contains "1"}}`.
- `test_start_service_returns_start_timeout_kills_proc` — `_poll_ready` returns `False` (deadline elapsed). Asserts `proc.terminate()` then `proc.kill()` called, return value is `{error: {code: "start_timeout", ...}}`, no `service.json` written.
- `test_start_service_raises_oserror_when_service_json_write_fails` — `_write_service_json` raises `OSError` (mocked via `unittest.mock.patch` on the helper). Asserts `self.assertRaises(OSError, ...)` (the framework converts to `vllm_error`).
- `test_start_service_raises_filenotfounderror_when_vllm_binary_missing` — `srv.subprocess.Popen` raises `FileNotFoundError`. Asserts `self.assertRaises(FileNotFoundError, ...)`.

**Edge path.**

- `test_start_service_with_cache_dir_appends_l5` — `cache_dir="/custom"`. Asserts `cache_resolver.resolve` is called with `cache_dir` argument.
- `test_start_service_stdout_redirected_to_stderr` — Asserts `Popen` is called with `stdout=sys.stderr` and `stderr=subprocess.STDOUT`.
- `test_start_service_start_new_session_true` — Asserts `Popen` is called with `start_new_session=True` (process group leader).
- `test_start_service_poll_returns_immediately_ready` — `_poll_ready` returns `True` on first iteration. Asserts exactly one `_poll_ready` call (no busy-wait after success).
- `test_start_service_poll_timeout_zero_uses_default` — `timeoutMs=0` (treated as "use default" — 02 §3.1 says "When supplied and > 0"). Asserts default 120 s is used.

### 3.3 `list_running_services() -> list[dict]` → `unit/mcp_server/test_list_running_services.py`

**Happy path.**

- `test_list_running_services_returns_empty_when_no_service_file` — `service.json` absent. Asserts return value `[]`.
- `test_list_running_services_returns_one_entry_when_service_running` — `service.json` exists, PID alive, status ready. Asserts return value is `[<one-entry-with-status-ready>]`.
- `test_list_running_services_entry_has_required_keys` — same. Asserts each dict has keys `model, pid, port, started_at, status`.
- `test_list_running_services_single_service_invariant` — only ever 1 entry (no test for >1; invariant).

**Error path** (per §5).

- `test_list_running_services_raises_oserror_when_service_json_unreadable` — `service.json` exists but `os.open` raises `PermissionError`. Asserts `self.assertRaises(PermissionError, srv.list_running_services)`.
- `test_list_running_services_raises_jsondecodeerror_when_service_json_malformed` — `service.json` exists with invalid JSON. Asserts `self.assertRaises(json.JSONDecodeError, srv.list_running_services)`.
- `test_list_running_services_prunes_stale_service_json` — `service.json` exists with dead PID. Asserts file is removed and return value is `[]`. (Stale-state cleanup is not an exception path; the framework's success-path code returns `[]` after pruning.)
- `test_list_running_services_raises_oserror_when_state_dir_unreadable` — the entire state directory has `chmod 000` (or, in a unit test, `os.listdir(state_dir)` is mocked to raise `PermissionError`). Asserts `self.assertRaises(PermissionError, srv.list_running_services)`. (Note: `chmod 000` may not work in CI; the mock-based variant is preferred.)

**Edge path.**

- `test_list_running_services_cold_cache_status_defaults_to_ready` — `service.json` exists, PID alive, in-memory readiness cache cold (the file does not store `status`). Asserts `status == "ready"` (the file was written only after polling succeeded).
- `test_list_running_services_handles_in_memory_status_cache_present` — after a `start_service` call that has just succeeded, an in-memory readiness cache holds `status: "ready"`. Asserts `list_running_services` reads the in-memory cache and returns `status: "ready"` (does not poll `/v1/models` again). (This tests the "cache populated by `start_service`, consumed by `list_running_services`" flow that 03 §5 describes.)
- `test_list_running_services_returns_loading_status_when_poll_pending` — `service.json` exists, PID alive, in-memory readiness cache holds `status: "loading"` (mid-poll, after `start_service` wrote `service.json` but before the `/v1/models` poll returned 200). Asserts the returned entry's `status == "loading"` (not `"ready"`). This covers the `status ∈ {"loading", "ready"}` enum from 03 §3.3 — the cold-cache→ready default only applies when the cache is genuinely cold, not when it has an explicit non-ready value.

### 3.4 `invoke_model(prompt, filename, model=None, image=None, images=None, size=None, outputFormat="png", count=1, negative_prompt=None, num_inference_steps=None, guidance_scale=None, true_cfg_scale=None, seed=None, timeoutMs=None) -> dict` → `unit/mcp_server/test_invoke_model.py`

**Happy path.**

- `test_invoke_model_succeeds_with_required_args_only` — `prompt="a cat"`, `filename=str(self.tmpdir / "out.png")`. Mocked `openai.OpenAI` returns one `b64_json`. Asserts return value has `{path: "out.png", b64_json: "..."}` and the file exists on disk.
- `test_invoke_model_passes_all_kwargs_to_client` — all 14 args supplied. Asserts the mocked `client.images.generate` (or `.edit`) call receives all 14 args verbatim.
- `test_invoke_model_count_one_returns_string_path` — `count=1`. Asserts `path` is a `str`, not a list.
- `test_invoke_model_count_greater_than_one_returns_list_paths` — `count=4`, `filename="out.png"` (relative to `self.tmpdir`). Asserts `path` is a list of 4 strings, files exist at `out-1.png` to `out-4.png` (no zero-padding).
- `test_invoke_model_with_image_routes_to_edit_endpoint` — `image="ref.png"`. Asserts `_route_invoke(..., as_edit=True)` is called and the multipart body contains `image=<encoded>`.
- `test_invoke_model_with_images_routes_to_edit_endpoint` — `images=["a.png", "b.png"]`. Asserts `_route_invoke(..., as_edit=True)` is called with both refs.
- `test_invoke_model_no_image_routes_to_generate_endpoint` — no `image` / `images`. Asserts `_route_invoke(..., as_edit=False)` is called.
- `test_invoke_model_outputFormat_png_persists_png_bytes` — `outputFormat="png"`, mocked response is base64-encoded PNG bytes. Asserts the persisted file's bytes equal the response bytes (no re-encode).
- `test_invoke_model_outputFormat_jpeg_persists_jpeg_bytes` — same with JPEG bytes.
- `test_invoke_model_outputFormat_webp_persists_webp_bytes` — same with WebP bytes.
- `test_invoke_model_timeoutMs_converted_to_seconds` — `timeoutMs=30000`. Asserts the `openai` client call receives `timeout=30.0`.
- `test_invoke_model_no_timeoutMs_uses_default_120` — no override. Asserts `timeout=120.0`.
- `test_invoke_model_reads_bearer_token_from_service_json` — `service.json` has `bearer_token="tkn"`. Asserts the `openai.OpenAI` client is constructed with `api_key="tkn"`.
- `test_invoke_model_reads_port_from_service_json` — `service.json` has `port=9999`. Asserts `base_url="http://127.0.0.1:9999/v1"`.

**Error path** (per §5 — exception-class returns are explicit `dict` shapes; raised exceptions are tested with `assertRaises`).

- `test_invoke_model_empty_prompt_returns_validation_error` — `prompt=""`. Asserts return value `{error: {code: "validation_error", ...}}`, no `openai` client call.
- `test_invoke_model_filename_parent_does_not_exist_returns_filename_dir_not_found` — `filename="/nonexistent/dir/out.png"`. Asserts return value `{error: {code: "filename_dir_not_found", ...}}`.
- `test_invoke_model_filename_conflict_on_count_greater_than_one` — `count=3`, `out-1.png` already exists. Asserts return value `{error: {code: "filename_conflict", ...}}` and no file is written.
- `test_invoke_model_returns_no_running_service_when_file_absent` — `service.json` absent. Asserts return value `{error: {code: "no_running_service", ...}}` (file-absent is a successful return of `None` from `_read_service_json`, not an exception).
- `test_invoke_model_prunes_stale_service_json_returns_no_running_service` — `service.json` exists with dead PID. Asserts file is removed and return value `{error: {code: "no_running_service", ...}}`.
- `test_invoke_model_raises_oserror_when_service_json_unreadable` — `service.json` exists but `os.open` raises `PermissionError`. Asserts `self.assertRaises(PermissionError, ...)`.
- `test_invoke_model_raises_openai_error_on_bad_request` — mocked client raises `openai.BadRequestError`. Asserts `self.assertRaises(openai.BadRequestError, ...)`.
- `test_invoke_model_raises_binascii_error_on_malformed_b64` — vllm-omni returns malformed `b64_json`. Asserts `self.assertRaises(binascii.Error, ...)`.
- `test_invoke_model_model_arg_mismatch_returns_model_not_loaded` — `model="other/repo"`, `service.json["model"]="org/repo"`. Asserts return value `{error: {code: "model_not_loaded", ...}}`.

**Edge path.**

- `test_invoke_model_count_zero_uses_count_one` — `count=0`. Asserts the call still proceeds and returns a single-image response (defensive default; 02 §3.1 says `count: int >= 1`, but the function handles 0 gracefully).
- `test_invoke_model_negative_count_uses_count_one` — `count=-1`. Same.
- `test_invoke_model_size_with_unsupported_value_passes_through` — `size="9999x9999"`. Asserts the call proceeds (no pre-validation per Q4) and the vllm-omni 4xx is surfaced.
- `test_invoke_model_true_cfg_scale_forwarded_verbatim` — `true_cfg_scale=4.0`. Asserts the value reaches the `openai` client call unchanged.
- `test_invoke_model_seed_zero_forwarded_verbatim` — `seed=0`. Asserts the value reaches the client (Python `0` is not `None`).
- `test_invoke_model_explicit_model_arg_matches_service_json` — `model="org/repo"` matches. Asserts no `model_not_loaded` error.
- `test_invoke_model_filename_relative_path_works` — `filename="out.png"` (relative to `self.tmpdir`). Asserts the file is written to `self.tmpdir / "out.png"`.

### 3.5 `release_service(model) -> dict` → `unit/mcp_server/test_release_service.py`

**Happy path.**

- `test_release_service_terminates_subprocess_and_removes_service_json` — `service.json` exists, PID alive, model matches. Asserts `proc.terminate()` called, `service.json` removed, return value `{released: true, model, pid, port}`.
- `test_release_service_graceful_shutdown_via_sigterm_only` — `proc.wait()` returns within `RELEASE_GRACE_S`. Asserts `proc.kill()` not called.
- `test_release_service_force_kill_after_grace_expires` — `proc.wait()` raises `subprocess.TimeoutExpired` after `RELEASE_GRACE_S`. Asserts `proc.terminate()` then `proc.kill()` called.
- `test_release_service_returns_full_identity` — Asserts return value includes `model, pid, port`.

**Error path** (per §5).

- `test_release_service_returns_no_running_service_when_file_absent` — `service.json` absent. Asserts return value `{error: {code: "no_running_service", ...}}`.
- `test_release_service_prunes_stale_service_json_returns_no_running_service` — `service.json` exists with dead PID. Asserts file is removed and return value `{error: {code: "no_running_service", ...}}`.
- `test_release_service_raises_oserror_when_service_json_unreadable` — `service.json` exists but `os.open` raises `PermissionError`. Asserts `self.assertRaises(PermissionError, ...)`.
- `test_release_service_model_mismatch_returns_model_not_loaded` — `model="other/repo"`, `service.json["model"]="org/repo"`. Asserts return value `{error: {code: "model_not_loaded", ...}}` and subprocess not terminated.

**Edge path.**

- `test_release_service_idempotent_on_dead_proc` — `service.json` exists with PID dead. Asserts return value `{error: {code: "no_running_service", ...}}` (idempotent — agent can call release on a dead service without seeing an error, per Q2).
- `test_release_service_pid_alive_but_no_zombie` — PID alive, but proc is in zombie state. Asserts `proc.terminate()` returns immediately, no exception, file removed.
- `test_release_service_returns_full_identity_with_zero_port` — `service.json` has `port: 0` (an edge case where vllm-omni was launched but the port-pick collision avoidance picked an OS-assigned port; the file shows what the OS reported back). Asserts return value includes `port: 0` (verbatim, not "no port" or `None`).

## 4. Internal helpers

**Whitebox closed-form** — internal helpers (`_*`) may be directly imported and called from the test module; this is the canonical exception to the blackbox-only rule for §3. Public functions in §3 are blackbox-tested only. This section tests the **closed-form behavior** of each helper against its declared inputs.

### 4.1 `_validate_state_dir` → `unit/mcp_server/test_helpers.py` (§4.1)

- `test_validate_state_dir_creates_default_dir_when_unset` — unset `LOCAL_IMAGE_GEN_STATE_DIR`. Asserts the directory exists at `~/.local-image-gen/state/` after the call. (Skip if `HOME` is not writable in the test env; use `self.skipTest(reason)`.)
- `test_validate_state_dir_uses_local_image_gen_state_dir_env` — set to `self.tmpdir / "custom"`. Asserts the directory exists at `self.tmpdir / "custom"` after the call.
- `test_validate_state_dir_idempotent_on_existing_dir` — call twice. Asserts no exception on second call.
- `test_validate_state_dir_returns_absolute_path` — Asserts the return value is an absolute `pathlib.Path`.
- `test_validate_state_dir_raises_oserror_on_permission_denied` — patch `os.makedirs` to raise `PermissionError`. Asserts `self.assertRaises(PermissionError, srv._validate_state_dir)`.

### 4.2 `_pick_free_port` → `unit/mcp_server/test_helpers.py` (§4.2)

- `test_pick_free_port_returns_int_in_ephemeral_range` — Asserts return value is an int between 1024 and 65535.
- `test_pick_free_port_returns_distinct_values_across_calls` — Two consecutive calls. Asserts returned values differ (probability of collision is negligible in the ephemeral range).
- `test_pick_free_port_default_host_is_loopback` — Default host. Asserts the socket was bound to `127.0.0.1` (verified by checking the socket's `getsockname()` during the call via a wrapper; OR simply by trusting the default arg).
- `test_pick_free_port_explicit_host` — `host="0.0.0.0"`. Asserts the socket was bound to `0.0.0.0` (same wrapper technique).

### 4.3 `_spawn_vllm_omni` → `unit/mcp_server/test_helpers.py` (§4.3)

- `test_spawn_vllm_omni_returns_popen_with_correct_args` — Asserts `subprocess.Popen` called with `args=<list>, stdout=sys.stderr, stderr=subprocess.STDOUT, start_new_session=True`.
- `test_spawn_vllm_omni_does_not_use_shell` — Asserts `shell=False` (default; verify by inspecting the call kwargs).
- `test_spawn_vllm_omni_returns_popen_object` — Asserts the return value has `.pid`, `.terminate()`, `.kill()`, `.wait()`, `.poll()`.
- `test_spawn_vllm_omni_propagates_filenotfounderror` — Patch `subprocess.Popen` to raise `FileNotFoundError`. Asserts `self.assertRaises(FileNotFoundError, srv._spawn_vllm_omni, [...])`.

### 4.4 `_poll_ready` → `unit/mcp_server/test_helpers.py` (§4.4)

- `test_poll_ready_returns_true_on_first_200` — mocked HTTP GET returns 200 with ready body on first call. Asserts return value `True`.
- `test_poll_ready_returns_false_on_deadline` — mocked HTTP always raises; deadline set to 0.1 s. Asserts return value `False`.
- `test_poll_ready_polls_at_READY_POLL_INTERVAL_S` — mocked HTTP always raises. Spy on the HTTP call count over 0.3 s with `READY_POLL_INTERVAL_S=0.1`. Asserts call count between 2 and 4 (timing tolerance).
- `test_poll_ready_authorization_header_sent` — Asserts the mocked HTTP call receives `Authorization: Bearer <token>` header.

### 4.5 `_read_service_json` → `unit/mcp_server/test_helpers.py` (§4.5)

- `test_read_service_json_returns_none_when_absent` — `service.json` does not exist. Asserts return value `None`.
- `test_read_service_json_returns_parsed_dict_when_present` — `service.json` exists with valid JSON. Asserts return value equals the parsed dict.
- `test_read_service_json_propagates_oserror_on_permission_denied` — `os.open` raises `PermissionError`. Asserts `self.assertRaises(PermissionError, srv._read_service_json)`.
- `test_read_service_json_propagates_jsondecodeerror_on_malformed` — `service.json` exists but is malformed. Asserts `self.assertRaises(json.JSONDecodeError, srv._read_service_json)`.

### 4.6 `_write_service_json` → `unit/mcp_server/test_helpers.py` (§4.6)

- `test_write_service_json_writes_atomically_via_tempfile` — Asserts after the call, `service.json` exists with the expected content and no `.tmp` files are left in the state dir.
- `test_write_service_json_overwrites_existing` — Pre-existing `service.json` with different content. Asserts the file's content is replaced.
- `test_write_service_json_creates_tempfile_in_state_dir` — Asserts the intermediate `NamedTemporaryFile` was created with `dir=<state_dir>` (not in the system default `/tmp`); verified by patching `tempfile.NamedTemporaryFile` and inspecting the kwargs.
- `test_write_service_json_propagates_oserror_on_disk_full` — Patch `tempfile.NamedTemporaryFile` to raise `OSError`. Asserts `self.assertRaises(OSError, srv._write_service_json, {...})`.

### 4.7 `_prune_stale_service_json` → `unit/mcp_server/test_helpers.py` (§4.7)

- `test_prune_stale_service_json_removes_file_when_pid_dead` — `service.json` exists with a PID that is not alive. Asserts file is removed.
- `test_prune_stale_service_json_keeps_file_when_pid_alive` — `service.json` exists with a PID that is alive. Asserts file is unchanged.
- `test_prune_stale_service_json_noop_when_file_absent` — Asserts no exception.
- `test_prune_stale_service_json_propagates_oserror_on_remove_failure` — Patch `os.remove` to raise `PermissionError`. Asserts `self.assertRaises(PermissionError, srv._prune_stale_service_json)`.

### 4.8 `_release_subprocess` → `unit/mcp_server/test_helpers.py` (§4.8)

- `test_release_subprocess_terminates_gracefully` — `proc.wait()` returns within grace. Asserts `proc.terminate()` called, `proc.kill()` not called.
- `test_release_subprocess_kills_after_grace_expires` — `proc.wait()` raises `TimeoutExpired`. Asserts `proc.terminate()` then `proc.kill()` called.
- `test_release_subprocess_does_not_remove_service_json` — Asserts `service.json` is unchanged (caller's responsibility).

### 4.9 `_route_invoke` → `unit/mcp_server/test_helpers.py` (§4.9)

- `test_route_invoke_generate_routes_to_generate_endpoint` — `as_edit=False`. Asserts `client.images.generate` called.
- `test_route_invoke_edit_routes_to_edit_endpoint` — `as_edit=True`. Asserts `client.images.edit` called.
- `test_route_invoke_returns_list_of_b64_json_strings` — Asserts return value is a `list[str]` of length `count`.
- `test_route_invoke_single_image_converts_to_data_url` — `image="/path/to/ref.png"`. Asserts the value passed to the `openai` call is a `data:image/png;base64,...` URL, not a bare path.
- `test_route_invoke_propagates_openai_error` — mocked client raises `openai.BadRequestError`. Asserts `self.assertRaises(openai.BadRequestError, ...)`.

### 4.10 `_build_edit_multipart` → `unit/mcp_server/test_helpers.py` (§4.10)

- `test_build_edit_multipart_constructs_envelope_with_image_field` — Asserts the resulting multipart body has `image` field with the encoded data.
- `test_build_edit_multipart_constructs_envelope_with_image_array` — `images=[a, b]`. Asserts the body has `image[]` field with both refs encoded.
- `test_build_edit_multipart_includes_prompt_and_count` — Asserts `prompt` and `n` are present in the multipart.

### 4.11 `_decode_and_persist` → `unit/mcp_server/test_helpers.py` (§4.11)

- `test_decode_and_persist_decodes_b64_to_bytes` — Asserts persisted file's bytes equal `base64.b64decode(b64_string)`.
- `test_decode_and_persist_writes_to_target_path` — Asserts the file exists at the target path.
- `test_decode_and_persist_handles_count_one` — Single target. Asserts the file is written, no list indexing errors.
- `test_decode_and_persist_handles_count_greater_than_one` — Asserts all N files are written.
- `test_decode_and_persist_propagates_binascii_error_on_malformed_b64` — Asserts `self.assertRaises(binascii.Error, ...)`.

## 5. Coverage targets

- **Line coverage**: ≥ 95 %
- **Branch coverage**: ≥ 90 %
- **Public-function coverage**: 100 % (every branch of every tool exercised)
- **Internal-helper coverage**: 100 % (every helper has ≥ 3 closed-form tests in §4)

The combination of §3 (blackbox public function tests) and §4 (whitebox internal helper tests) is intended to satisfy the 95 % line target without needing integration tests for unit-level coverage.

## 6. Test data

| Resource | Source |
|----------|--------|
| `tempfile.TemporaryDirectory` (stdlib) | `setUp` creates a per-test temp dir; tests use `self.tmpdir` for `service.json` and `filename` paths. Cleanup is implicit (context manager, §9). |
| `unittest.mock.patch` (stdlib) | Patches `srv.subprocess.Popen`, `srv.openai.OpenAI`, `srv.cache_resolver.walk_levels`, `srv.cache_resolver.resolve`, `srv._pick_free_port`, `srv._poll_ready`, `srv.time.monotonic`, `srv.secrets.token_urlsafe`, `srv.os.kill`, `srv.os.makedirs`, `srv.os.remove`, `srv.open`, `srv.tempfile.NamedTemporaryFile`, etc. |
| `unittest.mock.MagicMock` / `AsyncMock` (stdlib) | Mock the `Popen` and `openai.OpenAI` return values and method calls. |
| `unittest.IsolatedAsyncioTestCase` (stdlib) | For async tool tests (`start_service`, `invoke_model`). |
| `self.skipTest(reason)` (unittest) | Skip tests that depend on env state not available in CI (e.g. writable `HOME`). |
| `unittest.mock.patch.dict(os.environ, {...})` | Set / unset env vars for the test. |

No real models, no real vllm-omni subprocess, no real HF / MS network calls.

## 7. What is intentionally not tested

- **Real vllm-omni subprocess**: covered by `tests/integration/test_mcp_server.py`, gated on `python3-devel` + a real vllm-omni venv.
- **Real stdio JSON-RPC negotiation**: covered by integration test.
- **FastMCP framework internals**: trusted library.
- **`openai` Python client internals**: trusted library.
- **Stdlib I/O errors on `Path(filename).parent` permission checks**: `PermissionError` on the parent directory check is not separately tested (covered indirectly by `filename_dir_not_found`).
- **Concurrency** (multiple in-flight tool calls): single-service invariant + uvicorn FIFO queue per FR-8 makes this out-of-scope for v1.
- **Pre-validation of `size` per Q4**: design defers to vllm-omni 4xx; not pre-validated.
- **R2 closure behavior for `start_service` callable form**: not tested (the design fixes the form to a list-of-strings; the closure detail is internal to `_spawn_vllm_omni`).
- **Q5 `outputFormat` re-encoding**: if vllm-omni returns PNG when caller asked for JPEG, design does not re-encode. This is a POC-end-to-end check, not a unit test.

## 8. Open questions

Q1-Q6 from `03-design.md §8` carry through:

- **Q1.** Whether `_route_invoke` for edits needs the `httpx` hand-rolled multipart fallback. Tests in §3.4 / §4.9 / §4.10 use the mocked `openai.OpenAI` directly, so the fallback path is not directly exercised; the test of `_build_edit_multipart` verifies the **fallback envelope** shape. If the fallback is unused at runtime, §4.9 / §4.10 still pass (mocked client). `xfail(strict=True)` markers are **not** needed in Q1 because the tests pass against the mocked client regardless of which path is exercised at runtime.

- **Q2.** Whether `release_service` returns `no_running_service` vs `released: false` for an already-gone service. Tests in §3.5 assert `no_running_service` per the current design. `xfail(strict=True)` is **not** needed; if Q2 is resolved differently, the test is amended in-place at module 2 Gate 2.

- **Q3.** Whether `list_running_services` should report `status: "stopping"` during an in-progress release. Tests in §3.3 assert `status: "ready"` per the current design. No `xfail` needed; same logic as Q2.

- **Q4.** Whether `invoke_model` pre-validates `size`. Test `test_invoke_model_size_with_unsupported_value_passes_through` in §3.4 Edge asserts the current "no pre-validation" behavior. No `xfail` needed; same logic as Q2.

- **Q5.** Whether `_decode_and_persist` re-encodes when vllm-omni returns the wrong format. Tests in §3.4 Happy (`outputFormat_png/jpeg/webp_persists_*_bytes`) assert the bytes pass through unchanged. No `xfail` needed; POC end-to-end test verifies the assumption.

- **Q6.** Whether `true_cfg_scale` is forwarded as the literal field name or maps to a different wire field. Test `test_invoke_model_true_cfg_scale_forwarded_verbatim` in §3.4 Edge asserts verbatim forwarding. No `xfail` needed; POC end-to-end test verifies the wire field.

All 6 open questions are deferred to module 2 Gate 2 per `05-dev-plan.md §4 Risks`. None of the 04 tests require `xfail` markers — every test asserts the **current design's behavior**, and if the owner resolves a question differently at Gate 2, the corresponding test is amended in-place (per the agent's "amend in place + log" pattern from cache_resolver 04).
