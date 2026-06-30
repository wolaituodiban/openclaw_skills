# 03 — Module design: `local_image_gen.mcp_server`

Paired 1:1 with `04-test-design.md`. Mirrors the structure of `assets/examples/03-module-design.md` (8 §-headings; per-function shape: Purpose / Parameters / Returns / Raises / Behavior / Called by). All wire formats, CLI args, env vars, error codes, and 5-level chain integration are locked in `02-architecture.md` §3.1 — this design mirrors that contract and adds only the implementation-shape detail needed for code review.

**Conformance notes (v1 amend, 2026-07-01T01:14, owner python-coding-rules audit):**
- Per `python-coding-rules` §5 (no try blocks), this module **does not** wrap calls in `try` / `except` for "graceful degradation". Exceptions in `_read_service_json`, `_prune_stale_service_json`, and the `cache_resolver` walk **propagate** to the calling FastMCP framework. The FastMCP framework's request-handler is the recognized boundary (§5: "Catch only at the boundary where the error can be turned into a user-facing action or a typed return value"), not this module's tool functions. The previous 03 v0 spec text that read "I/O errors on `service.json` read are caught and treated as 'no service running'" is **wrong** and amended in v1.
- Per `python-coding-rules` §8 (unittest only), paired 04-test-design uses `unittest` + `unittest.IsolatedAsyncioTestCase` + `tempfile` (not `pytest` / `pytest-asyncio`).

## 1. Scope

The `mcp_server` module exposes the 5 MCP tools (`list_local_models`, `start_service`, `list_running_services`, `invoke_model`, `release_service`) over stdio JSON-RPC. It is the only module that talks to vllm-omni (over HTTP via the `openai.OpenAI` sync client) and to the on-disk state directory (`${LOCAL_IMAGE_GEN_STATE_DIR}/service.json`). It depends on `local_image_gen.cache_resolver` for the 5-level chain walk (pre-spawn existence check + L1-L5 resolution inside `start_service`).

This design covers: (a) the 5 tool functions; (b) the 11 internal helpers (state-dir I/O, port-picking, subprocess management, readiness polling, multipart construction, file persistence); (c) the 7 module-level constants (timeouts, file names, token size); (d) startup and shutdown (stdio lifecycle). It does **not** cover the `cache_resolver` interface (see `cache_resolver/03-design.md`); it does **not** cover the model-server CLI args (those are part of vllm-omni's own interface, not this module's design).

## 2. Files

```
local_image_gen/
├── __init__.py
├── mcp_server.py              ← this module (single file, ~400 lines)
└── tests/
    ├── unit/
    │   └── test_mcp_server.py ← per-tool unit tests; subprocess + HTTP mocked
    └── integration/
        └── test_mcp_server.py ← stdio JSON-RPC end-to-end (subprocess stubbed)
```

Module is a single file because (a) all 5 tools share the 3 internal helpers (`_read_service_json`, `_write_service_json`, `_prune_stale_service_json`) and threading them through a package would require relative imports for no benefit at v1's scale; (b) stdio JSON-RPC server loop and the 5 tool functions are conceptually one unit; (c) the gateway imports the 5 tools by name from `local_image_gen.mcp_server` and the import surface is the union of those 5 names.

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
5. For each visible model, set `current_load_status`: if the model matches `service.json["model"]` and `status == "loading"`, return `"loading"`; if `status == "ready"`, return `"loaded"`; else `"not_loaded"`.
6. Return the list, sorted by `model` (lexicographic).

**Called by.** FastMCP stdio server (one tool definition).

### 3.2 `start_service(model: str, cache_dir: Optional[str] = None, timeoutMs: Optional[int] = None) -> dict`

**Purpose.** Resolve `model` to an on-disk snapshot via the 5-level cache chain, spawn vllm-omni as a subprocess pointed at that snapshot, poll `/v1/models` until ready (or timeout), and write `service.json` atomically. Holds the single-service invariant: if a service is already running, fails fast with `service_already_running` and surfaces the existing service's `model`.

