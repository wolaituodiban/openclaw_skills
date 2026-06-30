# 03 — Module design: `local_image_gen.mcp_server`

Paired 1:1 with `04-test-design.md`. Mirrors the structure of `assets/examples/03-module-design.md` (8 §-headings; per-function shape: Purpose / Parameters / Returns / Raises / Behavior / Called by). All wire formats, CLI args, env vars, error codes, and 5-level chain integration are locked in `02-architecture.md` §3.1 — this design mirrors that contract and adds only the implementation-shape detail needed for code review.

**Conformance notes (v2 amend, 2026-07-01T05:21):**

- **v2 amend reason:** FATAL DESIGN DEFECT discovered post-merge (see `review-log.md` 2026-07-01T05:15). v1 spec'd `start_service` as a **synchronous blocking** call (`spawn → poll /v1/models until ready → write service.json → return`). vLLM warmup takes 2–3 minutes; MCP SDK hardcodes `DEFAULT_REQUEST_TIMEOUT_MSEC = 60000` (60s) for all tool calls; OpenClaw does not pass a custom timeout. Result: `start_service` always timed out at 60s, the vllm process started but `service.json` was never written, `invoke_model` failed with `no_running_service`, the skill could not be used end-to-end. v2 redesigns `start_service` as **non-blocking** (spawn → write `service.json` with `status: "loading"` → return immediately) with a **background thread** polling `/v1/models` and updating `service.json["status"]` to `"ready"`. `invoke_model` rejects calls while status is `"loading"`. `list_running_services` reads status from the file (not an in-memory cache). The `_readiness_cache` in-memory state is removed; status is always read from `service.json`.
- **No bearer-token authentication.** Per owner decision 2026-06-30 (security audit finding: token did not protect against any realistic threat model), bearer-token generation, `--api-key`, and the `bearer_token` field in `service.json` are **removed**. The vllm-omni subprocess is bound to `127.0.0.1` only; no remote access. The `LOCAL_IMAGE_GEN_BEARER_TOKEN` env var is removed.
- Per `python-coding-rules` §5 (no try blocks), this module **does not** wrap calls in `try` / `except` for "graceful degradation". Exceptions in `_read_service_json`, `_prune_stale_service_json`, the `cache_resolver` walk, and `_background_poll_ready` HTTP polling **propagate** to the calling FastMCP framework. The FastMCP framework's request-handler is the recognized boundary (§5: "Catch only at the boundary where the error can be turned into a user-facing action or a typed return value"), not this module's tool functions.
- Per `python-coding-rules` §8 (unittest only), paired 04-test-design uses `unittest` + `unittest.IsolatedAsyncioTestCase` + `tempfile` (not `pytest` / `pytest-asyncio`).

## 1. Scope

The `mcp_server` module exposes the 5 MCP tools (`list_local_models`, `start_service`, `list_running_services`, `invoke_model`, `release_service`) over stdio JSON-RPC. It is the only module that talks to vllm-omni (over HTTP via the `openai.OpenAI` sync client) and to the on-disk state directory (`${LOCAL_IMAGE_GEN_STATE_DIR}/service.json`). It depends on `local_image_gen.cache_resolver` for the 5-level chain walk (pre-spawn existence check + L1-L5 resolution inside `start_service`).

This design covers: (a) the 5 tool functions; (b) the 12 internal helpers (state-dir I/O, port-picking, subprocess management, **background readiness polling**, multipart construction, file persistence, **poll-thread registry**); (c) the **9 module-level constants** (timeouts, file names, **status enum values**); (d) startup and shutdown (stdio lifecycle). It does **not** cover the `cache_resolver` interface (see `cache_resolver/03-design.md`); it does **not** cover the model-server CLI args (those are part of vllm-omni's own interface, not this module's design).

## 2. Files

```
local_image_gen/
├── __init__.py
└── mcp_server.py              ← this module (single file, ~500 lines)

tests/
├── unit/
│   └── mcp_server/              ← per-tool unit tests; subprocess + HTTP mocked
│       ├── _mixins.py
│       ├── test_list_local_models.py
│       ├── test_start_service.py
│       ├── test_list_running_services.py
│       ├── test_invoke_model.py
│       ├── test_release_service.py
│       └── test_helpers.py
└── integration/
    └── test_mcp_server.py ← stdio JSON-RPC end-to-end (subprocess stubbed)
```

Module is a single file because (a) all 5 tools share the 3 internal helpers (`_read_service_json`, `_write_service_json`, `_prune_stale_service_json`) and threading them through a package would require relative imports for no benefit at v2's scale; (b) stdio JSON-RPC server loop and the 5 tool functions are conceptually one unit; (c) the gateway imports the 5 tools by name from `local_image_gen.mcp_server` and the import surface is the union of those 5 names.

## 3. Public classes or functions

