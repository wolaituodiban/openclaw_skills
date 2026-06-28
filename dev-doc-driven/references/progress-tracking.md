# Progress tracking (resumability)

Long workflows get killed: session timeout, gateway restart, the user walks away for 12 hours, the model context fills up. The doc files survive, but the agent's running understanding of "where we are right now" does not. This document is the canonical reference for the memory-backed progress mirror that solves that.

Load this file:
- on the first step of a new workflow (so the initial progress record is created with the right shape), and
- at the start of every new session that resumes an active workflow (so the resume protocol runs).

## 1. The progress record

The progress record is a single `memory/dev-doc-progress/<project>.md` file — one per active project. Its **structure mirrors `dev-doc/05-dev-plan.md`** (or `99-dev-plan.md` for recursive sub-trees): one row per module, in dev plan order, with a status field.

`<project>` is the same slug the user already uses for the project directory; for the URL shortener example, the file path is `memory/dev-doc-progress/shorturl.md`.

## 2. Progress record schema (template)

```markdown
# Dev-doc progress: <project name>

> Mirror of `dev-doc/05-dev-plan.md`. Update this file at every state transition.
> Last updated: <ISO timestamp>

## Overall status

- Current step: <1 | 2 | 3 | 4 | 5 | 6>
- Current module: <module name or "—">
- Next action: <one-line: "draft 01-requirements.md" / "write code for module 2" / "wait for human review of 02-architecture" / ...>

## Module status

| # | Module | Artifacts | Sub-agent | Human | Code | Tests | Notes |
|---|--------|-----------|-----------|-------|------|-------|-------|
| 1 | <module-a> | design ✓, test-design ✓ | ✓ | ✓ | ✓ | ✓ | done |
| 2 | <module-b> | design ✓, test-design ✓ | ✓ | ✓ | ☐ | ☐ | code not started |
| 3 | <module-c> | design ☐ | — | — | — | — | — |

## Pending review gates

- <artifact path> | waiting on <sub-agent | human> | since <ISO timestamp>

## Last completed action

<ISO timestamp> — <one-line description of what just happened>

## Next session checklist

1. Re-read `dev-doc/05-dev-plan.md` to confirm the plan has not changed.
2. Re-read this file to confirm where the workflow paused.
3. If "next action" is blocked on the user, surface the pending artifact and ask for review.
4. Otherwise resume the next action.
```

## 3. Field semantics

- **Artifacts** — which `03/04` design docs exist for the module. Free-form list of: `design`, `test-design`, with `✓` for present.
- **Sub-agent** — whether the sub-agent review of all design docs is PASS. `✓` / `☐` / `—`.
- **Human** — whether the human review of all design docs is PASS. `✓` / `☐` / `—`.
- **Code** — whether the module's source files (named in `02-architecture.md §5`) exist and have cleared the review gate. `✓` / `☐` / `—`.
- **Tests** — whether the module's test files (named in `02-architecture.md §5` and `04-test-design.md`) exist, pass locally, and have cleared the review gate. `✓` / `☐` / `—`.
- **Notes** — free-form; e.g. "blocked on user's framework choice", "needs sub-agent re-review after collision-retry logic change".

Icon vocabulary (do not invent new ones):
- `✓` — PASS / complete / approved.
- `☐` — not started, or in-progress but not yet past the relevant gate.
- `—` — not applicable yet (a later step depends on an earlier one).

## 4. When to update the progress record

Update `memory/dev-doc-progress/<project>.md` at every one of these transitions:

1. After step 1–5 produces an artifact, before requesting sub-agent review.
2. After sub-agent review returns PASS.
3. After human review returns PASS and the artifact is logged to `review-log.md`.
4. After a module's code is written and tests are green, before requesting the module's review gate.
5. After a module's review gate is fully passed (sub-agent + human on code + tests).
6. Whenever the user changes scope, the plan, or the architecture mid-flight.

The rule of thumb: **if the workflow would be confused about where to resume after a session kill, the progress record is not current — fix it before continuing.**

## 5. Resume protocol at session start

