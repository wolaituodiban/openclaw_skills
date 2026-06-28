# 04 — Test design: `shorturl.service`

Paired 1:1 with `03-module-design.md`. Every public symbol from 03 must appear here with at least one test case. References back to requirements use the long form in prose; the short ID is fine inside tables.

## 1. Scope

What we test: every public function in `shorturl.service`, every branch of `shorten` (happy, idempotent hit, collision retry, invalid URL, storage error). What we explicitly do not test: `secrets.choice` randomness (we monkeypatch `generate_code`), `urllib.parse` (stdlib).

Satisfies non-functional requirements NFR-1 (shorten latency) and NFR-3 (data durability) from `01-requirements.md` via the unit + integration tests.

## 2. Test layout

```
tests/
├── unit/
│   ├── test_service.py             ← all cases for this module
│   ├── test_storage_sqlite.py
│   └── test_cli.py
└── integration/
    └── test_api_flows.py
```

`test_service.py` uses `InMemoryStore` from `shorturl.storage` — fast, deterministic, no fixtures.

## 3. Unit tests — per public function

### 3.1 `is_valid_url`

**Happy path**
- `test_valid_http` — `is_valid_url("http://example.com")` → `True`.
- `test_valid_https_with_path` — `is_valid_url("https://example.com/a/b?c=1")` → `True`.
- `test_valid_with_port` — `is_valid_url("http://localhost:8080/x")` → `True`.

**Error branches**
- `test_rejects_ftp_scheme` — `"ftp://example.com"` → `False`.
- `test_rejects_javascript_scheme` — `"javascript:alert(1)"` → `False`.
- `test_rejects_data_scheme` — `"data:text/plain,foo"` → `False`.
- `test_rejects_empty` — `""` → `False`.
- `test_rejects_no_scheme` — `"example.com"` → `False`.
- `test_rejects_scheme_only` — `"http://"` → `False` (empty netloc).
- `test_rejects_none` — input `None` → `False` (does not raise).

**Edge cases**
- `test_accepts_unicode_host` — `"http://例え.com/"` → `True`.

### 3.2 `shorten`

**Happy path**
- `test_shorten_creates_code` — given `InMemoryStore()`, `shorten("http://example.com", store)` returns a 7-char string. `store.get(code) == "http://example.com"`.
- `test_shorten_returns_alphanumeric` — 100 calls produce only `[A-Za-z0-9]{7}` (regex match).

**Idempotency**
- `test_shorten_same_url_same_code` — call `shorten(u, store)` twice with the same URL; both calls return the same code. `store` has exactly 1 entry.
- `test_shorten_different_urls_different_codes` — call with two URLs; codes differ (monkeypatch `generate_code` to return `"aaaaaaa"` then `"bbbbbbb"` to make this deterministic).

**Collision retry**
- `test_shorten_retries_on_collision` — monkeypatch `generate_code` to return `["x", "x", "x", "y"]`. Use a `InMemoryStore` whose `put` raises `IntegrityError` on the first 3 calls. Verify `shorten` returns `"y"` and `store.get("y") == url`.

**Error branches**
- `test_shorten_rejects_invalid_url` — `shorten("not a url", store)` raises `InvalidURLError`. `store` is untouched (no `put`, no `find_by_url` reads).
- `test_shorten_propagates_storage_error` — `InMemoryStore.put` raises `StorageError`. `shorten` re-raises it (does not swallow).

**Edge cases**
- `test_shorten_with_url_containing_query` — `shorten("http://example.com/?a=1&b=2", store)`; idempotency compares the full URL byte-for-byte.
- `test_shorten_with_very_long_url` — 8000-char URL shortens without error.

### 3.3 `generate_code`

**Happy path**
- `test_length_is_7` — every call returns a 7-char string.
- `test_alphabet` — every char is in `[A-Za-z0-9]`.
- `test_uniqueness_over_many_calls` — 10 000 calls produce ≥ 9990 unique codes (collision rate < 0.1 %; this is a smoke test, not a randomness proof).

### 3.4 `resolve`

**Happy path**
- `test_resolve_returns_original` — pre-populate `store` with `{"abc1234": "http://example.com"}`. `resolve("abc1234", store)` → `"http://example.com"`.

**Error branches**
- `test_resolve_returns_none_for_unknown_code` — `resolve("nothere", store)` → `None` (does not raise).
- `test_resolve_returns_none_for_empty_store` — `resolve("anything", empty_store)` → `None`.

**Edge cases**
- `test_resolve_with_malformed_code_does_not_raise` — `resolve("../../etc/passwd", store)` → `None` (no exception, just not found).
- `test_resolve_propagates_storage_error` — `store.get` raises `StorageError`; `resolve` re-raises.

## 4. Integration tests — per cross-module flow

These live in `tests/integration/test_api_flows.py` and exercise `service` + `storage` together through the HTTP layer.

### 4.1 `flow_shorten_then_resolve`

- **Setup:** `app = create_app(InMemoryStore())`. `TestClient(app)`.
- **Steps:**
  1. `POST /shorten {"url": "http://example.com/a"}` → `200`, capture `code`.
  2. `GET /r/<code>` (allow_redirects=False) → `302`, `Location == "http://example.com/a"`.
- **Expected final output:** the second response has exactly `status_code == 302` and `headers["location"] == "http://example.com/a"`.
- **Cleanup:** `TestClient` context manager handles teardown.

### 4.2 `flow_reject_invalid_url`

- **Setup:** same as 4.1.
- **Steps:** `POST /shorten {"url": "javascript:alert(1)"}`.
- **Expected final output:** `status_code == 400`, body `{"error": "invalid_url"}`.

### 4.3 `flow_unknown_code_404`

- **Setup:** same as 4.1.
- **Steps:** `GET /r/nothere`.
- **Expected final output:** `status_code == 404`.

## 5. Coverage targets

| Metric | Target |
|--------|--------|
| Line coverage | ≥ 95 % |
| Branch coverage | ≥ 90 % |
| Public-function coverage | 100 % |

## 6. Test data

Inline. URLs are short, predictable, ASCII. No fixtures file. `InMemoryStore` is constructed in each test.

## 7. What is intentionally not tested

- The `SqliteStore` round-trip is in `test_storage_sqlite.py`, not here. This module's tests use `InMemoryStore` only.
- Concurrency / race between two concurrent `shorten` calls — out of scope (single process, single thread).
- URL normalization — explicitly out per `03-design.md §8`.

## 8. Open questions

- Whether to add property-based tests (`hypothesis`) for `is_valid_url`. Decision: not now, only if a fuzzer finds a bug.