The module's public surface is the 5 MCP tool functions (the only names the FastMCP `add_tool` decorators export). There is **no public class**. Each tool is a top-level `async def` (FastMCP's stdio server is async; the underlying vllm-omni HTTP calls are sync via `openai.OpenAI` sync client and are awaited via `asyncio.to_thread`).

### 3.1 `list_local_models() -> list[dict]`

**Purpose.** Enumerate models visible on disk in the 5-level cache lookup chain and report which of them are currently loaded / loading into a vllm-omni subprocess.

**Parameters.** None. The function reads env vars (`HF_HOME` / `HUGGINGFACE_HUB_CACHE` / `MODELSCOPE_CACHE` / `HOME`) and the fixed `service.json` path; both are resolved at call time.

**Returns.** `list[dict]` where each dict has keys `model: str` and `current_load_status: str ∈ {"not_loaded", "loading", "loaded"}`. Empty list if no models are visible on disk in any of the 5 levels. Single-service invariant ⇒ at most one entry has `current_load_status ∈ {"loading", "loaded"}`.

**Raises.**
- `OSError` — if `_read_service_json` fails to read `service.json` (permission, I/O error, stale NFS handle). The FastMCP framework's request handler is the boundary (§5) that converts this to a `vllm_error` typed return.
- `json.JSONDecodeError` — if `service.json` exists but is malformed JSON. Same boundary handling.
- `cache_resolver.CacheResolverError` (or whatever concrete exception the sibling module raises; see `cache_resolver/03-design.md §3.2`) — if all 5 cache-level walks fail. The FastMCP framework converts to a `vllm_error` typed return.

**Behavior.**
1. Call `cache_resolver.walk_levels()` to get the L1-L4 `CacheLevel` list (L5 is per-call and not used here).
2. For each `CacheLevel`, call `level.snapshot_for("<dir>")` to enumerate visible models. The directory scan walks `<root>/` for `models--<org>--<repo>/` (HF layout) or `models/<org>/<repo>/` (MS layout) subdirectories.
3. Read `service.json` via `_read_service_json()`. **If the file is absent, treat as "no service running"** (return value: not-found is not an exception; it is a successful return of `None`). **If the file is present but unreadable or malformed, the helper's exception propagates** (per §5; see Raises).
4. If a `service.json` record was read, check that its PID is alive via `os.kill(pid, 0)`. **If `ProcessLookupError` or `PermissionError` is raised, the PID is dead — call `_prune_stale_service_json()` to remove the file and continue with no service running.** (PID-alive check failures on a service-file record are not "errors to propagate" — they are routine stale-state cleanup. The deletion is a write, so it does not need try-wrapping: `_prune_stale_service_json` uses `os.remove` after the `os.kill` check, and the `os.remove` itself is wrapped in its own helper that lets `OSError` propagate to the boundary.)
5. For each visible model, set `current_load_status`: if the model matches `service.json["model"]` and `service.json["status"] == "loading"`, return `"loading"`; if `service.json["status"] == "ready"`, return `"loaded"`; else `"not_loaded"`.
6. Return the list, sorted by `model` (lexicographic).

**Called by.** FastMCP stdio server (one tool definition).

### 3.2 `start_service(model: str, cache_dir: Optional[str] = None, timeoutMs: Optional[int] = None) -> dict` — **NON-BLOCKING**

**Purpose.** Resolve `model` to an on-disk snapshot via the 5-level cache chain, spawn vllm-omni as a subprocess pointed at that snapshot, write `service.json` with `status: "loading"`, and **return immediately**. A **background daemon thread** polls `/v1/models` and updates `service.json["status"]` to `"ready"` on success. Holds the single-service invariant: if a service is already running, fails fast with `service_already_running` and surfaces the existing service's `model`.

**Why non-blocking.** vLLM model warmup takes 2–3 minutes. MCP SDK hardcodes `DEFAULT_REQUEST_TIMEOUT_MSEC = 60000` (60s) for tool calls; OpenClaw does not override this. A blocking `start_service` would always time out, leaving the vllm process running but `service.json` never written — a state where `invoke_model` cannot find the service. The non-blocking design moves the wait out of the MCP call boundary and into a daemon thread, satisfying the 60s constraint while still surfacing readiness status to the caller via `list_running_services`.

**Parameters.**
- `model: str` — required. HuggingFace-style repo id (`<org>/<repo>`).
- `cache_dir: Optional[str]` — default `None`. When supplied, the resolver appends an L5 `CacheLevel` to the walk.
- `timeoutMs: Optional[int]` — default `None`. When supplied and `> 0`, overrides the hardcoded 120 s poll timeout **for the background thread** (not the MCP call). The MCP call itself returns within milliseconds.

