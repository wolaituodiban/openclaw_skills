# 01 — Requirements

> **Status:** v12.5 (2026-07-01T00:19) — FR-4 `invoke_model` filename contract extended: (i) `filename`'s parent directory must already exist on disk — otherwise reject `filename_dir_not_found` (HTTP 400-shaped, no vllm-omni contact); (ii) `count>1` is now supported alongside a caller-supplied `filename`: when `count=N`, write files `<stem>-1.<ext>`, `<stem>-2.<ext>`, …, `<stem>-N.<ext>` where `<stem>` is `Path(filename).stem` and `<ext>` is `Path(filename).suffix`; the v12.4 rejection of `filename + count>1` is **retired**. Audit trail: v12.3 hardcoded the media directory and banned caller-supplied dirs (`invalid_filename` on `/`); v12.4 made `filename` required; v12.5 keeps `filename` required but adds a precondition on its parent dir and re-enables `count>1` with caller-supplied basenames. Owner rationale (2026-07-01T00:16): "filesystem is the caller's; the server neither invents names nor creates parent dirs".
>
> **POC gate (owner, 2026-06-30T21:32):** three POC items folded into v12.1 ([x] RESOLVED): ModelScope path acceptance = scheme B; `--api-key` support confirmed; readiness probe narrowed to `/v1/models`. Two items remain POC-pending (cold-start latency calibration; multipart field exact names). Full list in §8. v12.2 adds no new POC gate; the five parameters exist at the wire layer (verified by reading the vllm-omni stable documentation page 2026-06-30T23:17) — a live POST against a 0.22.0 instance is recorded as a follow-up POC item in §8.

## 1. Reference snapshot

| Field | Value |
|-------|-------|
| Skill name | `local-image-gen` |
| Current version | v12.5 |
| Last amendment date | 2026-07-01T00:19 |
| Amendment drivers | Owner decision 2026-07-01T00:19 (v12.5): (i) `filename`'s parent directory must already exist — otherwise reject `filename_dir_not_found` (400); (ii) `count>1` is now supported alongside caller-supplied `filename`: write `<stem>-N.<ext>` (no zero-padding) per index. Owner decision 2026-06-30T23:56 (v12.4): `filename` required positional — see `02-architecture.md` §0.3. Owner decision 2026-06-30T23:38 (v12.3): filename contract reversal — see `02-architecture.md` §0.2. Owner decision 2026-06-30T23:16 (v12.2): extend `invoke_model` with 5 vllm-omni extension parameters — wire-layer existence verified against [vllm-omni stable docs](https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/image_generation_api/) and [image_edit_api](https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/image_edit_api/) (web_fetch 2026-06-30T23:17; both endpoints declare the same five fields with the same names, types, and defaults; pass-through semantics per docs "Parameter Handling → Pass-through design"). POC-verified (vllm-omni 0.22.0 at `/tmp/.vllm-poc-venv/`) + owner-approved simplifications (2026-06-30T22:04: drop `service_id`; drop client-side FIFO lock; drop `--api-key` fallback). |
| Reference fixture | Z-Image-Turbo on RTX 3090 |
| Implementation detail | See `02-architecture.md` |

## 2. Problem statement

The OpenClaw built-in `image_generate` tool calls cloud APIs. For local-only workflows the operator has no first-class way to drive a local model server (vllm-omni) through the same MCP tool surface — every local call becomes a shell-out to a hand-managed server. The skill exists so that an agent, working through the MCP tool surface, can resolve a local model on disk, start a model service, invoke it, and release it as part of a normal tool call, with the OpenClaw gateway owning the MCP server's lifecycle.

## 3. Goals

