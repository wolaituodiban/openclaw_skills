---
name: "dev-doc-driven"
description: "Document-driven software development: plan, design, and implement projects with sub-agent and human review gates between artifacts."
---

# dev-doc-driven

Document-first software development workflow. For every non-trivial project, produce a chain of design documents under `project/dev-doc/` **before** writing any code. Each document and each source file is gated by both a sub-agent review and a human review; do not proceed until both pass.

## When to use

Trigger when the user asks to start, scaffold, plan, or structure a new software project, module, or substantial feature. Do **not** trigger for one-line fixes, single-file scripts, or pure research / explanation tasks.

## Hard rules

1. **No code before the full doc chain is approved.** Step 5 (dev plan) is the last thing that exists before the first source file.
2. **Every artifact gets two reviews in order: sub-agent → human.** Sequence matters: the sub-agent goes first so the human does not waste time on obvious gaps.
3. **One module fully done — code + tests — before the next module starts.** The dev plan is the unit of parallelism, not the agent's whim.
4. **Sub-module recursion is allowed and encouraged.** If a module's design doc would exceed ~500 lines or mix unrelated concerns, drop into a full sub-tree (requirements → architecture → sub-module design → sub-module test design → sub-dev-plan → code) under that module's folder. Same review gates apply at every level.
5. **Few-shot examples are loaded from `assets/examples/`, not invented.** Read the corresponding example document before drafting. Mirror its structure, depth, and prose style — do not invent a new schema.
6. **Project directory structure is the agent's responsibility.** At step 1 the agent creates `project/dev-doc/` and the per-module sub-folders. The user does not pre-create them.
7. **Sub-agent review runs in an isolated session.** Use `sessions_spawn` with no `context` (clean child), pass the artifact path + a "review against this example" brief. Do not fork the parent transcript into the reviewer.
8. **Dev progress is mirrored to memory so an aborted session can resume.** Schema, field semantics, update rules, and resume protocol live in `references/progress-tracking.md`; load that doc when you first start the workflow or when a session resumes.

## Glossary

These terms appear throughout the example documents. Use the long form in user-facing prose; the short IDs are fine inside the requirement tables for cross-referencing.

- **Functional requirement (FR)** — a requirement that describes **what** the system does. One row per behavior. Stable ID `FR-1`, `FR-2`, … so architecture / module / test documents can reference them later.
- **Non-functional requirement (NFR)** — a requirement that describes **how well** the system does it. Performance, reliability, security, observability, accessibility — qualities of behavior, not behavior itself. Stable ID `NFR-1`, `NFR-2`, …
- **Code** — the short identifier the service hands back. (Specific to the URL shortener example; replace per project.)
- **Mapping** — the stored record that links the short identifier to the original value. (Specific to the URL shortener example.)
- **Artifact** — any document, source file, or test file produced by the workflow. Every artifact goes through the review gate.
- **Review gate** — the fixed sub-agent → human → log sequence that every artifact must pass before the workflow advances.
- **Progress record** — the `memory/dev-doc-progress/<project>.md` mirror of the dev plan. See `references/progress-tracking.md`.

## Directory layout

```
project/
└── dev-doc/
    ├── 01-requirements.md
    ├── 02-architecture.md
    ├── 05-dev-plan.md
    ├── review-log.md
    ├── <module-a>/
    │   ├── 03-design.md
    │   └── 04-test-design.md
    ├── <module-b>/
    │   ├── 03-design.md
    │   └── 04-test-design.md
    └── <complex-module>/              ← recursive sub-tree
        ├── 01-requirements.md
        ├── 02-architecture.md
        ├── 99-dev-plan.md
        ├── <submodule-a>/
        │   ├── 03-design.md
        │   └── 04-test-design.md
        └── <submodule-b>/
            ├── 03-design.md
            └── 04-test-design.md
```

Top-level modules sit directly under `dev-doc/` (no extra `modules/` wrapper). A complex module just gets its own sub-tree in place of its `03/04` pair.

## The six steps