**Returns.** `dict` with keys `{model, pid, port, status: "loading"}` on success, or `dict` with key `{error: {code, message}}` on failure. Error codes: `service_already_running`, `model_not_found`, `subprocess_launch_failed`. (No `start_timeout` error — the timeout is now an asynchronous background concern; callers poll `list_running_services` to learn when status flips to `"ready"`.)

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_prune_stale_service_json` / `_write_service_json` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `subprocess.SubprocessError` — if `Popen` itself raises (file-not-found on the vllm binary, etc.). The framework converts to `subprocess_launch_failed` typed return.
- `cache_resolver.CacheResolverError` — if the resolver raises on L1-L5 walk failure. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Read `service.json` via `_read_service_json()`. If it exists, check PID alive via `os.kill(pid, 0)`. If PID alive, return `service_already_running` with the existing `model` (this is a domain check, not an exception path). If PID dead, call `_prune_stale_service_json()` (raises on disk error; framework handles).
2. Call `cache_resolver.resolve(model, cache_dir=cache_dir)` to get the `CacheLevel` or `None`.
3. If `None`, return `model_not_found` (the pre-spawn existence check).
4. Pick a free port via `_pick_free_port()`.
5. Build the CLI args list: `["vllm", "serve", absolute_path, "--omni", "--port", str(port), "--host", "127.0.0.1"]` (no `shell=True`, no `--api-key` — see Conformance notes).
6. Launch via `_spawn_vllm_omni(args)` (which calls `subprocess.Popen(args, stdout=sys.stderr, stderr=subprocess.STDOUT, start_new_session=True)`). Capture the PID from `proc.pid`.
7. **Immediately** write `service.json` atomically via `_write_service_json(...)` with `status: "loading"`, `model`, `pid`, `port`, `cache_source`, `model_path`, `started_at`. **This is the only place that writes `status: "loading"`.**
8. **Start the background poll thread** via `_background_poll_ready(port, pid, timeout_s)`. The thread is a `threading.Thread(daemon=True)`, registered in the module-level `_poll_threads: dict[int, threading.Thread]` keyed by PID. The thread polls `GET http://127.0.0.1:{port}/v1/models` every `READY_POLL_INTERVAL_S`. On 200, it reads `service.json`, sets `status: "ready"`, writes back, and exits. On `time.monotonic() > deadline_s`, it reads `service.json`, sets `status: "failed"`, writes back, **kills the subprocess** via `_release_subprocess(pid)`, removes `service.json`, and exits. On unexpected exception, it sets `status: "failed"`, writes back, and exits (the process may be left running for post-mortem; the operator can call `release_service`).
9. **Return immediately** with `{"model", "pid", "port", "status": "loading"}`. The MCP call typically completes in <100 ms.

**Called by.** FastMCP stdio server (one tool definition). Callers should follow up with `list_running_services` to learn when the service is ready.

### 3.3 `list_running_services() -> list[dict]`

**Purpose.** Return 0 or 1 entries describing the currently-running vllm-omni service. Single-service invariant ⇒ at most 1 entry. Prunes stale `service.json` before responding. The `status` field is read directly from `service.json` (no in-memory cache).

**Parameters.** None.