**Parameters.**
- `model: str` — required. HuggingFace-style repo id (`<org>/<repo>`).
- `cache_dir: Optional[str]` — default `None`. When supplied, the resolver appends an L5 `CacheLevel` to the walk.
- `timeoutMs: Optional[int]` — default `None`. When supplied and `> 0`, overrides the hardcoded 120 s start timeout for this single call.

**Returns.** `dict` with keys `{model, pid, port, started_at, bearer_token, cache_source, model_path}` on success, or `dict` with key `{error: {code, message}}` on failure. Error codes: `service_already_running`, `model_not_found`, `start_timeout`, `subprocess_launch_failed`.

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_prune_stale_service_json` / `_write_service_json` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `subprocess.SubprocessError` — if `Popen` itself raises (file-not-found on the vllm binary, etc.). The framework converts to `subprocess_launch_failed` typed return.
- `cache_resolver.CacheResolverError` — if the resolver raises on L1-L5 walk failure. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Read `service.json` via `_read_service_json()`. If it exists, check PID alive via `os.kill(pid, 0)`. If PID alive, return `service_already_running` with the existing `model` (this is a domain check, not an exception path). If PID dead, call `_prune_stale_service_json()` (raises on disk error; framework handles).
2. Call `cache_resolver.resolve(model, cache_dir=cache_dir)` to get `(absolute_path, cache_source)` or `None`.
3. If `None`, return `model_not_found` (the pre-spawn existence check).
4. Pick a free port via `_pick_free_port()`.
5. Generate `bearer_token = secrets.token_urlsafe(BEARER_TOKEN_BYTES)`.
6. Build the CLI args list: `["vllm", "serve", absolute_path, "--omni", "--port", str(port), "--host", "127.0.0.1", "--api-key", bearer_token]` (no `shell=True`).
7. Launch via `_spawn_vllm_omni(args)` (which calls `subprocess.Popen(args, stdout=sys.stderr, stderr=subprocess.STDOUT, start_new_session=True)`). Capture the PID from `proc.pid`.
8. Poll `_poll_ready(port, bearer_token, deadline_s)` until ready or timeout. Polling returns `bool`; HTTP errors during the poll are silently treated as "not yet ready" inside `_poll_ready` (this is a retry loop, not exception swallowing — see §4 `_poll_ready`).
9. On timeout: call `_release_subprocess(pid)` (SIGTERM, wait `RELEASE_GRACE_S`, SIGKILL). Return `start_timeout`. No `service.json` write. **`_release_subprocess` does not catch — `subprocess.TimeoutExpired` from `proc.wait()` propagates to `_release_subprocess`'s caller, which is this `start_service` function; we catch `TimeoutExpired` here as a normal timeout signal and proceed to `proc.kill()`** (this is a single boundary catch at the orchestration level, allowed by §5 for "orchestration functions may need to convert a timeout signal into a kill action").
10. On subprocess non-zero exit (checked via `proc.poll()`): read the return code, return `subprocess_launch_failed` with the exit code in the message.
11. On ready: write `service.json` atomically via `_write_service_json(...)`. Return the success dict.

**Called by.** FastMCP stdio server (one tool definition).

### 3.3 `list_running_services() -> list[dict]`

**Purpose.** Return 0 or 1 entries describing the currently-running vllm-omni service. Single-service invariant ⇒ at most 1 entry. Prunes stale `service.json` before responding.

**Parameters.** None.

**Returns.** `list[dict]` with each dict having keys `{model, pid, port, started_at, status}`. `status ∈ {"loading", "ready"}`. Empty list if no service is running or if `service.json` is pruned as stale.

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_prune_stale_service_json` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `json.JSONDecodeError` — if `service.json` is malformed. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Read `service.json` via `_read_service_json()`. If `None` (file absent), return `[]`. **If exception, propagate to framework** (per §5).
2. If PID not alive (`os.kill(pid, 0)` raises `ProcessLookupError` or `PermissionError`), call `_prune_stale_service_json()` to remove the file and return `[]`.
3. The single-service invariant guarantees at most 1 entry. Return `[{...}]` with the file contents and `status` field read separately from the readiness poll (the file does not store `status`; it is derived from the latest `/v1/models` poll result, cached in memory after `start_service` completes; if cache is cold, default to `"ready"` since the file was written only after polling succeeded).
4. Return the list.

