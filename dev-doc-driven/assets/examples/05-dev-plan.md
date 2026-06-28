# 05 — Dev plan: shorturl

Linear ordering of modules. The rule: a module's source code + tests are both complete and reviewed before the next module starts. The progress record in `memory/dev-doc-progress/shorturl.md` mirrors this plan's structure; updates to this file are mirrored there at every state transition. See `references/progress-tracking.md` for the record schema.

## 1. Modules in implementation order

| # | Module | Depends on | Recursive sub-tree? | Estimated complexity |
|---|--------|-----------|---------------------|----------------------|
| 1 | `shorturl.storage` | — | no | S |
| 2 | `shorturl.service` | module 1 (only the Protocol) | no | M |
| 3 | `shorturl.api` | modules 1 + 2 | no | M |
| 4 | `shorturl.cli` | modules 1 + 2 | no | S |

Storage goes first because the Protocol is needed before service can be tested. Service goes before API because the API is a thin wrapper. CLI goes last because it depends on service + storage but has the smallest surface.

## 2. Per-module exit criteria

A module is "done" only when **all** of the following are true:

- [ ] All source files named in `02-architecture.md §5` exist.
- [ ] All unit tests in the module's `04-test-design.md §3` pass.
- [ ] All integration tests in `04-test-design.md §4` that involve this module pass.
- [ ] Coverage targets in `04-test-design.md §5` are met.
- [ ] Sub-agent review of code + tests: PASS.
- [ ] Human review of code + tests: PASS.

## 3. Per-module review log

Append entries as they happen. Format: `<artifact> | sub-agent: PASS <ts> | human: PASS <ts>`.

### Module 1 — `shorturl.storage`

- `shorturl/storage.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `tests/unit/test_storage_sqlite.py` | sub-agent: PASS <ts> | human: PASS <ts>

### Module 2 — `shorturl.service`

- `shorturl/service.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `tests/unit/test_service.py` | sub-agent: PASS <ts> | human: PASS <ts>

### Module 3 — `shorturl.api`

- `shorturl/api.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `tests/integration/test_api_flows.py` | sub-agent: PASS <ts> | human: PASS <ts>

### Module 4 — `shorturl.cli`

- `shorturl/cli.py` | sub-agent: PASS <ts> | human: PASS <ts>
- `tests/unit/test_cli.py` | sub-agent: PASS <ts> | human: PASS <ts>

## 4. Risks to the plan

| Risk | Mitigation |
|------|------------|
| Module 1 (`storage`) Protocol shape turns out wrong for module 2 | acceptable — module 2 will surface the gap in its own review gate, fix module 1 before proceeding |
| Integration tests in module 3 reveal a service-level bug | acceptable — service is already human-approved; reopen service review gate, fix, re-approve, then re-run integration |

## 5. Done criteria for the whole project

When the last module is approved, what final checks run before declaring the project complete:

- [ ] Full test suite green (`pytest -q`).
- [ ] No open `Open questions` in any 01–04 doc (or all are explicitly deferred with owner sign-off).
- [ ] Integration smoke test against `01-requirements.md` acceptance criteria: `POST /shorten` → `GET /r/<code>` → 302, run manually.
- [ ] README.md exists with one-paragraph usage and one curl example.
- [ ] Human sign-off.