**Returns.** `list[dict]` with each dict having keys `{model, pid, port, started_at, status}`. `status ∈ {"loading", "ready", "failed"}`. Empty list if no service is running or if `service.json` is pruned as stale.

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_prune_stale_service_json` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `json.JSONDecodeError` — if `service.json` is malformed. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Read `service.json` via `_read_service_json()`. If `None` (file absent), return `[]`. **If exception, propagate to framework** (per §5).
2. If PID not alive (`os.kill(pid, 0)` raises `ProcessLookupError` or `PermissionError`), call `_prune_stale_service_json()` to remove the file and return `[]`. (This also cleans up any stale poll-thread entry; the thread will exit on its next poll attempt when it sees the file gone.)
3. The single-service invariant guarantees at most 1 entry. Return `[{...}]` with the file contents including the `status` field read from the file (default `"ready"` if the field is missing — preserves backward-compat with files written by older versions that did not track status).
4. Return the list.

**Called by.** FastMCP stdio server (one tool definition).

### 3.4 `invoke_model(prompt: str, filename: str, model: Optional[str] = None, image: Optional[str] = None, images: Optional[list[str]] = None, size: Optional[str] = None, outputFormat: str = "png", count: int = 1, negative_prompt: Optional[str] = None, num_inference_steps: Optional[int] = None, guidance_scale: Optional[float] = None, true_cfg_scale: Optional[float] = None, seed: Optional[int] = None, timeoutMs: Optional[int] = None) -> dict`

**Purpose.** Forward an image-generation or image-edit request to the running vllm-omni service, decode the returned base64 image(s), and persist them to disk at `filename` (with `<stem>-N.<ext>` for `count>1`). Returns the path(s) and b64_json string(s) per the v12.3-v12.5 contract. **Rejects the call if the service is still loading** (returns `service_loading` error so the caller knows to retry). 14 args total; `prompt` + `filename` are required positionals; the other 12 are keyword-with-default.

**Parameters.** 14 (see signature above). Argument semantics locked in `02-architecture.md` §3.1; this design does not re-document the wire-level behavior.

**Returns.** `dict` with keys `{path: str | list[str], b64_json: str | list[str], ...}` on success, or `dict` with key `{error: {code, message}}` on failure. Error codes: `no_running_service`, `service_loading`, `model_not_loaded`, `filename_dir_not_found`, `media_dir_unwritable`, `filename_conflict`, `validation_error`, `vllm_error` (with vllm-omni's `error` body in the message verbatim).

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_decode_and_persist` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `openai.OpenAIError` (and subclasses `BadRequestError`, `APIConnectionError`, `APITimeoutError`, etc.) — if the vllm-omni HTTP call fails. The framework converts to `vllm_error` typed return with the vllm-omni `error` body verbatim.
- `base64.binascii.Error` — if vllm-omni returns a malformed `b64_json` string. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Validate `prompt` is non-empty (else `validation_error`).
2. Validate `Path(filename).parent` exists (else `filename_dir_not_found`).
3. For `count>1`, compute target paths `<stem>-1.<ext>` … `<stem>-N.<ext>`; check all targets do not yet exist (else `filename_conflict`).
4. Read `service.json` via `_read_service_json()`. **If `None` (file absent), return `no_running_service`**. **If exception, propagate**.
5. **Check `service.json["status"]`. If `"loading"`, return `service_loading`** with a message instructing the caller to wait and retry. If `"failed"`, return `no_running_service` (the background thread already killed the subprocess and removed the file in the timeout case; if the file still exists with `status: "failed"`, the subprocess is left for post-mortem and the operator should call `release_service`).
6. Check PID alive; if dead, call `_prune_stale_service_json()` and return `no_running_service` (PID-alive check failures on a service-file record are routine stale-state cleanup, not exception propagation).
7. If `model` is supplied and does not match `service.json["model"]`, return `model_not_loaded`.
8. Read `port` from `service.json`.
9. Build an `openai.OpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key="EMPTY")` client (sync; per-call, not persisted). The `api_key` is a placeholder — the server does not require auth (see Conformance notes).
10. Route: if `image is not None or images is not None`, call `_route_invoke(..., as_edit=True)` which builds a multipart body and POSTs to `/v1/images/edits`; else call `_route_invoke(..., as_edit=False)` which POSTs a JSON body to `/v1/images/generations`.
11. Convert `timeoutMs` to seconds; pass as the `timeout` kwarg to the `openai` client call. If omitted, default 120 s.
12. The vllm-omni call returns a response with one or more `b64_json` strings. Call `_decode_and_persist(b64_strings, target_paths, output_format)` to base64-decode each and write to disk.
13. Build the success return: `path` is `filename` (string) when `count=1`, else `list[str]` of length `count`; `b64_json` mirrors the same shape.

**Called by.** FastMCP stdio server (one tool definition).

### 3.5 `release_service(model: str) -> dict`

**Purpose.** Stop the running vllm-omni subprocess, remove `service.json`, and return the released service's identity. Idempotent: if `service.json` is absent or its PID is dead, prunes the file and returns success. **Also clears the poll-thread registry entry** to prevent late writes to a removed `service.json`.

**Parameters.**
- `model: str` — required. The MCP server verifies the running service's `model` field matches; mismatch returns `model_not_loaded`.

