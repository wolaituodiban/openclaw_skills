# Requirements Review v2: `local-image-gen` (01-requirements.md)

**Scope**: Verify v2 against v1 review (12 issues). Verification pass only — no architecture, code, or fresh review.

**v2 applies 4 owner design decisions**: (1) bearer token plaintext/no-design-for-v1, (2) single-GPU no-multi-GPU-design, (3) no same-model concurrency, (4) no reference GPU. These are correctly reflected throughout v2.

---

## Per-issue verification

### ISSUE-1 — Stale-prune contradiction between FR-2 and §8
- **Status**: **RESOLVED**
- **Location in v2**: §8 line 70–73 (no stale-prune entry remains); FR-2 line 38 commits to on-call pruning.
- **One sentence**: The §8 entry that contradicted FR-2's prune-on-every-call behavior has been removed; FR-2 is now the sole authority on prune timing.

### ISSUE-2 — Bearer-token flow gap (token reachability)
- **Status**: **RESOLVED** (per owner decision #1: plaintext, no design)
- **Location in v2**: FR-3 line 39 (returns `{..., bearer_token}` in plaintext), FR-4 line 40 (forwards `Authorization: Bearer <token>` from PID-and-meta file), NFR-5 line 57 (env var `LOCAL_IMAGE_GEN_BEARER_TOKEN`, auto-generated if unset, persisted plaintext), §9 Glossary "PID-and-meta file" line 81 (fields list with `bearer_token (plaintext)`).
- **One sentence**: The token reaches the agent via FR-3's return record, is forwarded by FR-4, and the PID-and-meta file persists plaintext — the v1 inconsistency between "hash" and unhashed-token has been resolved by removing the hash entirely.

### ISSUE-3 — FR-2 missing `status` field that NFR-8 requires
- **Status**: **RESOLVED**
- **Location in v2**: FR-2 line 38 — `status` is one of `loading` | `ready` (per NFR-8), included in response shape `[{service_id, model_id, pid, port, started_at, status}]`.
- **One sentence**: FR-2 and NFR-8 now agree on the same field, value space, and cross-reference.

### ISSUE-4 — FR-4 missing failure-mode acceptance criteria
- **Status**: **RESOLVED**
- **Location in v2**: FR-4 line 40 — covers non-2xx response (surfaces model error + HTTP status), `invoke_timeout` 120 s (`LOCAL_IMAGE_GEN_INVOKE_TIMEOUT`), empty `prompt` and unsupported `size` (HTTP 400 validation error, no model-server contact).
- **One sentence**: All four v1 failure-mode gaps (HTTP error, timeout, invalid prompt, invalid size) now have explicit acceptance criteria.

### ISSUE-5 — FR-3 missing subprocess-hang behavior
- **Status**: **RESOLVED**
- **Location in v2**: FR-3 line 39 — start timeout 30 s (`LOCAL_IMAGE_GEN_START_TIMEOUT`), subprocess terminated, no PID-and-meta file written, timeout error returned.
- **One sentence**: FR-3 now explicitly defines the hang path and reuses the NFR-2 budget as the bound.

### ISSUE-6 — NFR-1 undefined "target GPU" / "warm-up" terms
- **Status**: **RESOLVED** (per owner decision #4: no reference GPU)
- **Location in v2**: NFR-1 line 53 (no GPU SKU locked, no budget asserted, observed for operator review); §4 line 29 non-goal ("Reference-GPU-locked performance budgets"); NFR-6 line 58 (no specific GPU SKU named).
- **One sentence**: The undefined terms are removed by removing the requirement they supported; NFR-1 is now a reporting-only requirement with no pass/fail threshold.

### ISSUE-7 — FR-1 `current_load_status` value space
- **Status**: **RESOLVED**
- **Location in v2**: FR-1 line 37 — `current_load_status` is one of `not_loaded` | `loading` | `loaded`, with semantics for each value.
- **One sentence**: Value space is now explicit and each state has a precise definition tied to start/load progress.

### ISSUE-8 — FR-8 multi-service not testable on 16 GB target
- **Status**: **RESOLVED** (per owner decisions #2 and #3: single-GPU, no same-model concurrency)
- **Location in v2**: FR-8 line 44 (single-GPU single-service invariant; same-model returns existing `service_id`); §3 goal #3 line 15 (v1 allows at most one running service); §4 line 23 non-goal (parallel model-server processes); §2 line 9 (explicitly deferred).
- **One sentence**: The untestable multi-service requirement has been replaced with a single-service invariant that is fully testable.

### ISSUE-9 — FR-6 `response_format` default only in §8
- **Status**: **RESOLVED**
- **Location in v2**: FR-6 line 42 — `b64_json` is the only supported `response_format`; `url` is rejected with `400 unsupported_response_format`.
- **One sentence**: The default is now locked into FR-6's acceptance criteria, not deferred to §8.

### ISSUE-10 — Missing env var names
- **Status**: **RESOLVED**
- **Location in v2**: FR-3 `LOCAL_IMAGE_GEN_START_TIMEOUT` line 39; FR-4 `LOCAL_IMAGE_GEN_INVOKE_TIMEOUT` line 40; FR-5 `LOCAL_IMAGE_GEN_RELEASE_GRACE` line 41; FR-7 `LOCAL_IMAGE_GEN_MCP_PORT` and `LOCAL_IMAGE_GEN_MCP_ALLOW_NONLOOPBACK` line 43; FR-9 `LOCAL_IMAGE_GEN_SHUTDOWN_TIMEOUT` line 45; NFR-5 `LOCAL_IMAGE_GEN_BEARER_TOKEN` line 57; §7 `LOCAL_IMAGE_GEN_STATE_DIR`, `LOCAL_IMAGE_GEN_MODEL_MANIFEST` line 66.
- **One sentence**: Every env var previously left implicit now has an explicit `LOCAL_IMAGE_GEN_*` name.

### ISSUE-11 — §8 model-scope open question vs §9 lock
- **Status**: **RESOLVED**
- **Location in v2**: §8 line 72 ("Multi-model manifest. Deferred to v2; v1 is single-model (Z-Image-Turbo, locked by §9)"); §4 line 23 non-goal; §9 line 77.
- **One sentence**: §8 is now framed as a deferral ("deferred to v2") rather than an unresolved question, and §9 retains the lock — see V2-1 below for a residual wording nit.

### ISSUE-12 — Missing Python version in NFR-6
- **Status**: **RESOLVED**
- **Location in v2**: NFR-6 line 58 — "Linux + Python 3.11+ + CUDA".
- **One sentence**: Python 3.11+ is now part of the portability floor.

---

## New issues introduced by v2

### V2-1 — Circular "locked by" cross-reference between §8 and §9
- **Severity**: minor
- **Location**: §9 line 77 ("v1 supports Z-Image-Turbo via the diffusers `ZImagePipeline` class (locked by §8)") vs §8 line 72 ("v1 is single-model (Z-Image-Turbo, locked by §9)").
- **Problem**: §9 says §8 locks the model choice; §8 says §9 locks it. The decision is consistent and unambiguous across the doc, but the cross-reference is circular — neither section is actually the locking authority on its own.
- **Suggestion**: Drop the "(locked by §N)" parenthetical on one side and write the lock directly, e.g., §9: "v1 supports Z-Image-Turbo only; multi-model manifest is deferred to v2 (see §8)."

No other new issues found. Token handling, single-GPU scope, env-var names, and the §8 deferral framing are all consistent.

---

## Open questions sanity check

All four §8 entries (lines 70–73) are genuinely deferred — none should be promoted into §5/§6:

- **`response_format: url` support** — v1 commitment (FR-6 line 42) is unambiguous; the v2 entry is a forward-looking deferral, not a pending decision.
- **Multi-GPU service distribution** — explicitly out of scope for v1 per §4 and FR-8; entry is correctly framed as deferred.
- **Multi-model manifest** — same shape as above; v1 is single-model and the §8 entry defers the expansion.
- **Persistent invocation queue across restarts** — this is a real open behavior question (the queue does not survive restart in v1, by design of FR-4); correctly framed as "worth revisiting."

No §8 item has already been decided elsewhere in the doc in a way that contradicts the §8 framing.

---

## Testability re-check

| FR | Testable by an automated test? | Note |
|----|---|---|
| FR-1 | **Yes.** Manifest fixture → assert entries with `current_load_status ∈ {not_loaded, loading, loaded}`; empty-manifest fixture → assert empty list, no error. | Value space now defined. |
| FR-2 | **Yes.** Fixture of N PID files (some live, some stale) → assert live ones returned with `status` field, stale files removed. | `status` field defined; cross-ref to NFR-8 resolves v1 gap. |
| FR-3 | **Yes.** Happy path: warm start → service record returned with all fields. Timeout: simulate wedged subprocess → assert terminated, no PID file, timeout error. Same-model-id: call twice → assert same `service_id`. Failure modes: invalid model_id, port exhaustion → assert no PID file, error surfaced. | Subprocess-hang path and same-model-id reuse both testable. |
| FR-4 | **Yes.** Happy path: forward to mock model-server. Non-2xx: mock returns 500 → assert error message + status surfaced. Timeout: mock hangs → assert `invoke_timeout` error. Empty prompt / invalid size → assert validation error without contacting mock. Unknown `service_id` / dead process → assert clear error. | All v1 failure-mode gaps now have testable criteria. |
| FR-5 | **Yes.** Start then release → assert PID file gone, process dead. Unknown id → assert no-op error. SIGTERM-ignoring process fixture → assert SIGKILL after grace period. | Grace period env var now named. |
| FR-6 | **Yes.** Standard request/response shape: fixture with valid payload → assert b64_json response. `response_format: url` → assert `400 unsupported_response_format`. Missing `prompt` / invalid `size` → assert `400 invalid_request_error`. Non-standard fields → assert ignored. | b64_json-only now committed in FR-6. |
| FR-7 | **Yes.** Default port → assert 8765 in use + log line. Override env var → assert overridden port. Non-loopback without opt-in → assert reject. With `LOCAL_IMAGE_GEN_MCP_ALLOW_NONLOOPBACK=true` → assert security-sensitive log. | Env var names now fixed; loopback-only default explicit. |
| FR-8 | **Yes.** Two `start_service(model_id)` calls with same id → assert same `service_id` returned, no second subprocess spawned. Different model ids in v1 → assert second call behavior consistent with single-service invariant (returns existing or refuses — both observable from the v1 invariant statement). | Single-service invariant is fully testable; multi-service is explicitly out of scope. |
| FR-9 | **Yes.** SIGTERM to MCP server with one running model-service → assert clean termination of both, PID file removed, exit code 0. Stuck model-service → assert SIGKILL after `LOCAL_IMAGE_GEN_SHUTDOWN_TIMEOUT`, MCP server exits non-zero. | Exit codes and shutdown timeout env var now specified. |

No FR has ambiguous or missing acceptance criteria after v2 edits.

---

## Summary

**12 of 12 v1 issues resolved.** **1 minor new issue (V2-1, circular cross-reference).** All four owner design decisions are correctly applied. §8 Open Questions contains only genuinely deferred items. All FRs are testable.