- **Step 1 — Requirements.** `01-requirements.md`. Read `assets/examples/01-requirements.md` first. State **what**, not how. Functional requirements, non-functional requirements, scope, acceptance criteria. Stop here. Do not think about modules yet.
- **Step 2 — Architecture.** `02-architecture.md`. Read `assets/examples/02-architecture.md` first. Architecture diagram, module list, per-module public interface, inter-module connections, project directory tree (files/folders to add or modify, named), tech stack.
- **Step 3 — Module design.** For each module: `dev-doc/<module>/03-design.md`. Read `assets/examples/03-module-design.md` first. Pseudocode-level spec of classes/methods/functions: signature, parameters, output, behavior, call-relationship. No real code.
- **Step 4 — Module test design.** Paired 1:1 with step 3: `dev-doc/<module>/04-test-design.md`. Read `assets/examples/04-test-design.md` first. Unit tests per public function (every branch), integration tests per cross-module flow (every observable output).
- **Step 5 — Dev plan.** `05-dev-plan.md`. Read `assets/examples/05-dev-plan.md` first. Linear module order. A module's code + tests are both complete and reviewed before the next starts. Recursive sub-trees plan themselves.
- **Step 6 — Module-by-module code + test implementation.** For each module in dev plan order: write source files named in the architecture doc; write unit tests (`tests/unit/`, one file per source, one case per public function, every branch); write integration tests (`tests/integration/`) for cross-module flows; run the suite, fix until green; submit for sub-agent review → human review. Both pass → next module.

## Review gate protocol

Between every artifact (doc or code), run this exact sequence:

1. **Sub-agent review.** `sessions_spawn` with isolated context. Task: "Review `<path>` against `assets/examples/<n>-<name>.md`. Return: PASS or list of issues with file:line and severity (blocker / major / minor). Do not modify the file." Wait for completion.
2. **Apply sub-agent fixes.** Edit the artifact to address every blocker and major. Re-spawn reviewer if changes were substantial. Loop until sub-agent returns PASS.
3. **Human review.** Show the artifact + sub-agent verdict to the user. Wait for explicit approval. No "looks good, moving on" without a green light.
4. **Log the approval.** Append a one-liner to `dev-doc/review-log.md` (`<artifact> | sub-agent: PASS <ts> | human: PASS <ts>`).

Never skip a gate. Never combine gates. The point of two reviewers is two independent passes.

## When a module is too complex

Symptom: a step 3 design doc would exceed ~500 lines, or mixes concerns that don't share state.

Action: inside `dev-doc/<complex-module>/`, run steps 1–6 recursively. The module's `03-design.md` becomes a thin index pointing to sub-modules. The module's `99-dev-plan.md` sequences sub-modules. If a sub-module is itself too complex, recurse again. Depth is unbounded; clarity is not negotiable.

## Progress tracking (resumability)

Long workflows get killed: session timeout, gateway restart, the user walks away for 12 hours, the model context fills up. The doc files survive, but the agent's running understanding of "where we are right now" does not.

The fix: mirror the dev plan to `memory/dev-doc-progress/<project>.md` and update that mirror at every state transition. Schema, field semantics, update rules, resume protocol, and a worked example all live in `references/progress-tracking.md`. Load that doc:

- on the first step of a new workflow (so the progress record is created with the right shape), and
- at the start of every new session (so the resume protocol runs).

The hard rule in one sentence: **if the workflow would be confused about where to resume after a session kill, the progress record is not current — fix it before continuing.**

## What this skill does NOT do

- Does not write code outside of step 6.
- Does not pick a tech stack — the architecture doc records the choice, but the user makes it.
- Does not run the final integration test suite unattended — code goes green locally, but a human runs the full integration pass before declaring the project done.
- Does not retrofit existing code — if the project already has source files, scope the new work to a clean sub-tree or do not trigger this skill.
- Does not skip the progress-record update "because the session is short" — short sessions are exactly the ones that get killed.

## Quick start (for the agent)

When triggered:

1. Confirm scope with the user — one paragraph of what we're building. Stop if scope is fuzzy.
2. `mkdir -p project/dev-doc` for the active project.
3. Load `references/progress-tracking.md`; create the initial progress record in `memory/dev-doc-progress/<project>.md`.
4. For each step 1–5: read the matching `assets/examples/<n>-<name>.md`, draft the artifact, run review gates, log approval, update the progress record.
5. Step 6 begins only after step 5 is human-approved. Then module-by-module with the same gates; update the progress record at every transition.
6. At session end (timeout, explicit pause, or natural completion), confirm the progress record's "Last completed action" matches the most recent change.

## References

- `references/progress-tracking.md` — progress-record schema, field semantics, update rules, resume protocol, worked example (load on first step of a new workflow and at every session start)
- `assets/examples/01-requirements.md` — mock few-shot for step 1
- `assets/examples/02-architecture.md` — mock few-shot for step 2
- `assets/examples/03-module-design.md` — mock few-shot for step 3
- `assets/examples/04-test-design.md` — mock few-shot for step 4
- `assets/examples/05-dev-plan.md` — mock few-shot for step 5

The example project in `assets/examples/` is a URL shortener service — small enough to read in one sitting, real enough to show what "done" looks like at each stage. Replace it with a real-project few-shot when one becomes available.
