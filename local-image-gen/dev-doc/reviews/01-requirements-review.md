# Requirements Review: `local-image-gen` (01-requirements.md)

## Summary
**Pass with issues — no blockers that prevent the chain from advancing, but three internal contradictions and four untestable acceptance criteria must be resolved before this document can anchor architecture, modules, and tests.** The five MCP tools, the dynamic-port model-server, the fixed-port MCP, the OpenAI-compat Images API, and the Z-Image-Turbo / diffusers basis are all covered. The document is structurally aligned with the few-shot reference (`shorturl`): same §1–§9 layout, same FR/NFR table style, same glossary conventions. Issues are concentrated in (a) the bearer-token flow, (b) NFR-8 ↔ FR-2 inconsistency, (c) FR-4 failure-mode coverage, and (d) FR-8 testability on a single GPU.

## Issues

### ISSUE-1
- **Severity**: blocker
- **Location**: FR-2 (line ~30) vs. §8 Open Questions (line ~85, "Stale-service pruning aggressiveness")
- **Problem**: FR-2 commits to a definitive behavior — "Stale PID files (process not alive) are pruned before responding; the stale file is removed" — but §8 still lists the same question as open with "Default: on every call (slightly more IO, much less confusion)". This is an internal contradiction: a functional requirement has already been written as if the open question is resolved. Either FR-2 is committing ahead of a decision that hasn't been made, or the open question is stale and should be deleted from §8.
- **Suggested fix**: Remove the corresponding entry from §8 (it has already been decided by FR-2), or change the §8 entry to a non-decision note such as "Tracking: behavior fixed by FR-2 — delete on adoption of this doc."

### ISSUE-2
- **Severity**: blocker
- **Location**: FR-3 (line ~33), FR-4 (line ~36), NFR-5 (line ~57), §9 Glossary entry "PID-and-meta file" (line ~97)
- **Problem**: The bearer-token authentication flow has a real gap. NFR-5 requires the OpenAI Images API to require a bearer token configured at model-server start. The glossary entry for "PID-and-meta file" says it stores `bearer_token_hash` — a **hash**, which is one-way. But FR-4 (`invoke_model`) must somehow pass a valid bearer token to the model-server's HTTP endpoint, and FR-3 (`start_service`) only says "the service record is returned" without specifying that the unhashed token is included. There is no stated mechanism for the agent to obtain the token that lets it call the running model-server. The MCP side has no auth (NFR-5), so the only way the token reaches `invoke_model` is through the service record returned at start time — but that field is not in FR-3's acceptance criteria.
- **Suggested fix**: Amend FR-3 acceptance criteria to "…the service record is returned including `service_id`, `model_id`, `port`, `pid`, `started_at`, and `bearer_token` (the unhashed token, for the client to use when calling the model-server directly and when using `invoke_model`)." Amend FR-4 acceptance criteria to "…forwards the request to the model-server's OpenAI-compatible endpoint for that service, including the bearer token associated with the service in the `Authorization` header." Decide and state in the glossary whether the PID-and-meta file persists the token, the hash, or both — current text is internally inconsistent with FR-3's needs.

### ISSUE-3
- **Severity**: blocker
- **Location**: FR-2 (line ~30) vs. NFR-8 (line ~64)
- **Problem**: NFR-8 says "The MCP server polls this before reporting a service as `ready` in `list_running_services`." FR-2's acceptance criteria for `list_running_services` lists returned fields as `(service id, model id, pid, port, started_at)` — with no `ready` / `status` field. NFR-8 introduces a new field on the same response shape that FR-2 does not. This is an internal inconsistency: an NFR is asserting the existence of a field that the FR defining the response does not include.
- **Suggested fix**: Extend FR-2's returned-fields list to include `status` (or `ready`), with the value space defined ("ready" | "loading" | "dead" — the last one being what pruning would have removed, so probably "ready" | "loading"). Cross-reference NFR-8 from FR-2.

### ISSUE-4
- **Severity**: major
- **Location**: FR-4 (line ~36)
- **Problem**: FR-4's acceptance criteria cover happy path ("Returns the generated image…") and two failure modes ("unknown service_id", "process dead"). They do not cover: (a) HTTP-level failure from the model-server (non-2xx response, connection refused mid-call, timeout), (b) invalid or empty `prompt`, (c) invalid `size` value, (d) what timeout `invoke_model` itself enforces on the model-server call. These are all testable in a unit/integration test, but without explicit acceptance criteria, the implementer and the test author will guess differently.
- **Suggested fix**: Add to FR-4: "If the model-server returns a non-2xx response, `invoke_model` surfaces the model's error message and the HTTP status. If the model-server does not respond within `invoke_timeout` (default 120 s, overridable via env var), the call returns a timeout error. Empty `prompt` and unsupported `size` values return a validation error (HTTP 400-shaped) without contacting the model-server."

