# 02-architecture v2 review (post-stdio-restructure)

**Reviewer**: sub-agent (depth 1/1), spawned 2026-06-28 23:54 GMT+8
**Docs under review**:

- `~/.openclaw/skills/local-image-gen/dev-doc/01-requirements.md` (v4)
- `~/.openclaw/skills/local-image-gen/dev-doc/02-architecture.md` (v2)

**Restructure context**: owner-driven (2026-06-28T23:48), five simultaneous changes (MCP port → stdio, env vars 11 → 3, subprocess env-vars → CLI args, all timeouts hardcoded, `start_service(model_id, model_path=None)` parameter override). This review checks that the restructure landed cleanly across both docs.

## Summary

- **Overall verdict**: **PASS-WITH-COMMENTS**
- **Files reviewed**: 2
- **Issues found**: 9 (0 blocker, 3 major, 6 minor)

The stdio-mode restructure landed cleanly. The grep verification confirms the legacy env-vars (`LOCAL_IMAGE_GEN_MCP_PORT`, `LOCAL_IMAGE_GEN_MCP_ALLOW_NONLOOPBACK`, `LOCAL_IMAGE_GEN_MODEL_MANIFEST`, `LOCAL_IMAGE_GEN_*_TIMEOUT`/`*_GRACE`) are completely gone from both docs — only the review-log entry mentions `LOCAL_IMAGE_GEN_START_TIMEOUT` historically, which is correct. The mermaid diagram correctly shows stdio (no MCP port arrow). Hardcoded timeout values (30/120/10/30 s) appear identically across both docs. FR-7 / FR-9 / NFR-4 / NFR-5 were rewritten consistently in both docs. The owner's skepticism about the 30 s start timeout is honestly acknowledged in both NFR-2 (step 1) and §8 risks (step 2).

The remaining issues are residue from the v3 → v4 / v1 → v2 jump: a couple of "manifest" references that survived in FR-1 even though the manifest is gone in v1, one semantic gap in `start_service` (model_path override vs single-service invariant), and a Chinese fragment accidentally retained in an English doc.

## Findings

### MAJOR

#### ARCH-V2-1 (MAJOR): FR-1 still references a "manifest" that does not exist in v1

- **File**: `01-requirements.md`:37 (FR-1 row)
- **Excerpt**: `MCP list_local_models returns one entry per model that the local model manifest recognizes. … Empty manifest returns an empty list and never errors.`
- **Issue**: Step 1 §8 Open Questions explicitly says "v1 is single-model (Z-Image-Turbo only, defined in §9)" and "Multi-model manifest. Deferred to v2". Step 2 §3.1 (line 81) says "v1 supports one model only: the model at `${LOCAL_IMAGE_GEN_MODEL_PATH}`". But FR-1's acceptance criteria still describe a manifest-discovery model with multi-entry semantics and "Empty manifest returns an empty list". In v1 there is no manifest file; `list_local_models` returns at most one entry (the model at the configured `LOCAL_IMAGE_GEN_MODEL_PATH`). The acceptance criteria cannot be met as written because there is no manifest to be empty or to recognize entries.
- **Suggested fix**: Rewrite FR-1's acceptance criteria to match v1 reality. Suggested text:
  > MCP `list_local_models` returns one entry: `{model_id: "z-image-turbo", current_load_status}` where `current_load_status ∈ {not_loaded | loading | loaded}`. If `LOCAL_IMAGE_GEN_MODEL_PATH` does not point to a valid model directory, the tool returns an empty list `[]` (the operator has not configured a model to be loadable) — never an error. `current_load_status` is computed from the live PID-and-meta files intersecting with the configured model path (single-service invariant ⇒ at most one of `loading`/`loaded`).
  Also drop "Empty manifest returns an empty list" wording in favor of "Empty / unset `LOCAL_IMAGE_GEN_MODEL_PATH` returns an empty list".

#### ARCH-V2-2 (MAJOR): `start_service` invariant vs `model_path` override — ambiguous semantics

