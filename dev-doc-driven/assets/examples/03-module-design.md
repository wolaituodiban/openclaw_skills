# 03 — Module design: `shorturl.service`

Paired 1:1 with `04-test-design.md`. One file per module — this example shows the level of detail expected. References back to requirements use the long form ("functional requirement FR-1") in prose; the short ID is fine inside tables.

## 1. Scope

What this module does: encode the business rules for shortening and resolving URLs. What it does not: handle HTTP (that's `shorturl.api`), persist directly (that's `shorturl.storage`), parse argv (that's `shorturl.cli`).

Satisfies functional requirements FR-1 (shorten a URL), FR-2 (resolve a short code), and FR-4 (idempotent shorten) from `01-requirements.md`.

## 2. Files

| Path | Role |
|------|------|
| `shorturl/service.py` | All public functions for this module |

## 3. Public classes / functions

### 3.1 `is_valid_url(url: str) -> bool`

- **Purpose:** pure validator. Reject anything that is not a syntactically valid `http://` or `https://` URL.
- **Parameters:**
  - `url` — the candidate URL string.
- **Returns:** `True` iff `url` parses via `urllib.parse.urlparse` with `scheme in {"http", "https"}` and a non-empty `netloc`.
- **Raises / errors:** never.
- **Behavior:**
  1. `parsed = urlparse(url)`.
  2. If `parsed.scheme not in {"http", "https"}`: return `False`.
  3. If `not parsed.netloc`: return `False`.
  4. Otherwise return `True`.
- **Called by:** `shorten`, `shorturl.api` (defensive double-check on POST body), tests.

### 3.2 `shorten(url: str, store: MappingStore) -> str`

- **Purpose:** create or fetch a code for `url`, persist it, return the code.
- **Parameters:**
  - `url` — the long URL. Must pass `is_valid_url` or this raises.
  - `store` — any `MappingStore` (SQLite in prod, in-memory in tests).
- **Returns:** the 7-character code (newly generated or pre-existing for the same URL — idempotency, FR-4).
- **Raises / errors:**
  - `InvalidURLError(url)` if `not is_valid_url(url)`.
  - `StorageError(reason)` if `store.put` raises (caller decides whether to retry).
- **Behavior:**
  1. If `not is_valid_url(url)`: raise `InvalidURLError(url)`.
  2. `existing = store.find_by_url(url)`. If not `None`: return `existing`.
  3. Loop up to 5 times:
     a. `code = generate_code()` (see 3.3).
     b. `try: store.put(code, url)`.
     c. If `put` raises `IntegrityError` (collision): loop again.
     d. Else: return `code`.
  4. If 5 attempts collide: raise `StorageError("code_collision")` (effectively never, but defensive).
- **Called by:** `shorturl.api` route handler for `POST /shorten`, `shorturl.cli` `shorten` subcommand.

### 3.3 `generate_code() -> str`

- **Purpose:** produce a random 7-character `[A-Za-z0-9]{7}` code.
- **Parameters:** none.
- **Returns:** a fresh code string.
- **Raises / errors:** never (cryptographically random source is `secrets.choice`).
- **Behavior:** `return "".join(secrets.choice(ALPHABET) for _ in range(7))` where `ALPHABET = string.ascii_letters + string.digits`.
- **Called by:** `shorten` only.

### 3.4 `resolve(code: str, store: MappingStore) -> Optional[str]`

- **Purpose:** look up the original URL for `code`.
- **Parameters:**
  - `code` — the 7-character code. Format is not validated here; an unknown code simply returns `None`.
  - `store` — any `MappingStore`.
- **Returns:** the original URL, or `None` if not found.
- **Raises / errors:** never. A bad store (connection lost) propagates `StorageError` — caller decides.
- **Behavior:** `return store.get(code)`.
- **Called by:** `shorturl.api` route handler for `GET /r/<code>`, `shorturl.cli` `resolve` subcommand.

## 4. Internal helpers

- `_validate_code_format(code: str) -> bool` — one-liner: `len(code) == 7 and all(c in ALPHABET for c in code)`. Used by the API layer for cheap input filtering before calling `resolve`. Not part of the public surface.

## 5. State and data flow

This module is stateless. All state lives in the injected `MappingStore`. The only "data" it owns is the `ALPHABET` constant.

## 6. Dependencies

- **Other modules:** `shorturl.storage` (only the `MappingStore` Protocol — no concrete class).
- **External libraries:** `secrets`, `string`, `urllib.parse` — all stdlib.
- **External systems:** none.

## 7. Configuration

None. All behavior is driven by inputs.

## 8. Open questions

- Whether `shorten` should normalize URLs (strip trailing slash, lowercase host) before idempotency check. Currently does not — exact byte-equality. Resolved before step 4: do not normalize.