**Returns.** `dict` with keys `{released: true, model, pid, port}` on success, or `dict` with key `{error: {code, message}}` on failure. Error codes: `no_running_service`, `model_not_loaded`. No `service_id` field (v12.1).

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_prune_stale_service_json` / `os.remove` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `json.JSONDecodeError` — if `service.json` is malformed. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Read `service.json` via `_read_service_json()`. If `None` (file absent), return `no_running_service`. **If exception, propagate**.
2. If PID dead (`os.kill(pid, 0)` raises `ProcessLookupError` / `PermissionError`), call `_prune_stale_service_json()` to remove the file, pop the poll-thread entry, and return `no_running_service` (idempotent — agent can call release on a dead service without seeing an error per Q2).
3. If `service.json["model"]` does not match the argument, return `model_not_loaded`.
4. **Pop the poll-thread entry from `_poll_threads`** (the thread is a daemon; even if it's still running, it will exit on its own when the file is gone). Use `_poll_threads.pop(pid, None)`.
5. Call `_release_subprocess(pid)` (SIGTERM, wait `RELEASE_GRACE_S`, SIGKILL). **`_release_subprocess` does not catch — `subprocess.TimeoutExpired` from `proc.wait()` propagates; this function's caller (the FastMCP framework or `release_service` itself) catches the timeout signal and proceeds to `proc.kill()`.** This is a single boundary catch at the orchestration level (§5: "the boundary is the only place a `try` is acceptable").
6. Remove `service.json` via `os.remove` (the helper's wrapper). The helper lets `OSError` propagate.
7. Return `{released: True, model, pid, port}`.

**Called by.** FastMCP stdio server (one tool definition).

## 4. Internal helpers

- `_validate_state_dir() -> pathlib.Path` — resolves `${LOCAL_IMAGE_GEN_STATE_DIR}` (default `~/.local-image-gen/state/`), runs `mkdir(parents=True, exist_ok=True)`, returns the absolute path. Called once at module import time and once at startup. Returns the same path on every call. Lets `OSError` propagate.
- `_pick_free_port(host: str = "127.0.0.1") -> int` — opens a TCP socket, `bind((host, 0))`, reads `getsockname()[1]`, closes the socket. Returns the port number. Used by `start_service` to pick a port before spawning vllm-omni (which does not accept `--port 0`). Uses `with socket.socket(...) as s:` per §9.
- `_spawn_vllm_omni(args: list[str]) -> subprocess.Popen` — calls `subprocess.Popen(args, stdout=sys.stderr, stderr=subprocess.STDOUT, start_new_session=True)`. Returns the Popen object. stdout/stderr are unified to the MCP server's stderr; stdout is reserved for JSON-RPC. Lets `OSError` / `FileNotFoundError` propagate.
- **`_background_poll_ready(port: int, pid: int, timeout_s: float) -> None`** — **the readiness poll, now a daemon-thread target function, not awaited directly**. Polls `GET http://127.0.0.1:{port}/v1/models` every `READY_POLL_INTERVAL_S` until 200 or `time.monotonic() > timeout_s`. The function **mutates `service.json` directly** (reads it, sets `status`, writes back via `_write_service_json`):
  - On 200-ready: read `service.json`, set `status: "ready"`, write back, return.
  - On timeout: read `service.json`, set `status: "failed"`, write back, call `_release_subprocess(pid)`, `os.remove` the file, return.
  - On unexpected exception (e.g. `OSError` on file I/O): log to stderr, set `status: "failed"`, write back (best-effort), return. The subprocess is left for post-mortem; the operator can call `release_service`.
  - HTTP transient errors during the poll are **not** raised — they are "not yet ready" signals; the function continues to the next iteration. This is the same retry-loop semantics as the old `_poll_ready`, but in a thread context. The function itself is called once per `start_service` invocation; the daemon thread it runs in is registered in `_poll_threads[pid]`.
  - **This function does not catch `httpx.HTTPError` or `ConnectionError`** at the loop body — per §5, retries use a `while` loop with a `time.sleep(READY_POLL_INTERVAL_S)` between attempts, and any exception in the HTTP call is treated as "not yet ready" by virtue of being inside the retry loop's `while` condition. The `try` is **not** added to the HTTP call — instead, the call is wrapped in a helper `_probe_v1_models(port) -> bool` that returns `False` on any exception and `True` only on 200. This helper is the only place a `try` exists, and it is the boundary that converts a transient network error into a "not ready" signal (a typed return value) — exactly the pattern §5 endorses.