- **File**: `01-requirements.md`:39 (FR-3 row); cross-ref `02-architecture.md`:83 (§3.2 start_service signature)
- **Excerpt**: `start_service(model_id, model_path=None) launches a model-server subprocess bound to an OS-assigned free port. In v1, if any model-service is already running, start_service does not start a new process — it returns the existing service record (global single-service invariant, regardless of model_id). model_path defaults to the value of the LOCAL_IMAGE_GEN_MODEL_PATH env var (default …); a non-None model_path argument overrides the env var for this call only.`
- **Issue**: The single-service invariant and the per-call `model_path` override coexist without an explicit precedence rule for the conflict case. Three possible readings:
  1. The override is silently dropped — `start_service` returns the existing record even if the caller's `model_path` would point at a different model on disk. (Most consistent with FR-8.)
  2. The override triggers an error — caller-supplied `model_path` ≠ `LOCAL_IMAGE_GEN_MODEL_PATH` already recorded in the live PID-and-meta file → return `{error: ...}`.
  3. The override is "for this call only" in the sense that *if the service needs to be started*, use the override; if a service is already running, the override is irrelevant.
  None of the three is spelled out. With v1 single-model semantics this is largely a theoretical concern, but the architecture doc carries it forward into the `start_service` signature at §3.2 without disambiguating.
- **Suggested fix**: Add one sentence to FR-3 (and mirror in step 2 §3.2): "If a service is already running, the `model_path` argument is ignored — the existing service record is returned as-is (FR-8 single-service invariant takes precedence over the `model_path` override; the override applies only when a new process is actually spawned)." Alternatively, document this as a future v2 concern and add a TODO to §8 Open Questions.

#### ARCH-V2-3 (MAJOR): Operator-facing invocation form disagrees between step 1 §7 and step 2 §7

- **File**: `01-requirements.md`:65 (§7 Users / actors — Operator entry) vs `02-architecture.md`:153 (§6 Tech stack — Packaging row) vs `02-architecture.md`:165–169 (§7 mcp_servers config example)
- **Excerpt (step 1 §7)**: `configures the agent (typically in the OpenClaw mcp_servers config) to spawn mcp_server.py with three env vars`
- **Excerpt (step 2 §6)**: `entry point: local-image-gen-mcp (stdio, invoked by agent). The model-server is launched as a subprocess from inside mcp_server, not as a separately-installed CLI.`
- **Excerpt (step 2 §7 example)**: `"args": ["-m", "local_image_gen.mcp_server"]`
- **Issue**: Three different invocation forms mentioned:
  - step 1 §7: `mcp_server.py` (suggests `python3 local_image_gen/mcp_server.py`)
  - step 2 §6: `local-image-gen-mcp` (console-script entry point declared in `pyproject.toml`)
  - step 2 §7 example: `python3 -m local_image_gen.mcp_server`
  All three happen to load the same module, but the operator reading step 1 §7 and configuring OpenClaw `mcp_servers` may pick the file-path form, which depends on the working directory and the `local_image_gen/` package layout. The JSON example in step 2 §7 is the canonical recommendation; step 1 §7 should match.
- **Suggested fix**: In step 1 §7, change `to spawn mcp_server.py` to `to spawn the MCP server via the console-script entry point local-image-gen-mcp (or, equivalently, python3 -m local_image_gen.mcp_server)`. Pick one as canonical in step 2 §6 and make sure step 1 §7 and the §7 example agree.

### MINOR

#### ARCH-V2-4 (MINOR): Step 2 §2 Module list retains "Long-lived MCP server" phrasing

- **File**: `02-architecture.md`:46
- **Excerpt**: `Long-lived MCP server: exposes the five MCP tools, tracks running model-services, spawns / signals / cleans up model-server subprocesses.`
- **Issue**: The review prompt specifically flagged this phrasing for inspection. In context it's defensible — the MCP server's lifetime equals the agent's, which may be long. But the spirit of the stdio-restructure is "agent-spawned, lifetime-bound, no independent existence". The phrase "long-lived" is the exact term used to describe a port-mode MCP server that runs as a daemon. Either rephrase to "Agent-spawned MCP server" (matching §1's `subgraph MCP["MCP server - agent-spawned stdio"]`) or add a parenthetical clarifying "long-lived relative to the agent session, not relative to the host".
- **Suggested fix**: Change to `Agent-spawned MCP server (lifetime = agent's lifetime): exposes the five MCP tools …`.