1. `start_service(model)` resolves a HuggingFace- or ModelScope-style repo name against the **local cache only** (no network download in v1) and brings a vllm-omni subprocess up.
2. `invoke_model(prompt, ...)` maps onto vllm-omni's `POST /v1/images/generations` (text-to-image) or `POST /v1/images/edits` (image-conditioned edit) endpoints, returning decoded image bytes.
3. `release_service(model)` brings the subprocess down and removes its state.
4. `list_local_models` and `list_running_services` exist for diagnostics.
5. Bearer-token authentication on the model service's HTTP surface is unconditional; the OpenClaw gateway owns the MCP server's lifecycle via stdio.
6. vllm-omni is the **only** accepted model-server backend in v1.
7. Errors from vllm-omni (4xx, 5xx, validation, shape-mismatch, capability-unsupported) are surfaced to the caller **verbatim** — the MCP server does not parse, transform, hide, or retry upstream errors.
8. The MCP server does **not** maintain a model-capability table; it does not pre-validate fields it forwards; it does not auto-start services on first `invoke_model`.

## 4. Non-goals (v1)

- Network download of model snapshots — pre-cached on disk only. `model_not_found` if no on-disk snapshot.
- `response_format: url` for `/v1/images/generations` — vllm-omni does not expose this for diffusion in v1; v1 returns `b64_json`-only; MCP server sets `response_format: b64_json` regardless of any caller-supplied override equivalent (FR-4 mapping).
- Multi-service (multiple model-servers simultaneously).
- Multi-GPU.
- Bearer-token rotation, hashing, per-user scoping, expiry.
- SIGTERM/SIGHUP handlers on the MCP server — stdin EOF is the only shutdown signal.
- Auto-start of `start_service` on first `invoke_model`.
- Client-side FIFO lock between concurrent `invoke_model` calls against the same service.

## 5. Functional requirements

Each FR states **what the system does**, not how. Wire formats, file layouts, command-line arguments, and protocol field names belong in `02-architecture.md`.

| ID | Requirement | Priority | Acceptance criteria |
|----|-------------|----------|---------------------|
| FR-1 | List loadable local models | must | `list_local_models()` returns one entry per model name resolvable to an on-disk snapshot, with `current_load_status ∈ {not_loaded, loading, loaded}`. No hardcoded allow-list — any pre-cached repo name appears. An unresolvable name returns `model_not_found` from `start_service` and never appears here. Response shape: `[{model, current_load_status}]` (the field is named `model`, to align with `image_generate`). |
| FR-2 | List running model services | must | `list_running_services()` returns one entry per live model service (zero or one entry in v1). Each entry's `status ∈ {loading, ready}`. Stale state files (process not alive) are pruned before responding. Response shape: `[{model, pid, port, started_at, status, cache_source}]`. Empty list is valid. |
| FR-3 | Start a new model service | must | `start_service(model, cache_dir=None, timeoutMs=None)`: (i) resolves `model` against the local cache; (ii) on hit, spawns vllm-omni (the only accepted backend) as a subprocess; (iii) waits until the subprocess reports ready or `timeoutMs` elapses (hardcoded default applies when omitted); (iv) on success, returns `{model, pid, port, started_at, bearer_token, cache_source, ...}`; on failure to find / load / reach ready, the subprocess is terminated and no state file is written. The bearer token is returned in plaintext so the caller can use it to call the model service directly. |
| FR-4 | Invoke a running model service | must | `invoke_model(prompt, filename, model=None, image=None, images=None, size=None, outputFormat="png", count=1, negative_prompt=None, num_inference_steps=None, guidance_scale=None, true_cfg_scale=None, seed=None, timeoutMs=None)` — 14 args, `prompt` and `filename` are required positional. Reject `prompt=""`. Reject `filename=None` at the signature layer. Reject `filename` containing `/`, `filename` whose parent directory does not exist on disk (`filename_dir_not_found`), and any path already in use after applying the `count>1` numbering rule. If `count>1`, write `<stem>-1.<ext>` … `<stem>-N.<ext>`; otherwise write `<filename>` verbatim. Reject the call if any of the resulting target paths already exists (`filename_conflict`). If no service is running, return `no_running_service`; do **not** auto-start. If a `model` is supplied and does not match the running service, return `model_not_loaded`. Support both text-to-image (no `image`/`images`) and image-editing (at least one) modes; each invocation returns image bytes in the requested `outputFormat` plus a stable `path` (file is always written — no inline-only return). Five diffusion-control parameters (`negative_prompt`, `num_inference_steps`, `guidance_scale`, `true_cfg_scale`, `seed`) are forwarded verbatim; the running model is the source of truth for accepted shapes/values (silently ignored is possible). Errors from the running service are surfaced verbatim. |
| FR-5 | Release a model service | must | `release_service(model)` stops the running vllm-omni subprocess (graceful, then forceful on timeout) and removes its state file. `model` is required. Idempotent — a missing state file returns `no_running_service`; a stale state file (recorded process is dead) is removed and the call returns success. `model` mismatch against the state file returns `model_not_loaded`. Successful response: `{released: true, model, ...}`. |
| FR-6 | OpenAI-compatible Images API exposed | must | A running model service exposes vllm-omni's OpenAI-compatible endpoints — `POST /v1/images/generations` (JSON) and `POST /v1/images/edits` (multipart/form-data) — returning DALL-E-compatible response shapes (`{"data": [{b64_json}]}`). Bearer token (FR-3) protects both. In v1 only `response_format: b64_json` is requested; `url` is not exposed. |
| FR-7 | MCP server in stdio mode, lifecycle owned by OpenClaw gateway | must | The MCP server runs in stdio mode (JSON-RPC over stdin/stdout). The **OpenClaw gateway** owns the MCP server's lifecycle — spawning, tracking, terminating. The MCP server has no listening port of its own; vllm-omni is the only network-listening process in the system. The gateway → MCP server pipe is private to the gateway. |
| FR-8 | Global single-service invariant | must | At most one model service runs at any time. A second `start_service` (same or different `model`) fails with `service_already_running`, surfacing the existing service's `model`. The MCP server does not auto-release the existing service to make room. Multi-service and multi-GPU are out of scope. v1 deliberately keeps the model-name-only interface (no `service_id` field); when v2 introduces multi-service, a service identifier will reappear on this surface. |
| FR-9 | Cleanup delegation on stdin EOF | should | When the MCP server's stdin closes (no SIGTERM/SIGHUP handlers installed), the MCP server cleans up its **own** vllm-omni subprocess (graceful, then forceful) and removes its state file before exiting. The OpenClaw gateway does **not** reach into vllm-omni directly. |