- `_read_service_json() -> Optional[dict]` — reads `${STATE_DIR}/service.json` if it exists; returns the parsed dict or `None`. Lets `OSError` / `PermissionError` / `json.JSONDecodeError` propagate (§5).
- `_write_service_json(contents: dict) -> None` — writes `service.json` atomically via `with tempfile.NamedTemporaryFile(mode='w', dir=state_dir, delete=False) as f:` + `f.write(...)` + `f.flush()` + `os.replace(f.name, service_path)` (§9 — uses `with` for the temp file). Lets `OSError` propagate. **Used in three call sites now: `start_service` (initial write with `status: "loading"`), `_background_poll_ready` (status update), `release_service` (no — release deletes, not writes).**
- `_prune_stale_service_json() -> None` — reads `service.json`; if its PID is not alive (`os.kill(pid, 0)` raises `ProcessLookupError` / `PermissionError`), calls `os.remove(service_path)` via the helper `_remove_service_json_file()` (which lets `OSError` propagate). Used by `list_local_models`, `start_service`, `list_running_services`, and `release_service`.
- `_release_subprocess(pid: int) -> None` — opens `/proc/<pid>` or uses `psutil.Process(pid)` (whichever is available; psutil preferred for cross-platform) to get a handle, sends `proc.terminate()` (SIGTERM), waits up to `RELEASE_GRACE_S`, and on `subprocess.TimeoutExpired` sends `proc.kill()` (SIGKILL). The single `try` in this function is at the boundary (§5): it catches `subprocess.TimeoutExpired` to convert the timeout signal into a kill action. Does not remove `service.json`; that is the caller's responsibility.
- `_route_invoke(client: openai.OpenAI, prompt: str, model: str, as_edit: bool, image: Optional[str], images: Optional[list[str]], size: Optional[str], outputFormat: str, count: int, negative_prompt: Optional[str], num_inference_steps: Optional[int], guidance_scale: Optional[float], true_cfg_scale: Optional[float], seed: Optional[int], timeout_s: float) -> list[str]` — switches between `client.images.generate(...)` (JSON body) and `client.images.edit(...)` (multipart) based on `as_edit`. Returns a list of b64_json strings of length `count`. For edits, the local file paths in `image` / `images` are converted to base64 data URLs and passed as `image` / `image[]` per the POC-confirmed vllm-omni field names. Lets `openai.OpenAIError` and `OSError` propagate.
- `_build_edit_multipart(...)` — constructs the multipart body for `/v1/images/edits`. Uses `openai.OpenAI`'s `images.edit` helper for the multipart envelope (POC-verified at vllm-omni 0.22.0) and passes vllm-omni-specific field names via the client call's kwargs. (If the `openai` Python client does not expose `image[]` array semantics, this helper falls back to a hand-rolled `httpx` POST; that fallback is gated on a runtime check at first call, not at import time — see 02 §6 Tech Stack for the rationale.)
- `_decode_and_persist(b64_strings: list[str], target_paths: list[pathlib.Path], output_format: str) -> None` — base64-decodes each string, writes the bytes to the corresponding `target_path` via `with open(target_path, "wb") as f:` (§9). `output_format` controls the file extension (sanity check — extension is already on `target_path`). Lets `OSError` / `base64.binascii.Error` propagate.
- **`_probe_v1_models(port: int) -> bool`** — synchronous, single-shot HTTP probe of `GET http://127.0.0.1:{port}/v1/models`. Returns `True` on 200, `False` on any other status code or any exception. The only `try` in this helper catches `Exception` at the boundary (§5) to convert transient network errors into a "not ready" typed return. Used by `_background_poll_ready` in its retry loop.

**Module-level state:**

- `_poll_threads: dict[int, threading.Thread] = {}` — registry mapping PID → daemon poll thread. Populated by `start_service`; cleared by `release_service`. The thread itself is a daemon and will exit on its own when `service.json` is removed; the registry entry is for cleanup accounting, not thread lifecycle control.

## 5. State and data flow

