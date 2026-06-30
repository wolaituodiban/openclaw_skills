# Architecture Review (draft, incomplete): `local-image-gen` (02-architecture.md)

> ⚠️ **Status: incomplete**. Sub-agent (`bec0752d`) timed out (3m17s, `FailoverError`).
> The partial findings below are from the sub-agent's truncated reasoning trace.
> Manual verification of each finding is included; the full review is pending rerun or owner-decision to skip Gate 1 re-run.

**Sub-agent**: `agent:main:subagent:bec0752d-e9da-46f1-a15b-3ec5b756822d`
**Run-id**: `39ddee83-f0cb-4f03-9d26-cf28535422c0`
**Date**: 2026-06-28T16:09+08:00

## Findings (partial, manually verified)

### ARCH-1 — PID-and-meta file authorship is internally inconsistent (BLOCKER)

**Problem**: `02-architecture.md` contradicts itself about who writes the PID-and-meta file.

| Location | Says who writes | Says when |
|---|---|---|
| §1 line 32 (diagram) | MCP server | "spawn subprocess + write" |
| §3.1 line 63 (model-server interface) | model-server | "On startup, writes one PID-and-meta file" |
| §3.2 line 79 (start_service) | ambiguous ("writes") | "Spawns subprocess, polls /health... writes PID-and-meta file" |
| §3.2 line 87 (release_service) | MCP server (implied) | "Removes the PID-and-meta file" |
| §3.2 line 92 (MCP SIGTERM) | MCP server (implied) | "removes its PID-and-meta file" |
| §4 line 99 | model-server | "the PID-and-meta file the model-server writes on /health reporting ready (or sooner, on bind)" |
| §4 line 100 | MCP server | "MCP server... writes it to every PID-and-meta file it spawns" |
| §8 risk 2 (line 166) | MCP server | "MCP server only writes the PID-and-meta file AFTER /health returns ready" |

**Why blocker**: The spawn lifecycle (subprocess → bind port → write PID file → /health ready → MCP server returns to caller) is the spine of the project. If the doc cannot state unambiguously who writes the file, when, and how atomicity is guaranteed, the test-design step (step 4) cannot enumerate failure modes and the per-module code (step 6) cannot be implemented.

**Manual suggestion**: Pick one writer. Recommended: **model-server writes** (rationale: model-server knows its own pid, port, and is the only entity that can report a self-consistent atomic {pid, port, started_at} snapshot — MCP server learns pid via Popen object, but learns port only via the PID file, so MCP server cannot be the first writer). Lock in §3.1, §3.2, §4, §8 in one edit pass. Update diagram (line 32) to remove "write PID-and-meta" from MCP server's edge labels.

### ARCH-2 — start_service success/failure paths under-specified (MAJOR)

**Problem**: §3.2 line 79 (start_service) describes the success path (spawn → poll /health → write PID-and-meta) but does not enumerate the failure paths that FR-3 explicitly requires.

**FR-3 failure modes (from `01-requirements.md` line 39)**: timeout, subprocess terminated, no PID-and-meta file written, timeout error returned.

**What's missing**:
- Model artifact not loadable (e.g. `modelscope download` not run) → error code?
- Subprocess crashes before /health reaches `ready` → error code, who cleans up?
- Port exhaustion (MCP tries to bind but kernel returns EADDRINUSE) → N/A here since model-server picks dynamic port, but should be stated
- Bearer-token mismatch (env var not propagated) → ??
- State dir not writable → fail-fast at MCP startup, but what if it becomes unwritable after start?

**Manual suggestion**: Add to §3.2 under start_service:
```
Failure modes:
- `LOCAL_IMAGE_GEN_START_TIMEOUT` exceeded → {error: {code: "start_timeout", message: "..."}}. Subprocess terminated (SIGTERM then SIGKILL after 5s). No PID-and-meta file written.
- Subprocess exits non-zero before /health=ready → {error: {code: "subprocess_exit", message: "...", exit_code: int}}. No PID-and-meta file written.
- Model artifact missing → {error: {code: "model_not_loaded", message: "..."}}. Same cleanup.
- State dir not writable → {error: {code: "state_dir_error", message: "..."}}.
```

### ARCH-3 — Tool error shape inconsistency (MINOR)

**Problem**: §3.2 line 77/83/86 declare return type `{error: str}` for three tools, but §7 line 146 (cross-cutting decisions) says "MCP server returns MCP-shaped tool errors with a structured `error` field containing `code` and `message`."

**Manual suggestion**: Either change §3.2 to `{error: {code: str, message: str}}` (recommended — aligns with §7 and makes error codes machine-parseable), or change §7 to match the string form (not recommended — loses structure).

## Pending review work

The sub-agent timed out before completing:
- Full issue enumeration (only 3 of presumably more findings captured)
- Requirements coverage table (FR-1..FR-9 / NFR-1..FR-8)
- Two-module fit check (whether shared concerns warrant a third module)
- Severity re-classification with full doc context

**Decision needed**:
- **Option A**: Re-spawn sub-agent (potentially with a simpler prompt or different model) to complete the full review.
- **Option B**: Owner manually reviews these 3 findings as Gate 1 proxy, then I edit the doc, then Gate 2.
- **Option C**: Extend this draft to a full review manually (loses the Gate 1 = different-LLM-perspective guarantee).