## 6. Non-functional requirements

| ID | Category | Requirement | Measure |
|----|----------|-------------|---------|
| NFR-1 | performance | Latency reporting | Every `invoke_model` response and every model-service HTTP response carries a `duration_ms` field. No GPU-SKU-specific latency budget is locked in v1; observed latency is recorded for operator review, not asserted as a pass/fail threshold. |
| NFR-3 | reliability | State-file durability | State files survive MCP-server restart. The MCP server re-validates each file's recorded PID at startup and removes files whose process is dead. |
| NFR-4 | observability | Structured logs | One JSON line per MCP tool invocation (tool name, args summary, duration_ms, status, error if any); one JSON line per vllm-omni lifecycle event (start, ready, exit, signal, timeout). MCP-server logs go to stderr (stdout is reserved for the JSON-RPC stream). vllm-omni stdout is captured to MCP-server stderr for unified log handling. Log fields and startup banners are specified in `02-architecture.md` §7. |
| NFR-5 | security | Bearer-token auth | The OpenAI-compatible Images API requires a bearer token (env var `LOCAL_IMAGE_GEN_BEARER_TOKEN`, auto-generated at MCP-server startup if unset; plaintext). The MCP server passes the token to vllm-omni at startup; the token is required on every request to vllm-omni. vllm-omni token mismatch returns `401`, surfaced verbatim. There is no "loopback-only fallback" path — bearer-token auth is unconditional. The MCP-server tool surface is exposed only via the gateway's private stdin/stdout pipe; there is no MCP listening socket. Token rotation / hashing / per-user scoping are out of scope in v1. |
| NFR-6 | portability | Linux + Python 3.11+ + CUDA + vllm-omni runtime | Runs on Linux + Python 3.11+ + a CUDA-capable GPU (compute capability ≥ 8.0, ≥ 16 GB VRAM for Z-Image-Turbo at 1024×1024) + a local model cache on disk + **vllm-omni 0.14.0+** installed and on `PATH`. vllm-omni is the only accepted model-server backend; installing it is an operator prerequisite (no `pip install` from inside the skill). Missing / too-old vllm-omni → `start_service` fails fast with `vllm_omni_not_found` or `vllm_omni_version_too_old`. macOS / Windows / CPU-only are explicitly out of scope. |
| NFR-7 | operability | No external services | No database, no message broker, no cloud API. State = PID-and-meta file directory + local model cache on disk. |
| NFR-8 | observability | Readiness probe | The MCP server polls the running vllm-omni subprocess's readiness endpoint to detect when inference is available. A successful probe marks the service `ready` in `list_running_services`; an unsuccessful probe keeps it `loading` and counts toward `start_service.timeoutMs`. The exact endpoint, request shape, and probe cadence are specified in `02-architecture.md` §3.1. |