When a new session starts (or when the agent wakes up after a long gap), and a progress record exists for the active project, run these steps in order before doing anything else:

1. **Read the progress record.** `memory/dev-doc-progress/<project>.md`.
2. **Read the plan.** `dev-doc/05-dev-plan.md` (and any `99-dev-plan.md` for active recursive sub-trees). Confirm the plan is unchanged since the record was last updated.
3. **Read the most recent review-log entries.** `dev-doc/review-log.md` (last 10 lines is usually enough). Confirm what is already approved.
4. **State the resume point in one line.** Example: "Resuming: writing `shorturl/storage.py` for module 1, code-review not yet requested." Then proceed.

If the progress record and the dev plan disagree (e.g. the user added a module mid-flight without updating the plan), the plan is the source of truth — update the progress record, do not silently follow the stale record.

## 6. Conflict resolution

Two sources of truth can drift apart:
- **Progress record is ahead of the plan** — you started work that the plan doesn't list. Stop, update the plan, mirror it back to the record.
- **Progress record is behind the plan** — the user updated the plan mid-flight (added a module, reordered, removed one). Update the record to match the plan before continuing.

Either way: **the plan wins.** The record is a mirror, not the source of truth.

## 7. When not to write a progress record

- The workflow is in step 1 and no artifact exists yet — nothing to mirror. The record may be created on first transition, not at the very start.
- The workflow finished (all modules approved) — write a final "complete" line in the next heartbeat or daily memory note; no need to keep updating the table.

In both cases, the absence of a record is fine and expected.

## 8. Worked example

Below is the progress record for the URL shortener at a moment when module 1 (`shorturl.storage`) is fully done and module 2 (`shorturl.service`) design is in sub-agent review. This is the kind of state a session kill might leave behind.

```markdown
# Dev-doc progress: shorturl

> Mirror of `dev-doc/05-dev-plan.md`. Update this file at every state transition.
> Last updated: 2026-06-28T12:18:00+08:00

## Overall status

- Current step: 6
- Current module: shorturl.service
- Next action: wait for sub-agent review of `shorturl/service.py` + `tests/unit/test_service.py`, then apply fixes

## Module status

| # | Module | Artifacts | Sub-agent | Human | Code | Tests | Notes |
|---|--------|-----------|-----------|-------|------|-------|-------|
| 1 | shorturl.storage | design ✓, test-design ✓ | ✓ | ✓ | ✓ | ✓ | done — review-log has 2 PASS lines |
| 2 | shorturl.service | design ✓, test-design ✓ | ✓ | ✓ | ✓ | ✓ | code + tests written, sub-agent review in flight |
| 3 | shorturl.api | design ☐ | — | — | — | — | blocked on module 2 review |
| 4 | shorturl.cli | design ☐ | — | — | — | — | — |

## Pending review gates

- shorturl/service.py | waiting on sub-agent | since 2026-06-28T12:17:30+08:00
- tests/unit/test_service.py | waiting on sub-agent | since 2026-06-28T12:17:30+08:00

## Last completed action

2026-06-28T12:17:30+08:00 — wrote `shorturl/service.py` and `tests/unit/test_service.py`; both files exist; pytest suite green locally.

## Next session checklist

1. Re-read `dev-doc/05-dev-plan.md` to confirm the plan has not changed.
2. Re-read this file to confirm where the workflow paused.
3. If "next action" is blocked on the user, surface the pending artifact and ask for review.
4. Otherwise resume the next action.
```

A fresh session reading this record knows exactly: "I am in step 6, module 2; code and tests are written and green; I'm waiting for sub-agent review to come back." No re-derivation, no guessing.

## 9. Anti-patterns

- **Updating the record after every sentence.** Batch within a transition — one update per "what just happened" milestone, not per tool call.
- **Letting the record diverge silently from the plan.** If you find yourself wanting to write something that isn't in the plan, stop and update the plan first.
- **Writing the record from scratch each session.** Always edit in place; preserve the audit trail (the timestamps tell a story).
- **Skipping the record because "this is a short task".** The shorter the task, the more likely it is to be killed mid-way.