### ISSUE-5
- **Severity**: major
- **Location**: FR-3 (line ~33), cross-referenced against NFR-2 (line ~52)
- **Problem**: NFR-2 specifies that `start_service` "returns within 30 s" for the success path. FR-3 lists failure modes as "model not loadable, port exhaustion, subprocess error" but does not define what happens if the subprocess hangs (e.g., model-server is wedged before its `/health` endpoint reports ready). NFR-2's budget implicitly bounds this, but a hang is not the same as a slow success — a hang should terminate the subprocess and surface an error, not just block until some external timeout.
- **Suggested fix**: Add to FR-3: "If the model-server subprocess does not report `ready` on `GET /health` within the start timeout (default 30 s; same value as NFR-2), the subprocess is terminated, the PID-and-meta file is removed, and `start_service` returns a timeout error."

### ISSUE-6
- **Severity**: major
- **Location**: NFR-1 (line ~51)
- **Problem**: NFR-1 measures against "model warm-up + 5 s" and "the target GPU". Neither term is defined elsewhere. "Model warm-up" is presumably the first inference pass (compile / cuDNN benchmark), but its duration depends on the prompt, size, and step count, and on whether the same model-server has already served a request. "The target GPU" is referenced only by class ("CUDA-capable, compute capability ≥ 8.0, ≥ 16 GB VRAM" in NFR-6) — that's a class, not a specific SKU. As written, NFR-1 cannot be tested deterministically: the test will either over-budget (slow GPU) or under-budget (fast GPU).
- **Suggested fix**: Replace NFR-1 with two measurable statements: (a) "Warm-path p50 latency for a 1024×1024 image at 9 inference steps is < 5 s on a reference GPU class (e.g., NVIDIA RTX 4090; reference class to be locked in NFR-6)." (b) "Cold-path p50 latency (first invocation after `start_service`) is < 2× warm-path p50 on the same reference GPU class." Lock the reference GPU in NFR-6 to a specific model or a specific compute capability + VRAM floor + a named benchmark.

### ISSUE-7
- **Severity**: major
- **Location**: FR-1 (line ~27)
- **Problem**: FR-1's acceptance criteria promise "current load status" as a returned field for each model entry, but the value space is not specified. A test cannot assert what `current_load_status` should be at any given moment without knowing the allowed values.
- **Suggested fix**: Define the value space: "`current_load_status` is one of `not_loaded` | `loading` | `loaded`. A model is `not_loaded` if no service is currently running it; `loading` if a `start_service` for it is in progress; `loaded` if at least one running service has it."

### ISSUE-8
- **Severity**: major
- **Location**: FR-8 (line ~42), cross-referenced against NFR-6 (line ~60)
- **Problem**: FR-8 requires "two model services running the same or different model ids coexist on distinct dynamic ports and respond independently." NFR-6 floors the target hardware at "≥ 16 GB VRAM" for "Z-Image-Turbo at 1024×1024". Two services loading the **same** Z-Image-Turbo model on a 16 GB GPU will likely OOM, and "different model ids" assumes more than one model is in scope, which §8 still lists as an open question ("Single model (Z-Image-Turbo only) or multi-model manifest from day one?"). The requirement as written is not testable on the target hardware, and the "different model ids" branch depends on an undecided scope question.
- **Suggested fix**: Tighten FR-8 to the testable subset: "Two model services running **different** model ids coexist on distinct dynamic ports and respond independently; two services running the same model id is not required in v1 (assumed to require ≥ 2× the single-service VRAM budget)." Or, if parallel-same-model is required, raise NFR-6's VRAM floor to cover it and add a load-time VRAM probe to FR-3.

### ISSUE-9
- **Severity**: minor
- **Location**: FR-6 (line ~39), cross-referenced against §8 Open Question "Image response format" (line ~89)
- **Problem**: §8 commits a default of `response_format: b64_json`, but FR-6 just says "the standard OpenAI Images response shape" without specifying the response_format. An implementer reading only §5 will not know that `url` is unsupported in v1, and an integration test will have to choose one.
- **Suggested fix**: Add to FR-6: "`response_format` is accepted as `b64_json` or `url`; for v1 the model-server returns `b64_json` (in-process data URL) regardless of the request value, because there is no public URL host. The `url` field is reserved for a future release." Or, lock the default into FR-6 and remove the §8 entry.