State is on disk in `${LOCAL_IMAGE_GEN_STATE_DIR}/service.json`. The MCP server holds **no in-process state across tool calls** (other than the daemon-thread registry `_poll_threads`, which is for cleanup accounting). The 5-level cache lookup chain is recomputed at each `start_service` call; the chain is **not** cached across calls because env vars may change between calls (e.g. operator sets `HF_HOME` between two `start_service` invocations). Per FR-8 single-service invariant, the file holds at most one record; the module does not implement any locking (per 02 §3.1, vllm-omni's single-worker uvicorn queues requests FIFO at the server).

**`service.json` schema (v2):**

```json
{
  "model": "Tongyi-MAI/Z-Image-Turbo",
  "pid": 12345,
  "port": 4711,
  "started_at": 1751325600.123,
  "status": "loading",
  "cache_source": "hf_env",
  "model_path": "/hf_cache/models--Tongyi-MAI--Z-Image-Turbo/snapshots/abc123"
}
```

`status ∈ {"loading", "ready", "failed"}`. The file is **always** present while a service is being managed; absence means "no service running". The `bearer_token` field is removed in v2 (no auth).

**Startup sequence (stdio lifecycle, FR-9):**
1. `import local_image_gen.mcp_server` — module body calls `_validate_state_dir()` (one-shot).
2. FastMCP framework registers the 5 tools via `server.add_tool(...)` calls.
3. Server enters the stdio read loop on `sys.stdin`, dispatching each line as a JSON-RPC request to the matching tool function.

**Shutdown sequence (stdio lifecycle, FR-9):**
1. Gateway closes `sys.stdin` (stdin EOF).
2. FastMCP framework stops accepting new tool calls (in-flight calls complete).
3. The framework's shutdown hook reads `service.json`; if a service is running, calls `_release_subprocess(pid)` (SIGTERM, wait `RELEASE_GRACE_S`, SIGKILL), pops the poll-thread entry, removes `service.json`. If the service was in `"loading"`, the vllm process is still in the middle of model load — the kill is unavoidable to satisfy the shutdown grace.
4. Process exits 0 if shutdown completes within `SHUTDOWN_GRACE_S = 30`. On hard timeout, SIGKILL on vllm-omni and exit non-zero.

Data flow for a typical `start_service` → `invoke_model`:
1. `start_service` reads `service.json` (state on disk), checks PID alive.
2. `start_service` calls `cache_resolver.resolve` to find the on-disk snapshot.
3. `start_service` calls `_pick_free_port` to find a free port.
4. `start_service` calls `_spawn_vllm_omni` to launch the subprocess.
5. `start_service` calls `_write_service_json({...status: "loading"...})`.
6. `start_service` starts the background poll thread (registered in `_poll_threads`).
7. `start_service` returns the loading dict to the MCP caller (typically <100 ms).
8. **Caller polls `list_running_services`** to learn when status flips to `"ready"`.
9. `invoke_model` reads `service.json`, checks `status`, calls `openai.OpenAI` sync client → vllm-omni over HTTP.
10. vllm-omni returns b64_json response.
11. `invoke_model` calls `_decode_and_persist` to write files to disk.
12. `invoke_model` returns the success dict (path + b64_json + vllm-omni usage metadata).

## 6. Dependencies

External libraries (imported at module top):
- `asyncio` (stdlib) — `asyncio.to_thread` for awaiting sync `openai` calls.
- `base64` (stdlib) — b64_json decode.
- `json` (stdlib) — `service.json` read/write.
- `os` (stdlib) — `os.kill`, `os.replace`, `os.remove`, env-var reads.
- `pathlib` (stdlib) — `Path` for `filename` validation.
- `socket` (stdlib) — port-picking.
- `subprocess` (stdlib) — `Popen` for vllm-omni.
- `sys` (stdlib) — `sys.stderr` for unified log capture.
- `tempfile` (stdlib) — `NamedTemporaryFile` for atomic `service.json` write.
- `threading` (stdlib) — `Thread` for the background readiness poll.
- `time` (stdlib) — `time.monotonic` for readiness-poll deadline, `time.sleep` for poll interval.
- `typing` (stdlib) — `Optional`.
- `mcp` (third-party, FastMCP) — `@server.add_tool` decorators, `stdio` server loop.
- `openai` (third-party) — `openai.OpenAI` sync client.
- `httpx` (third-party, **transitive via `openai`**) — imported only if the `images.edit` helper cannot express `image[]` array semantics and a hand-rolled multipart fallback is required (gated on runtime check). Also used by `_probe_v1_models` for the direct HTTP probe in the background poll.
- `psutil` (third-party, optional) — preferred over `/proc/<pid>` for the cross-platform process handle in `_release_subprocess`. Falls back to a `subprocess.Popen` shim if not installed (logged at module-import time).

Module-internal:
- `local_image_gen.cache_resolver` — `walk_levels` and `resolve` are the only functions imported from this module. (The cache_resolver module's own exception types are not re-raised; this module just lets them propagate per §5.)

Test dependencies (per `python-coding-rules` §8 — `unittest` only, no pytest):
- `unittest` (stdlib) — `TestCase` + `IsolatedAsyncioTestCase` for sync + async test bodies.
- `unittest.mock` (stdlib) — `MagicMock` / `AsyncMock` / `patch` for `subprocess.Popen`, `openai.OpenAI`, and **`threading.Thread`** patches.
- `tempfile` (stdlib) — `TemporaryDirectory` context manager in `setUp` / `tearDown` (§9).
- `time` (stdlib) — `time.monotonic` patches via `unittest.mock.patch`.
- `pathlib` (stdlib) — `Path` for test paths.
- `os` (stdlib) — `os.environ` patches via `unittest.mock.patch.dict`.
- `typing` (stdlib) — `Optional`, `Any` for type hints in test code.
- **No pytest. No pytest-asyncio. No freezegun.** The freezegun-equivalent is `unittest.mock.patch('local_image_gen.mcp_server.time.monotonic', return_value=<fixed>)`.

## 7. Configuration

| Constant | Value | Source | Used by |
|----------|-------|--------|---------|
| `DEFAULT_START_TIMEOUT_S` | `120` | 02 §3.1 (v11 owner decision 2026-06-30T21:32) | `_background_poll_ready` (timeout for the background thread) |
| `DEFAULT_INVOKE_TIMEOUT_S` | `120` | 02 §3.1 | `invoke_model` |
| `RELEASE_GRACE_S` | `10` | 02 §3.1 | `release_service`, stdio-EOF shutdown |
| `SHUTDOWN_GRACE_S` | `30` | 02 §3.1 | stdio-EOF shutdown |
| `READY_POLL_INTERVAL_S` | `1.0` | 02 §3.1 | `_background_poll_ready` |
| `SERVICE_FILE_NAME` | `"service.json"` | 02 §3.1 (v12.1 — no `service_id`) | all I/O helpers |
| `STATUS_LOADING` | `"loading"` | v2 amend (this doc) | `service.json["status"]` |
| `STATUS_READY` | `"ready"` | v2 amend (this doc) | `service.json["status"]` |
| `STATUS_FAILED` | `"failed"` | v2 amend (this doc) | `service.json["status"]` (set by background poll on timeout / error) |
| `DEFAULT_STATE_DIR` | `"~/.local-image-gen/state/"` | 02 §3.1 (env-var default) | `_validate_state_dir` |

**Removed in v2:**

- `BEARER_TOKEN_BYTES` — removed. No bearer-token generation in v2 (see Conformance notes).
- `LOCAL_IMAGE_GEN_BEARER_TOKEN` env var — removed. No token to read.

Env vars read at module-import time:
- `LOCAL_IMAGE_GEN_STATE_DIR` — if set, overrides the default state directory; if unset, `${HOME}/.local-image-gen/state/`.

## 8. Open questions

- **Q1.** (Resolved at v2.) Whether `_route_invoke` for edits needs the `httpx` hand-rolled multipart fallback or whether the `openai` Python client's `images.edit` helper handles `image[]` natively. POC gate is deferred to E2E validation. The helper is in place; the fallback path is gated on a runtime check at first call.
- **Q2.** (Resolved at v2.) `release_service` returns `no_running_service` when the service is already gone (idempotent). Documented in §3.5.
- **Q3.** (Resolved at v2.) `list_running_services` returns 1 entry with `status: "loading"` / `"ready"` / `"failed"` from `service.json`. No in-progress stopping state is tracked because `_release_subprocess` is synchronous-blocking and the file is removed before the tool call returns. (Resolves the "what if release is in flight" question with "the file is gone, so we return 0 entries".)
- **Q4.** (Unchanged.) `invoke_model` does not pre-validate `size` against a per-model allow-list. Forwards verbatim; vllm-omni returns 4xx for unsupported sizes. Defer to E2E POC.
- **Q5.** (Unchanged.) `outputFormat` is not re-encoded; `_decode_and_persist` writes the bytes as-is. POC E2E test must verify vllm-omni honors `output_format`. If not, `_decode_and_persist` needs a re-encode step.
- **Q6.** (Unchanged.) `true_cfg_scale` is forwarded verbatim. POC verification.
- **Q7 (new in v2).** Whether the background poll thread should be observable by the operator (e.g. log lines on each transition, or a `_last_poll_at` field in `service.json`). Current design is silent — only status transitions trigger a write. Operator sees status only when they call `list_running_services`. This is acceptable; the daemon thread's stderr log lines (if logging is enabled at module level) are the only runtime signal.
- **Q8 (new in v2).** What happens to a `start_service` call if the operator calls it again while status is `"loading"`? Current design: the second call sees `service.json` with a live PID, returns `service_already_running` with the existing model. This is correct (single-service invariant) but the operator has no way to cancel a stuck `"loading"` service other than `release_service`. If the operator wants a "force-restart" semantic, that is a separate tool (not in v2).
- **Q9 (new in v2).** Whether the MCP 60s hard timeout should be documented in user-facing SKILL.md. **Yes — this is a known constraint** that affects all callers. The skill's SKILL.md must call this out so callers know to expect fast `start_service` returns and follow up with `list_running_services` for status. (Documented in the SKILL.md `invoke_model` section; this doc acknowledges it as a protocol-level fact.)

## 9. Style and tooling

- Per `python-coding-rules`:
  - `@typeguard.typechecked` on all public functions and internal helpers.
  - `pathlib.Path` for filesystem paths; no `os.path.join`.
  - `with` statement for all file handles, sockets, and temp files.
  - No `try` / `except` blocks except at the recognized boundary (FastMCP request handler, or the single boundary catches in `_release_subprocess` and `_probe_v1_models`).
  - `dataclass(frozen=True)` for value types; no plain dicts for structured records.
  - `jsonschema` for validating `service.json` against a schema (the schema is in `local_image_gen/schemas/service_v2.json`).
  - `unittest` + `unittest.IsolatedAsyncioTestCase` for tests; no pytest.
- Per `skill-creator` (referenced in `dev-doc/00-meta.md`): no `try` / `except` in skill surface code; `@typeguard.typechecked` everywhere; `dataclass(frozen=True)` for records.

## 10. Versioning

- **v1 (2026-07-01T01:14):** Initial spec; synchronous blocking `start_service`; bearer-token auth; `_readiness_cache` in-memory state. **Superseded by v2.**
- **v2 (2026-07-01T05:21):** **FATAL DESIGN DEFECT amend.** Non-blocking `start_service` with background poll thread; status moved to `service.json`; bearer-token auth removed; `_probe_v1_models` boundary helper; `_poll_threads` registry; new `STATUS_LOADING` / `STATUS_READY` / `STATUS_FAILED` constants; `service_loading` error code on `invoke_model`; new §9 Style and tooling section; new Q7/Q8/Q9 in §8 Open questions.