#### ARCH-V2-5 (MINOR): Spurious Chinese fragment "mcp走stdio模式" in English prose

- **File**: `02-architecture.md`:159
- **Excerpt**: `- **Config / env vars (only three, per owner decision 2026-06-28 23:39 — mcp走stdio模式):**`
- **Issue**: A Chinese-language fragment ("MCP走stdio模式" → "MCP goes to stdio mode") from the owner's verbal direction was left in the doc body as a parenthetical. It does not affect technical correctness but reads as unprofessional documentation leakage.
- **Suggested fix**: Replace with an English parenthetical: `- **Config / env vars (only three, per owner decision 2026-06-28 23:39 — MCP transport set to stdio mode):**`.

#### ARCH-V2-6 (MINOR): Glossary lacks a "model_id" entry — the new `start_service(model_id, model_path=None)` signature introduces an identifier not previously named

- **File**: `01-requirements.md`:75–86 (§9 Glossary)
- **Issue**: With the new `start_service(model_id, model_path=None)` signature in v4, `model_id` is a first-class identifier that the caller picks. But the §9 Glossary has entries for Model, Model-server, MCP server, Service id, PID-and-meta file, Stale PID-and-meta file — and no entry for `model_id` or `model_path`. The relationship "model_id is a logical name (in v1 always `z-image-turbo`); model_path is the on-disk directory the pipeline loads from" is not documented. The Glossary already has an entry for "Service id" (a v1 concept); it should also have one for model_id / model_path.
- **Suggested fix**: Add two entries to §9:
  > - **model_id** — a logical string identifier for a model (in v1 always `z-image-turbo`). Used as a key in `list_local_models` output and as the `model_id` parameter to `start_service`. Independent of `model_path` (the on-disk directory).
  > - **model_path** — the absolute on-disk directory containing the diffusers-format model weights. Read from `LOCAL_IMAGE_GEN_MODEL_PATH` by default; overridable per-call via `start_service(..., model_path=...)`. With `local_files_only=True`, the model-server fails to start if the directory is missing or malformed.

#### ARCH-V2-7 (MINOR): No integration test for "zombie model-server on forced SIGKILL"

- **File**: `02-architecture.md`:131–136 (§5 dir tree); cross-ref `02-architecture.md`:188 (§8 risks — "Agent exit while model-server is running leaves a zombie model-server with no PID file")
- **Excerpt (risk row)**: `v1: model-server becomes orphan if the MCP server is killed forcibly (SIGKILL) — operator must pgrep -f model_server.py and kill manually. v2: model-server could detect parent-death and self-terminate.`
- **Issue**: §8 risks documents a known operational gap (model-server orphan on forced MCP server kill) and lists operator manual cleanup as v1 mitigation. But there is no integration test exercising this path. The three integration tests in §5 (`test_spawn_lifecycle.py`, `test_global_single_service.py`, `test_stdio_transport.py`) cover happy-path and stdio-transport, not the failure mode that is explicitly called out as a risk.
- **Suggested fix**: Either add `tests/integration/test_orphan_recovery.py` documenting the manual-recovery procedure as a regression test, or downgrade the risk row's likelihood from "low" to "very low" and remove the manual-recovery text in favor of a one-line note in README. At minimum, add a TODO entry to §8 Open Questions in step 1.

#### ARCH-V2-8 (MINOR): State-directory creation failure path not spelled out

