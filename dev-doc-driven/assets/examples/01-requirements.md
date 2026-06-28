# 01 — Requirements: shorturl

## 1. Project name

`shorturl` — a small URL shortening service.

## 2. Problem statement

Long URLs are hard to share, ugly in print, and lossy when forwarded through tools that truncate. `shorturl` lets a user POST a long URL and receive a short code; the short code, when resolved, 302-redirects to the original. The service is meant for internal tooling use (link tracking, compact sharing in chat) — not as a public bit.ly competitor.

## 3. Goals

1. A POST to `/shorten` with a valid URL returns a 7-character alphanumeric code within 50 ms p99 (1k QPS, single instance).
2. A GET to `/r/<code>` returns a 302 redirect to the original URL within 30 ms p99.
3. Created mappings persist across process restarts.
4. The service runs as a single Python process with one SQLite file for storage — no external services required.

## 4. Non-goals

- User accounts, authentication, or per-user analytics.
- Custom short codes (the service generates them).
- Rate limiting beyond the implicit "1k QPS / instance" budget.
- Multi-region replication, sharding, or CDN fronting.
- A web UI. CLI + HTTP API only.

## 5. Functional requirements

A functional requirement describes **what** the system does. One row per behavior. The stable ID (`FR-1`, `FR-2`, …) is referenced from architecture, module, and test documents so the chain stays traceable.

| ID | Requirement | Priority | Acceptance criteria |
|----|-------------|----------|---------------------|
| FR-1 | Shorten a URL | must | `POST /shorten {"url": "<long>"}` → `200 {"code": "<7 chars>", "short_url": "http://<host>/r/<code>"}`. Reject non-HTTP(S) URLs with `400`. |
| FR-2 | Resolve a short code | must | `GET /r/<code>` → `302 Location: <original>`. Unknown code → `404`. |
| FR-3 | Persist mappings | must | After a successful shorten, restarting the process and calling `GET /r/<code>` still returns `302`. |
| FR-4 | Idempotent shorten | should | `POST /shorten` with the same URL twice returns the same code (within a process lifetime; restart is allowed to re-generate). |
| FR-5 | CLI command | should | `shorturl shorten <url>` prints the code and exits 0; `shorturl resolve <code>` prints the original URL and exits 0. |

## 6. Non-functional requirements

A non-functional requirement describes **how well** the system does what it does — quality attributes of behavior, not behavior itself. Performance, reliability, security, observability, portability all live here. The stable ID (`NFR-1`, `NFR-2`, …) is referenced the same way as functional requirements.

| ID | Category | Requirement | Measure |
|----|----------|-------------|---------|
| NFR-1 | performance | shorten latency | p99 < 50 ms at 1k QPS |
| NFR-2 | performance | resolve latency | p99 < 30 ms at 1k QPS |
| NFR-3 | reliability | data durability | mappings survive process restart |
| NFR-4 | observability | structured logs | one JSON line per request with method, path, status, duration_ms |
| NFR-5 | portability | no external services | runs on any host with Python 3.11+ and a writable filesystem |

## 7. Users / actors

- **Internal developer** — calls `/shorten` from a script or browser, pastes the returned short URL into a chat or doc.
- **CLI user** — runs `shorturl` from a shell for one-off operations.

## 8. Open questions

- [ ] Final HTTP framework choice — FastAPI is the default unless the user prefers Flask or stdlib `http.server`.
- [ ] Whether FR-4 (idempotency) needs to survive restart. The "should" priority suggests it can change later.

## 9. Glossary

- **Code** — the 7-character `[A-Za-z0-9]{7}` identifier returned by `POST /shorten` and used in `/r/<code>`.
- **Mapping** — the (code → original_url) record stored in SQLite.
- **Shorten** — the act of creating a new mapping and returning its code.
- **Functional requirement** — describes what the system does.
- **Non-functional requirement** — describes how well the system does it.