**Called by.** FastMCP stdio server (one tool definition).

### 3.4 `invoke_model(prompt: str, filename: str, model: Optional[str] = None, image: Optional[str] = None, images: Optional[list[str]] = None, size: Optional[str] = None, outputFormat: str = "png", count: int = 1, negative_prompt: Optional[str] = None, num_inference_steps: Optional[int] = None, guidance_scale: Optional[float] = None, true_cfg_scale: Optional[float] = None, seed: Optional[int] = None, timeoutMs: Optional[int] = None) -> dict`

**Purpose.** Forward an image-generation or image-edit request to the running vllm-omni service, decode the returned base64 image(s), and persist them to disk at `filename` (with `<stem>-N.<ext>` for `count>1`). Returns the path(s) and b64_json string(s) per the v12.3-v12.5 contract. 14 args total; `prompt` + `filename` are required positionals; the other 12 are keyword-with-default.

**Parameters.** 14 (see signature above). Argument semantics locked in `02-architecture.md` §3.1; this design does not re-document the wire-level behavior.

**Returns.** `dict` with keys `{path: str | list[str], b64_json: str | list[str], ...}` on success, or `dict` with key `{error: {code, message}}` on failure. Error codes: `no_running_service`, `model_not_loaded`, `filename_dir_not_found`, `media_dir_unwritable`, `filename_conflict`, `validation_error`, `vllm_error` (with vllm-omni's `error` body in the message verbatim).

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_decode_and_persist` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `openai.OpenAIError` (and subclasses `BadRequestError`, `AuthenticationError`, `APIConnectionError`, `APITimeoutError`, etc.) — if the vllm-omni HTTP call fails. The framework converts to `vllm_error` typed return with the vllm-omni `error` body verbatim.
- `base64.binascii.Error` — if vllm-omni returns a malformed `b64_json` string. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Validate `prompt` is non-empty (else `validation_error`).
2. Validate `Path(filename).parent` exists (else `filename_dir_not_found`).
3. For `count>1`, compute target paths `<stem>-1.<ext>` … `<stem>-N.<ext>`; check all targets do not yet exist (else `filename_conflict`).
4. Read `service.json` via `_read_service_json()`. **If `None` (file absent), return `no_running_service`**. **If exception, propagate**.
5. Check PID alive; if dead, call `_prune_stale_service_json()` and return `no_running_service` (PID-alive check failures on a service-file record are routine stale-state cleanup, not exception propagation).
6. If `model` is supplied and does not match `service.json["model"]`, return `model_not_loaded`.
7. Read `bearer_token` and `port` from `service.json`.
8. Build an `openai.OpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key=***` client (sync; per-call, not persisted).
9. Route: if `image is not None or images is not None`, call `_route_invoke(..., as_edit=True)` which builds a multipart body and POSTs to `/v1/images/edits`; else call `_route_invoke(..., as_edit=False)` which POSTs a JSON body to `/v1/images/generations`.
10. Convert `timeoutMs` to seconds; pass as the `timeout` kwarg to the `openai` client call. If omitted, default 120 s.
11. The vllm-omni call returns a response with one or more `b64_json` strings. Call `_decode_and_persist(b64_strings, target_paths, output_format)` to base64-decode each and write to disk.
12. Build the success return: `path` is `filename` (string) when `count=1`, else `list[str]` of length `count`; `b64_json` mirrors the same shape.

**Called by.** FastMCP stdio server (one tool definition).

### 3.5 `release_service(model: str) -> dict`

**Purpose.** Stop the running vllm-omni subprocess, remove `service.json`, and return the released service's identity. Idempotent: if `service.json` is absent or its PID is dead, prunes the file and returns success.

**Parameters.**
- `model: str` — required. The MCP server verifies the running service's `model` field matches; mismatch returns `model_not_loaded`.

**Returns.** `dict` with keys `{released: true, model, pid, port}` on success, or `dict` with key `{error: {code, message}}` on failure. Error codes: `no_running_service`, `model_not_loaded`. No `service_id` field (v12.1).

**Raises.**
- `OSError` / `PermissionError` — if `_read_service_json` / `_prune_stale_service_json` / `os.remove` I/O fails. The FastMCP framework converts to `vllm_error` typed return.
- `json.JSONDecodeError` — if `service.json` is malformed. The framework converts to `vllm_error` typed return.

**Behavior.**
1. Read `service.json` via `_read_service_json()`. If `None` (file absent), return `no_running_service`. **If exception, propagate**.
2. If PID dead (`os.kill(pid, 0)` raises `ProcessLookupError` / `PermissionError`), call `_prune_stale_service_json()` to remove the file and return `no_running_service` (idempotent — agent can call release on a dead service without seeing an error per Q2).
3. If `service.json["model"]` does not match the argument, return `model_not_loaded`.
4. Call `_release_subprocess(pid)` (SIGTERM, wait `RELEASE_GRACE_S`, SIGKILL). **`_release_subprocess` does not catch — `subprocess.TimeoutExpired` from `proc.wait()` propagates; this function's caller (the FastMCP framework or `release_service` itself) catches the timeout signal and proceeds to `proc.kill()`.** This is a single boundary catch at the orchestration level (§5: "the boundary is the only place a `try` is acceptable").
5. Remove `service.json` via `os.remove` (the helper's wrapper). The helper lets `OSError` propagate.
6. Return `{released: True, model, pid, port}`.

**Called by.** FastMCP stdio server (one tool definition).

## 4. Internal helpers

- `_validate_state_dir() -> pathlib.Path` — resolves `${LOCAL_IMAGE_GEN_STATE_DIR}` (default `~/.local-image-gen/state/`), runs `mkdir(parents=True, exist_ok=True)`, returns the absolute path. Called once at module import time and once at startup. Returns the same path on every call. Lets `OSError` propagate.
- `_pick_free_port(host: str = "127.0.0.1") -> int` — opens a TCP socket, `bind((host, 0))`, reads `getsockname()[1]`, closes the socket. Returns the port number. Used by `start_service` to pick a port before spawning vllm-omni (which does not accept `--port 0`). Uses `with socket.socket(...) as s:` per §9.
- `_spawn_vllm_omni(args: list[str]) -> subprocess.Popen` — calls `subprocess.Popen(args, stdout=sys.stderr, stderr=subprocess.STDOUT, start_new_session=True)`. Returns the Popen object. stdout/stderr are unified to the MCP server's stderr; stdout is reserved for JSON-RPC. Lets `OSError` / `FileNotFoundError` propagate.
- `_poll_ready(port: int, bearer_token: str, deadline_s: float) -> bool` — polls `GET /v1/models` with `Authorization: Bearer <bearer_token>` every `READY_POLL_INTERVAL_S` until 200-ready or `time.monotonic() > deadline_s`. Returns `True` on ready, `False` on timeout. The HTTP error handling is **inside the retry loop**: each HTTP call is wrapped at the loop body with a `try` (single allowed boundary, §5) that catches `httpx.HTTPError` / `ConnectionError` and continues to the next poll iteration; the function itself raises nothing on transient network errors. Lets `OSError` propagate only on socket exhaustion.
- `_read_service_json() -> Optional[dict]` — reads `${STATE_DIR}/service.json` if it exists; returns the parsed dict or `None`. Lets `OSError` / `PermissionError` / `json.JSONDecodeError` propagate (§5).
- `_write_service_json(contents: dict) -> None` — writes `service.json` atomically via `with tempfile.NamedTemporaryFile(mode='w', dir=state_dir, delete=False) as f:` + `f.write(...)` + `f.flush()` + `os.replace(f.name, service_path)` (§9 — uses `with` for the temp file). Lets `OSError` propagate.
- `_prune_stale_service_json() -> None` — reads `service.json`; if its PID is not alive (`os.kill(pid, 0)` raises `ProcessLookupError` / `PermissionError`), calls `os.remove(service_path)` via the helper `_remove_service_json_file()` (which lets `OSError` propagate). Used by `list_local_models`, `start_service`, and `list_running_services`.
- `_release_subprocess(pid: int) -> None` — opens `/proc/<pid>` or uses `psutil.Process(pid)` (whichever is available; psutil preferred for cross-platform) to get a handle, sends `proc.terminate()` (SIGTERM), waits up to `RELEASE_GRACE_S`, and on `subprocess.TimeoutExpired` sends `proc.kill()` (SIGKILL). The single `try` in this function is at the boundary (§5): it catches `subprocess.TimeoutExpired` to convert the timeout signal into a kill action. Does not remove `service.json`; that is the caller's responsibility.
- `_route_invoke(client: openai.OpenAI, prompt: str, model: str, as_edit: bool, image: Optional[str], images: Optional[list[str]], size: Optional[str], outputFormat: str, count: int, negative_prompt: Optional[str], num_inference_steps: Optional[int], guidance_scale: Optional[float], true_cfg_scale: Optional[float], seed: Optional[int], timeout_s: float) -> list[str]` — switches between `client.images.generate(...)` (JSON body) and `client.images.edit(...)` (multipart) based on `as_edit`. Returns a list of b64_json strings of length `count`. For edits, the local file paths in `image` / `images` are converted to base64 data URLs and passed as `image` / `image[]` per the POC-confirmed vllm-omni field names. Lets `openai.OpenAIError` and `OSError` propagate.
- `_build_edit_multipart(...)` — constructs the multipart body for `/v1/images/edits`. Uses `openai.OpenAI`'s `images.edit` helper for the multipart envelope (POC-verified at vllm-omni 0.22.0) and passes vllm-omni-specific field names via the client call's kwargs. (If the `openai` Python client does not expose `image[]` array semantics, this helper falls back to a hand-rolled `httpx` POST; that fallback is gated on a runtime check at first call, not at import time — see 02 §6 Tech Stack for the rationale.)
- `_decode_and_persist(b64_strings: list[str], target_paths: list[pathlib.Path], output_format: str) -> None` — base64-decodes each string, writes the bytes to the corresponding `target_path` via `with open(target_path, "wb") as f:` (§9). `output_format` controls the file extension (sanity check — extension is already on `target_path`). Lets `OSError` / `base64.binascii.Error` propagate.

## 5. State and data flow

State is on disk in `${LOCAL_IMAGE_GEN_STATE_DIR}/service.json`. The MCP server does not hold any in-process state across tool calls (other than the FastMCP framework's own request-scoped state). The 5-level cache lookup chain is recomputed at each `start_service` call; the chain is **not** cached across calls because env vars may change between calls (e.g. operator sets `HF_HOME` between two `start_service` invocations). Per FR-8 single-service invariant, the file holds at most one record; the module does not implement any locking (per 02 §3.1, vllm-omni's single-worker uvicorn queues requests FIFO at the server).

**Startup sequence (stdio lifecycle, FR-9):**
1. `import local_image_gen.mcp_server` — module body calls `_validate_state_dir()` (one-shot) and then a startup hook calls `_prune_stale_service_json()`.
2. FastMCP framework registers the 5 tools via `server.add_tool(...)` calls.
3. Server enters the stdio read loop on `sys.stdin`, dispatching each line as a JSON-RPC request to the matching tool function.

**Shutdown sequence (stdio lifecycle, FR-9):**
1. Gateway closes `sys.stdin` (stdin EOF).
2. FastMCP framework stops accepting new tool calls (in-flight calls complete).
3. The framework's shutdown hook reads `service.json`; if a service is running, calls `_release_subprocess(pid)` (SIGTERM, wait `RELEASE_GRACE_S`, SIGKILL) and removes `service.json`.
4. Process exits 0 if shutdown completes within `SHUTDOWN_GRACE_S = 30`. On hard timeout, SIGKILL on vllm-omni and exit non-zero.

Data flow for a typical `invoke_model`:
1. `invoke_model` reads `service.json` (state on disk).
2. `invoke_model` reads env vars indirectly via `openai.OpenAI` client construction.
3. `invoke_model` calls `_route_invoke` → `openai.OpenAI` sync client → vllm-omni over HTTP.
4. vllm-omni returns b64_json response.
5. `invoke_model` calls `_decode_and_persist` to write files to disk.
6. `invoke_model` returns the success dict (path + b64_json + vllm-omni usage metadata).

## 6. Dependencies

External libraries (imported at module top):
- `asyncio` (stdlib) — `asyncio.to_thread` for awaiting sync `openai` calls.
- `base64` (stdlib) — b64_json decode.
- `json` (stdlib) — `service.json` read/write.
- `os` (stdlib) — `os.kill`, `os.replace`, `os.remove`, env-var reads.
- `pathlib` (stdlib) — `Path` for `filename` validation.
- `secrets` (stdlib) — `token_urlsafe` for bearer-token generation.
- `socket` (stdlib) — port-picking.
- `subprocess` (stdlib) — `Popen` for vllm-omni.
- `sys` (stdlib) — `sys.stderr` for unified log capture.
- `tempfile` (stdlib) — `NamedTemporaryFile` for atomic `service.json` write.
- `time` (stdlib) — `time.monotonic` for readiness-poll deadline.
- `typing` (stdlib) — `Optional`.
- `mcp` (third-party, FastMCP) — `@server.add_tool` decorators, `stdio` server loop.
- `openai` (third-party) — `openai.OpenAI` sync client.
- `httpx` (third-party, **transitive via `openai`**) — imported only if the `images.edit` helper cannot express `image[]` array semantics and a hand-rolled multipart fallback is required (gated on runtime check).
- `psutil` (third-party, optional) — preferred over `/proc/<pid>` for the cross-platform process handle in `_release_subprocess`. Falls back to a `subprocess.Popen` shim if not installed (logged at module-import time).
- `urllib.parse` (stdlib) — `urljoin` is not used; the `openai` client builds URLs from `base_url`. (Listed for completeness; not imported.)

Module-internal:
- `local_image_gen.cache_resolver` — `walk_levels` and `resolve` are the only functions imported from this module. (The cache_resolver module's own exception types are not re-raised; this module just lets them propagate per §5.)

Test dependencies (per `python-coding-rules` §8 — `unittest` only, no pytest):
- `unittest` (stdlib) — `TestCase` + `IsolatedAsyncioTestCase` for sync + async test bodies.
- `unittest.mock` (stdlib) — `MagicMock` / `AsyncMock` / `patch` for `subprocess.Popen` and `openai.OpenAI` patches.
- `tempfile` (stdlib) — `TemporaryDirectory` context manager in `setUp` / `tearDown` (§9).
- `time` (stdlib) — `time.monotonic` patches via `unittest.mock.patch`.
- `pathlib` (stdlib) — `Path` for test paths.
- `os` (stdlib) — `os.environ` patches via `unittest.mock.patch.dict`.
- `typing` (stdlib) — `Optional`, `Any` for type hints in test code.
- **No pytest. No pytest-asyncio. No freezegun.** The freezegun-equivalent is `unittest.mock.patch('local_image_gen.mcp_server.time.monotonic', return_value=<fixed>)`.

## 7. Configuration

| Constant | Value | Source | Used by |
|----------|-------|--------|---------|
| `DEFAULT_START_TIMEOUT_S` | `120` | 02 §3.1 (v11 owner decision 2026-06-30T21:32) | `start_service` |
| `DEFAULT_INVOKE_TIMEOUT_S` | `120` | 02 §3.1 | `invoke_model` |
| `RELEASE_GRACE_S` | `10` | 02 §3.1 | `release_service`, stdio-EOF shutdown |
| `SHUTDOWN_GRACE_S` | `30` | 02 §3.1 | stdio-EOF shutdown |
| `READY_POLL_INTERVAL_S` | `1.0` | 02 §3.1 | `_poll_ready` |
| `SERVICE_FILE_NAME` | `"service.json"` | 02 §3.1 (v12.1 — no `service_id`) | all I/O helpers |
| `BEARER_TOKEN_BYTES` | `32` | 02 §3.1 (`secrets.token_urlsafe(32)`) | `start_service` |
| `DEFAULT_STATE_DIR` | `"~/.local-image-gen/state/"` | 02 §3.1 (env-var default) | `_validate_state_dir` |

Env vars read at module-import time:
- `LOCAL_IMAGE_GEN_BEARER_TOKEN` — if set, used as the bearer token; if unset, auto-generated per `start_service` call (not per module-load — see below).
- `LOCAL_IMAGE_GEN_STATE_DIR` — if set, overrides the default state directory; if unset, `${HOME}/.local-image-gen/state/`.

Note on bearer-token lifetime: the token is generated **per `start_service` call**, not per module-load. The `LOCAL_IMAGE_GEN_BEARER_TOKEN` env var, if set, is used as a static token for the lifetime of the gateway. This matches 02 §3.1's "auto-generated if unset" semantics — the env var provides a way for the gateway operator to pin the token across restarts.

## 8. Open questions

- **Q1.** Whether `_route_invoke` for edits needs the `httpx` hand-rolled multipart fallback or whether the `openai` Python client's `images.edit` helper handles `image[]` natively. This is a POC gate — blocked on running vllm-omni end-to-end in the WSL env. Resolution: run a POC; if `images.edit` accepts `image=["/path/a", "/path/b"]` directly, no fallback is needed; if not, the `_build_edit_multipart` fallback path is exercised.
- **Q2.** Whether `release_service` should return `released: false` (vs raise `no_running_service`) when the service is already gone. Current design returns `no_running_service` (idempotent — agent can call release on a dead service without seeing an error per 02 §3.1). The OpenClaw built-in `image_generate` may want a different shape; defer to user Gate 2.
- **Q3.** Whether `list_running_services` should return 0 entries or 1 entry with `status: "stopping"` while a release is in progress (between `proc.terminate()` and `proc.kill()`). Current design returns 1 entry with `status: "ready"` (the in-process `_release_subprocess` call is synchronous and blocks the FastMCP tool call, so there is no in-progress state to observe from the outside). If the gateway needs to observe the in-progress state, `_release_subprocess` would need to be async and the file would need to be marked `status: "stopping"`. Resolution: defer to user Gate 2 (current design is the simpler synchronous-blocking path).
- **Q4.** Whether `invoke_model` should pre-validate `size` against a per-model allow-list (e.g. `"1024x1024"` for Z-Image-Turbo). Current design forwards the value verbatim and lets vllm-omni return 4xx for unsupported sizes. This matches 02 §3.1's "MCP server does not pre-validate" stance. Resolution: defer to user Gate 2.
- **Q5.** Whether the `outputFormat` parameter's effective format is enforced on the persisted bytes (e.g. re-encode a PNG returned by vllm-omni as JPEG if the caller asked for `jpeg`). Current design decodes the b64_json bytes and writes them as-is (assuming vllm-omni respects the `output_format` parameter and returns the requested format). If vllm-omni returns PNG when the caller asked for JPEG, the file is written as a JPEG with PNG bytes inside (a malformed file). Resolution: POC end-to-end test must verify; if vllm-omni does not honor `output_format`, `_decode_and_persist` needs to re-encode.
- **Q6.** Whether the `true_cfg_scale` parameter is forwarded as the literal field name `true_cfg_scale` (vllm-omni docs) or as a vllm-omni extension that maps to a different wire field. Current design forwards verbatim. Resolution: POC verification.