- **File**: `02-architecture.md`:102 (§3.2 mcp_server startup)
- **Excerpt**: `On startup: validates state directory (mkdir -p if missing), prunes stale PID-and-meta files, validates LOCAL_IMAGE_GEN_MODEL_PATH exists (fail-fast on misconfig).`
- **Issue**: The MCP server validates that `LOCAL_IMAGE_GEN_MODEL_PATH` exists, but the validation for `LOCAL_IMAGE_GEN_STATE_DIR` only mentions `mkdir -p if missing` — no failure mode spelled out for the case where `mkdir` fails (e.g., permissions, parent dir not writable). With the MCP server's stderr-only logging (NFR-4) and stdio transport (FR-7), a startup failure here produces an error line on the operator's stderr. This is acceptable but the doc doesn't say so.
- **Suggested fix**: Add a clause: `On startup: validates state directory (mkdir -p if missing; fail-fast with a stderr-logged error if mkdir fails). Prunes stale PID-and-meta files. Validates LOCAL_IMAGE_GEN_MODEL_PATH exists (fail-fast on misconfig, stderr-logged).`

#### ARCH-V2-9 (MINOR): Model-server stdout / uvicorn stdout interleaving risk noted but not documented

- **File**: `02-architecture.md`:69 (§3.1 model-server logging) + `02-architecture.md`:157 (§7 cross-cutting logging)
- **Excerpt**: `Logs one JSON line per lifecycle event to stdout (NFR-4 — note this is the model-server's own stdout; the MCP server redirects it to its own stderr for unified log capture).`
- **Issue**: When the model-server is run *standalone* (per §3.1 line 72 "It can be run standalone for development by invoking it with the same CLI args"), uvicorn's default access logs also go to stdout. The doc says the JSON lifecycle lines go to stdout but doesn't mention uvicorn's logs will interleave. This is purely an ergonomics issue for the standalone-dev case; not a correctness issue.
- **Suggested fix**: Add a sentence to §7 logging: `When the model-server runs standalone (dev), uvicorn access logs interleave with the JSON lifecycle lines on stdout. Production (MCP-spawned) routing is unaffected — uvicorn stdout is redirected to the MCP server's stderr by the subprocess.Popen plumbing (see §4).`

## Cross-document check