## 7. Users / actors

- **Agent (MCP client)** — invokes the five MCP tools. Typical flow: `list_local_models` → `start_service(model)` → `invoke_model(prompt, ...)` (×N) → `release_service(model)`. On `service_already_running` (FR-8) the agent decides whether to invoke the running service or release it first. Day-to-day invoke/release use never touches a service identifier under v1's single-service invariant; `list_running_services` is purely diagnostic.
- **Human developer (HTTP client)** — sends `curl` or OpenAI-SDK requests to a running service's Images API directly, bypassing MCP. Uses the bearer token returned by `start_service` or read from the state file.
- **Operator** — configures the **OpenClaw gateway** (`gateway.config.mcp.servers`) to manage the MCP server as a managed subprocess. Registers two skill-specific env vars: `LOCAL_IMAGE_GEN_BEARER_TOKEN` (auto-generated if unset) and `LOCAL_IMAGE_GEN_STATE_DIR`. Standard cache env vars (`HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `MODELSCOPE_CACHE`) are inherited from the gateway's environment. Responsible for installing vllm-omni 0.14.0+ on the host (NFR-6); the skill does not auto-install.

## 8. Open questions (POC-dependent)

> **POC gate (owner, 2026-06-30T21:32):** items marked **[POC]** must be verified against a real vllm-omni 0.14.0+ install before locking the version that ships. POC results land as amendments to v12.1+ with the verified scheme documented in `02-architecture.md`. POC does NOT re-open decisions already made (single-service invariant, FR-3 chain order, single model-server responsibility, verbatim error surface).
>
> **POC status as of 2026-06-30T22:10:** scheme B confirmed; `--api-key` confirmed; readiness probe narrowed to `/v1/models`.

- [x] **vllm-omni ModelScope path acceptance (RESOLVED — scheme B).** POC 2026-06-30T22:00 confirmed `vllm serve --omni <modelscope-abs-path>` is accepted directly; vllm-omni auto-detects the diffusers pipeline via `model_index.json` at the root and dispatches the right pipeline class (Z-Image-Turbo verified: `ZImagePipeline` auto-detected, init line `Z-Image init: dim=3840 n_heads=30 n_kv_heads=30 ffn_hidden_dim=10240 final_out_dims=(64,) tp=1`). No HF-bridge / MS-fallback is needed in v1.
- [x] **vllm-omni `--api-key` support (RESOLVED).** POC + source (`vllm/entrypoints/openai/api_server.py:265-269`) confirm `args.api_key` is wired into a FastAPI `AuthenticationMiddleware` that protects every route including `/v1/images/generations` and `/v1/images/edits`. NFR-5 is an unconditional requirement; no fallback path.
- [POC] **Z-Image-Turbo cold-start latency calibration.** v1 default `timeoutMs = 120 s`. POC observed weight-load ~22 s on RTX 3090; full dummy warm-up not yet measured due to WSL `python3-devel` env gap (independent of scheme B correctness). Calibration adjusts the hardcoded default when measured.
- [POC] **`/v1/images/edits` multipart field exact names.** The MCP server packages `image`/`images` (and any future `mask`) into the multipart body. Exact field names (`image` vs `image[]`), ordering, and whether the prompt requires a separate multipart field are pending POST against a live vllm-omni instance. Schema mismatches surface as 4xx and pass through verbatim.
- [POC] **v12.2 extension parameters verified against a live vllm-omni 0.22.0 instance.** Wire-layer existence of `negative_prompt` / `num_inference_steps` / `guidance_scale` / `true_cfg_scale` / `seed` is verified against the [vllm-omni stable docs](https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/image_generation_api/) ([image_edit_api](https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/image_edit_api/)) (web_fetch 2026-06-30T23:17, both endpoints declare the same five fields). A live POST against a 0.22.0 instance is still pending so that the MCP server's actual outbound payload can be diffed against vllm-omni's Pydantic schema. The wire-layer source-of-truth is the vllm-omni docs page, not this POC; if 0.22.0 implementation diverges from the docs, an amendment will follow.
- [POC] **v12.5 filename contract end-to-end.** Verify (i) `filename` with `/` returns `invalid_filename` (no vllm-omni contact); (ii) `filename` omitted returns the standard "missing required argument" error (no vllm-omni contact); (iii) `filename` whose parent dir does not exist returns `filename_dir_not_found` (400, no vllm-omni contact); (iv) any target path already in use returns `filename_conflict` (400, no vllm-omni contact); (v) `count=3` + `filename="cat.png"` writes `cat-1.png`, `cat-2.png`, `cat-3.png` and returns `{path: ["…/cat-1.png", "…/cat-2.png", "…/cat-3.png"], b64_json: [...]}`; (vi) `count=10` writes `cat-1.png` … `cat-10.png` (no zero-padding). Each item stands or falls independently.
- [POC] **Readiness probe exact response shape on Z-Image-Turbo.** Probe endpoint narrowed to `/v1/models` per source review (vllm-omni 0.22.0 overrides upstream); exact pre-ready vs ready response shape still to wire so the parser can distinguish reliably.
- [ ] **`response_format: url` support.** Deferred to v2. v1 is `b64_json` only.
- [ ] **Multi-GPU service distribution.** Deferred to v2+.
- [ ] **Multi-model manifest.** Deferred to v2; v1 ships Z-Image-Turbo as the reference fixture and accepts any repo name vllm-omni supports.

## 9. Glossary

- **Cache source** — the level of the cache chain (FR-3) that actually served the load. Five possible values: `hf_env`, `hf_default`, `ms_env`, `ms_default`, `cache_dir`. The MCP server writes the winning source into the PID-and-meta file as audit.
- **PID-and-meta file** — a JSON file under `${STATE_DIR}` written on successful service start, recording connection details (model, pid, port, started_at, bearer_token, cache_source, model_path). v1 stores at the fixed path `${STATE_DIR}/service.json` (single-service invariant); no service-id field. Stale files (recorded process not alive) are pruned on MCP-server startup and on every `list_running_services` call.
- **Reference fixture** — the model that ships as the default documentation and integration target. v1: `Tongyi-MAI/Z-Image-Turbo`. Operators may pre-cache additional models; v1 reads whatever is on disk.
- **`service_already_running`** — error code returned by `start_service` (FR-3) when a model service is already running. Error message surfaces the existing service's `model`.
- **HuggingFace layout** — `<hub-root>/models--<org>--<repo>/snapshots/<sha>/`. Standard layout under `${HF_HOME}` / `~/.cache/huggingface/hub/`.
- **ModelScope layout** — `<hub-root>/models/<org>/<repo>/`. Standard layout under `${MODELSCOPE_CACHE}` / `~/.cache/modelscope/hub/`.

---

**Next docs in the chain:** `02-architecture.md` (implementation layout), `03-test-strategy.md` (per-skill-testing convention), `04-implementation-plan.md` (per-skill-creator + skill-testing workflow).