### ISSUE-10
- **Severity**: minor
- **Location**: FR-7 (line ~41)
- **Problem**: FR-7 says the default port is `8765` and is "overridable via env var" but does not name the env var. Both the implementer and the test author will guess. The few-shot reference is silent on env vars (it doesn't have one), so this isn't a deviation, but the gap is a small testability hit.
- **Suggested fix**: Specify the env var name, e.g., "overridable via env var `LOCAL_IMAGE_GEN_MCP_PORT` (default `8765`)." Apply the same pattern to the bearer-token env var referenced in NFR-5 and the state-directory env var implied by §7.

### ISSUE-11
- **Severity**: minor
- **Location**: §8 Open Question "Model scope" (line ~83) vs. §9 Glossary entry "Model" (line ~93)
- **Problem**: §8 asks "Single model (Z-Image-Turbo only) or multi-model manifest from day one?" with a default of single model. §9 already locks the answer: "v1 supports Z-Image-Turbo via the diffusers `ZImagePipeline` class." A reader of §8 will assume the decision is still pending.
- **Suggested fix**: Either remove the §8 entry, or rephrase as "Resolved by §9: v1 is single-model (Z-Image-Turbo); multi-model manifest deferred to v2."

### ISSUE-12
- **Severity**: minor
- **Location**: NFR-6 (line ~60)
- **Problem**: NFR-6 specifies the GPU and OS constraints but not the Python version. The few-shot reference's NFR-5 (portability) names "Python 3.11+". The diffusers / torch stack has well-known Python-version constraints; missing the floor here is a portability gap.
- **Suggested fix**: Add a Python version to NFR-6's measure, e.g., "Python 3.11+ on Linux with a CUDA-capable GPU…"

## Coverage check

| User-stated requirement | Covered by | OK? |
|---|---|---|
| list loadable models | FR-1 | yes — explicit `list_local_models` requirement, manifest-driven, empty-safe |
| list running services | FR-2 | yes — explicit `list_running_services` requirement, stale-prune behavior (see ISSUE-1) |
| start a service | FR-3 | yes — explicit `start_service(model_id)`, dynamic port, PID-and-meta file (see ISSUE-5 for timeout gap) |
| invoke a service | FR-4 | partial — happy path covered; HTTP error / timeout / invalid-input paths missing (ISSUE-4) |
| release a service | FR-5 | yes — explicit `release_service(service_id)`, SIGTERM→SIGKILL, idempotent on unknown id |
| model-server uses dynamic port | FR-3 | yes — "OS-assigned free port" |
| MCP server uses fixed port | FR-7 | yes — default `8765`, env-overridable (env var name missing — ISSUE-10) |
| OpenAI-compatible Images API | FR-6 | yes — `POST /v1/images/generations` with standard request/response shape (response_format default lives only in §8 — ISSUE-9) |
| Z-Image-Turbo / diffusers based | explicit in §1, §9, NFR-6, NFR-1, NFR-2 | yes — explicit, named in five places; only §8 still lists scope as open (ISSUE-11) |

## Testability check

| FR | Testable by an automated test? | Note |
|---|---|---|
| FR-1 | **Partially.** Empty-manifest case is testable; the "current load status" field is not testable until its value space is defined (ISSUE-7). |
| FR-2 | Yes. Given a fixture of N PID files (some live, some stale), call the tool, assert the stale one is removed and the live ones are returned with the documented fields. |
| FR-3 | **Partially.** Happy path and obvious failures (unknown model_id, port exhaustion under simulation) are testable; subprocess-hang behavior is not testable until a start timeout is defined (ISSUE-5). |
| FR-4 | **Partially.** Happy path is testable. HTTP-error / timeout / invalid-prompt / invalid-size paths are not testable because the acceptance criteria don't specify them (ISSUE-4). |
| FR-5 | Yes. Start a service, release it, assert PID file removed and process dead. Unknown-id → no-op error is testable. Grace-period fallback to SIGKILL is testable by simulating a process that ignores SIGTERM. |
| FR-6 | Yes for the standard request/response shape. Missing-prompt / unsupported-size response shape is not testable because FR-6 doesn't say what 400-shaped errors look like (related to ISSUE-4). |
| FR-7 | Yes once the env var name is fixed (ISSUE-10). Start with default → assert port 8765 in use; start with override → assert overridden port in use; assert log line emitted. |
| FR-8 | **Not deterministically testable on the target hardware floor (16 GB VRAM)** with two services loading the same Z-Image-Turbo model — see ISSUE-8. Testable for two services on different model ids only after §8's model-scope question is resolved. |
| FR-9 | Partially. SIGTERM → clean shutdown is testable; "exits" is testable; specific exit code and shutdown timeout are not specified, so "cleanly" is subjective. |