- ✅ Goal 4 (step 1, stdio mode) is consistent with FR-7 (stdio) and step 2 §1 mermaid (`Agent -->|spawn subprocess stdin stdout JSON-RPC| MCPServer`) and step 2 §3.2 (`stdio transport (FR-7)`).
- ✅ Goal 5 (step 1, MCP lifetime = agent's) is consistent with FR-9 (step 1) and step 2 §3.2 (`On stdin EOF / agent process exit (FR-9)`) and step 2 §8 risks (`Agent exit while model-server is running leaves a zombie…`).
- ⚠ Goal 4 wording in step 1 (`The agent discovers the MCP server only by being configured to spawn it`) is satisfied by step 2 §7's mcp_servers JSON example. ✓
- ⚠ FR-3 (step 1) describes `start_service(model_id, model_path=None)`; step 2 §3.2 mirrors the signature exactly. ✓ (But see ARCH-V2-2 about the model_path-vs-invariant interaction.)
- ⚠ FR-4 (step 1, serialized FIFO invoke) is consistent with step 2 §3.2 `Serialized FIFO per FR-4 / FR-8`.
- ⚠ FR-5 (step 1, SIGTERM with 10 s grace) is consistent with step 2 §3.2 `SIGTERM the subprocess, fall back to SIGKILL after the hardcoded 10 s grace period`.
- ⚠ FR-7 (step 1, stdio mode) is referenced by step 2 in: §3.1 (implicitly, via `Local files only` design), §3.2 (explicit `stdio transport (FR-7)`), §4 (implicit), §7 (explicit `stdout is reserved for the JSON-RPC stream — FR-7`). All references correct.
- ⚠ FR-9 (step 1, stdin EOF / agent exit shutdown) is referenced by step 2 §3.2 (`On stdin EOF / agent process exit (FR-9)`) and step 2 §8 risks (`stdio mode ⇒ MCP server usually exits cleanly when agent exits`). ✓
- ⚠ NFR-2 (step 1, 30 s start timeout + owner skepticism) is consistent with step 2 §3.1 (line 67) and step 2 §8 risks (line 184, "Owner has noted skepticism about the 30 s default; revisit at v1 implementation time"). ✓
- ⚠ NFR-4 (step 1, MCP server logs to stderr) is consistent with step 2 §3.1 (model-server writes to its own stdout, redirected by MCP server) and step 2 §7 cross-cutting logging. ✓
- ⚠ NFR-5 (step 1, "loopback-binding and non-loopback-binding policies are moot") is consistent with step 2 §2, §3.2, §7 — no loopback policy referenced anywhere in step 2.
- ⚠ §7 Operator (step 1, "spawn mcp_server.py with three env vars") — three env vars listed correctly (BEARER_TOKEN, STATE_DIR, MODEL_PATH). But the form `mcp_server.py` disagrees with step 2 §6 (`local-image-gen-mcp`) and §7 (`python -m local_image_gen.mcp_server`). See ARCH-V2-3.
- ⚠ §9 Glossary (step 1, "MCP server — Communicates with the agent over JSON-RPC on stdin/stdout; its lifetime equals the spawning agent's lifetime. Has no listening port and no network socket") is consistent with FR-7 and step 2 §3.2. ✓ No "fixed port" or other legacy concept leaks in. ✓
- ⚠ Step 2 §1 mermaid: `Agent -->|spawn subprocess stdin stdout JSON-RPC| MCPServer` — correctly shows stdio, no MCP port arrow. `MCPServer -->|subprocess Popen CLI args write PID| ModelSrv` — correctly shows MCP server → model-server via subprocess + PID file. `Operator -->|mcp_servers config spawn args| Agent` — correctly shows operator configures agent. ✓
- ⚠ Step 2 §3.1 CLI args list (`--service-id --model-id --model-path --bearer-token --state-dir`) matches step 2 §4 (`--service-id <uuid> --model-id <id> --model-path <absolute path> --bearer-token <token> --state-dir <dir>`). ✓
- ⚠ Step 2 §7 env vars table lists exactly the three env vars (`BEARER_TOKEN`, `STATE_DIR`, `MODEL_PATH`) with correct defaults. ✓
- ⚠ Step 2 §8 risks has a stdio-pipe-backpressure row, an "Agent exit while model-server is running" row referencing stdio mode — both unique to the v2 restructure. ✓

## Grep verification

```bash
$ grep -n "LOCAL_IMAGE_GEN_MCP_PORT" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "LOCAL_IMAGE_GEN_MCP_ALLOW_NONLOOPBACK" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "LOCAL_IMAGE_GEN_MODEL_MANIFEST" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "LOCAL_IMAGE_GEN_START_TIMEOUT" 01-requirements.md 02-architecture.md
# (no matches in either file; only mentioned historically in reviews/review-log.md)

$ grep -n "LOCAL_IMAGE_GEN_INVOKE_TIMEOUT" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "LOCAL_IMAGE_GEN_RELEASE_GRACE" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "LOCAL_IMAGE_GEN_SHUTDOWN_TIMEOUT" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "MCP_PORT" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n "MCP_ALLOW" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n -i "fixed port" 01-requirements.md 02-architecture.md
# (no matches in either file)

$ grep -n -i "loopback" 01-requirements.md 02-architecture.md
01-requirements.md:57:| NFR-5 | security | Bearer-token auth | … so loopback-binding and non-loopback-binding policies are moot. …
# (single intentional reference: NFR-5 explicitly notes loopback policy is now moot because there is no network listener. This is the correct, expected reference — not a residual leak.)

$ grep -n -i "manifest" 01-requirements.md 02-architecture.md
01-requirements.md:37:| FR-1 | List loadable local models | must | MCP list_local_models returns one entry per model that the local model manifest recognizes. … Empty manifest returns an empty list and never errors.
01-requirements.md:72:- [ ] Multi-model manifest. Deferred to v2; v1 is single-model (Z-Image-Turbo only, defined in §9).
01-requirements.md:77:- Model — a loadable image generation pipeline. v1 supports Z-Image-Turbo only … Multi-model manifest is deferred to v2 (see §8 Open Questions).
02-architecture.md:81:- v1 supports one model only: the model at ${LOCAL_IMAGE_GEN_MODEL_PATH} … Multi-model discovery from a manifest is deferred to v2 (step-1 §8 Open Questions).
02-architecture.md:113:- No persistence beyond state dir. … and the model manifest.
# (three intentional references in §8 Open Questions + Glossary + step 2 §3.1, all correctly framed as deferred-to-v2; one residual leak in FR-1 acceptance criteria — see ARCH-V2-1; one stale reference at step 2 §4 line 113 "and the model manifest" — see ARCH-V2-10 below.)

$ grep -n -i "long-lived" 01-requirements.md 02-architecture.md
02-architecture.md:46:| 2 | local_image_gen.mcp_server | Long-lived MCP server: exposes the five MCP tools, tracks running model-services, spawns / signals / cleans up model-server subprocesses. | new |
# (single reference — see ARCH-V2-4)
```

#### ARCH-V2-10 (MINOR, found during grep): Step 2 §4 line 113 says "the model manifest" — leftover from before the restructure

- **File**: `02-architecture.md`:113
- **Excerpt**: `The state dir holds only the PID-and-meta file for the current service (v1 single-service ⇒ at most one file at a time) and the model manifest.`
- **Issue**: There is no "model manifest" file in v1 (manifest is deferred to v2 per §8 Open Questions). Step 2 §3.1 line 81 confirms "v1 supports one model only: the model at `${LOCAL_IMAGE_GEN_MODEL_PATH}`". The `and the model manifest` clause is residual.
- **Suggested fix**: Drop the clause. Suggested text: `The state dir holds only the PID-and-meta file for the current service (v1 single-service ⇒ at most one file at a time). The model itself lives under the model cache path (default `/home/cxt/.cache/modelscope/hub/models/Tongyi-MAI/Z-Image-Turbo`), separate from the project root and from the state dir.`

## Recommendations

1. **Address ARCH-V2-1 and ARCH-V2-3 before Gate 2** — both are externally-visible inconsistencies (operator-facing text and FR acceptance criteria) that an implementer or operator could trip over.
2. **ARCH-V2-2 can be deferred to Gate 2 review** — it's a semantic ambiguity that affects a corner case (override + service already running) which is unlikely to occur in v1 single-model practice.
3. **ARCH-V2-4, V2-5, V2-6, V2-7, V2-8, V2-9, V2-10 are polish items** — fix at next doc touch-up pass; they don't block Gate 2.

## What the docs got right

- Hardcoded timeout values (30 s start, 120 s invoke, 10 s release grace, 30 s shutdown) appear identically and consistently across both docs, in the right FR/NFR rows and the right architecture sections.
- The owner's skepticism about 30 s is honestly acknowledged in NFR-2 (step 1) and §8 risks (step 2). Not papered over, not silently changed.
- Mermaid diagram accurately reflects stdio mode — no MCP port, no listening socket arrow, agent → MCPServer via `spawn subprocess stdin stdout JSON-RPC`.
- The §5 dir tree includes `test_stdio_transport.py` covering stdio transport integration. This is new in v2 and is the right shape.
- The owner-decision timestamps in the v1 design-constraints block (line 10–11) correctly reference 2026-06-28 23:39, matching the review-log entry for this restructure.
- NFR-5 is rewritten correctly: "loopback-binding and non-loopback-binding policies are moot" is the right framing — there is no listener at all, so the previous policy question dissolves. The single `loopback` reference in the doc body (NFR-5 row) is the intentional "this concern is moot" note, not a residual leak.
- The mcp_servers config JSON example in step 2 §7 is the right shape (command + args + env), and the three env vars in the example match the three env vars in the prose.

**Verdict: PASS-WITH-COMMENTS.** Three MAJOR items should be addressed before Gate 2 (FR-1 manifest residue, `start_service` override semantics, operator invocation form). The structural rest of the restructure is solid.