# 03 — Module design: `local_image_gen.cache_resolver`

Paired 1:1 with `04-test-design.md` (not yet written). One file per module — this document mirrors the structure of `assets/examples/03-module-design.md`. References back to requirements use the long form ("functional requirement FR-3") in prose; the short ID is fine inside tables.

Cache-source enum used in signatures below:

```python
CacheSource = Literal['hf_env', 'hf_default', 'ms_env', 'ms_default', 'cache_dir']
```

**Deliberate deviation from 02-architecture.md §3 (2026-07-01T02:56 owner correction, doc fix-up):**

- **Test layout** — 02 §5 places `tests/` at the skill root (`<project-root>/tests/`). This 03 + 04 pair follows that layout (`tests/unit/test_cache_resolver.py`). The previous v1 path `local_image_gen/tests/unit/test_cache_resolver.py` was a doc drift from 02 §5 and was corrected in v1 amend.
- **`walk_levels()` returns 1–4 levels, not 5** — 02 §3 L141 says "5 levels in walk order", but 02 §3 L142 says "level 5 (`cache_dir`) is appended only if `cache_dir` is supplied" (per-call, inside `resolve()`). 02 is internally inconsistent on this point. This 03 (and 02's "Resolution rules" prose at L142) follow the **per-call L5 inside `resolve()`** interpretation, so `walk_levels()` returns the 1–4 env-resolved levels and `resolve()` appends the `cache_dir` level when supplied. 02 v10 should reconcile L141 with L142.
- **`CacheLevel.layout` for L5** — set to `'hf'` nominal in code; `_cache_dir_snapshot` actually probes both HF and MS layouts per 02 §3 step 5. The `layout` field is effectively unused for L5; 02 §3 does not constrain it. Tracked as 03 §8 Q3 (alternative: drop the field from L5).


## 1. Scope

What this module does: walk the 5-level cache lookup chain (HF env → HF default → MS env → MS default → caller-supplied `cache_dir`) for a given `model` and return the absolute on-disk snapshot path together with which level won. What it does not: spawn subprocesses, contact vllm-omni, load model weights, map `None` to MCP error codes (that mapping is owned by `mcp_server`).

Satisfies functional requirement FR-3 (5-level cache lookup chain) from `01-requirements.md`.

## 2. Files

| Path | Role |
|------|------|
| `local_image_gen/cache_resolver.py` | All public functions for this module + the `CacheLevel` dataclass + private snapshot-path helpers |
| `tests/unit/test_cache_resolver.py` | One test module per public function, one branch per public branch (not yet written — see 04-test-design) |

## 3. Public classes / functions

### 3.1 `CacheLevel`

Frozen dataclass representing one slot in the lookup chain.

- **Fields:**
  - `name: CacheSource` — the level's identity. Reported back to `mcp_server` as `cache_source`. Literal values per 02-architecture.md §3.2.
  - `root: str` — absolute path of the cache root resolved at walk time. For env-var levels this is the parent directory augmented with `hub/` per HuggingFace convention.
  - `layout: Literal['hf', 'ms']` — the on-disk layout convention. `'hf'` for HuggingFace's `models--<org>--<repo>/snapshots/<sha>/` form; `'ms'` for ModelScope's `models/<org>/<repo>/` form.
  - `snapshot_for: Callable[[str], Optional[str]]` — pure function `(model) -> absolute_snapshot_path | None`. Returns the absolute path of the first existing snapshot for `model` under this level, or `None` if no snapshot is present.
- **Frozen:** `@dataclass(frozen=True)` per 02 §3.2 "No state beyond the chain arguments".
- **Constructor signature:** `CacheLevel(name: CacheSource, root: str, layout: Literal['hf', 'ms'], snapshot_for: Callable[[str], Optional[str]])`
- **Called by:** `walk_levels()` constructs them; `resolve()` consumes them; `mcp_server.list_local_models` consumes them for startup logging (read-only).

### 3.2 `resolve(model: str, cache_dir: Optional[str] = None) -> Optional[CacheLevel]`

- **Purpose:** walk the chain in fixed order and return the first level whose `snapshot_for(model)` is non-`None`. Returns `None` if no level matches. **The caller invokes `level.snapshot_for(model)` itself** to obtain the absolute snapshot path — `resolve` does not pre-resolve the path. This avoids re-running the snapshot lookup in callers that only need the level (e.g. `list_local_models` for diagnostics), and matches `02-architecture.md` §3 spec ("cache_resolver: single responsibility = 5-level chain walk; return the level that wins").
- **Parameters:**
  - `model` — the HuggingFace-style repo id, e.g. `'Tongyi-MAI/Z-Image-Turbo'`. Must contain exactly one `/`. A model id with zero or multiple `/` yields `None` from every level's `snapshot_for` and therefore `None` overall.
  - `cache_dir` — optional per-call cache directory. When `None`, levels 1–4 only. When supplied, an additional L5 level is appended to the chain inside this function.
- **Returns:** the first `CacheLevel` whose `snapshot_for(model)` is non-`None`, or `None` if no level matched. The caller calls `level.snapshot_for(model)` to get the absolute snapshot path.
- **Raises / errors:** never. IO is limited to `os.path.isdir` + `os.listdir`; both return safely without raising on missing paths.
- **Behavior:**
  1. `levels = walk_levels()`. If `cache_dir is not None`, append an L5 `CacheLevel` constructed with `name='cache_dir'`, `root=cache_dir`, `layout='hf'` nominal, and `snapshot_for = functools.partial(_cache_dir_snapshot, cache_dir)` (so the partial takes only `model` and matches the one-arg `Callable[[str], Optional[str]]` shape of the `CacheLevel.snapshot_for` field). The closure performs the L5 auto-probe (HF-then-MS).
  2. For `level` in `levels`: `if level.snapshot_for(model) is not None: return level`.
  3. After all levels: `return None`.
- **Called by:** `mcp_server.start_service` (canonical use) and `mcp_server.list_local_models` (diagnostics). `mcp_server` maps `None` → `model_not_found` MCP error.
- **Caller-side snapshot lookup** (illustrative — not in this module):

  ```python
  # mcp_server.py caller code
  level = cache_resolver.resolve(model, cache_dir=cache_dir)
  if level is None:
      raise ModelNotFoundError(model)
  snapshot_path = level.snapshot_for(model)   # second call; intentional — same return value as the one inside resolve()
  ```

### 3.3 `walk_levels() -> List[CacheLevel]`

- **Purpose:** build the chain — four `CacheLevel` objects in walk order. Per 02 §3.2 spec, this diagnostic helper takes no arguments; the optional L5 (`cache_dir`) level is appended inside `resolve()` instead, where the per-call arg lives.
- **Parameters:** none.
- **Returns:** list of `CacheLevel` in fixed order: L1 (hf_env) → L2 (hf_default) → L3 (ms_env) → L4 (ms_default). Length is 1, 2, 3, or 4 depending on which env vars are set (L1 skipped if neither `HF_HOME` nor `HUGGINGFACE_HUB_CACHE` is set; L3 skipped if `MODELSCOPE_CACHE` is unset; L2 and L4 always present).
- **Raises / errors:** never.
- **Behavior:**
  1. Read `os.environ` for `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `MODELSCOPE_CACHE`. These reads happen at every call (cache resolver has no internal env cache).
  2. **Level 1 (hf_env)** — included iff `HF_HOME or HUGGINGFACE_HUB_CACHE` is set. `root = os.path.join(<resolved env>, 'hub')`. `layout='hf'`.
  3. **Level 2 (hf_default)** — always included. `root = HF_DEFAULT_ROOT` (`~/.cache/huggingface/hub/` per `os.path.expanduser`). `layout='hf'`.
  4. **Level 3 (ms_env)** — included iff `MODELSCOPE_CACHE` is set. `root = MODELSCOPE_CACHE` verbatim (no `hub/` suffix; the MS env var is the cache root, not its parent). `layout='ms'`.
  5. **Level 4 (ms_default)** — always included. `root = MS_DEFAULT_ROOT` (`~/.cache/modelscope/hub/`). `layout='ms'`.
- **Called by:** `resolve()` (concatenates L5 with this list), `mcp_server.list_local_models` (for NFR-4 per-event log fields).

## 4. Internal helpers

- `_hf_snapshot(root: str, model: str) -> Optional[str]` — probe a HuggingFace-layout cache root: if `<root>/models--<org>--<repo>/snapshots/<sha>/` exists for some sha under `root`, return the absolute path of one snapshot in deterministic sorted order; else `None`. Used by L1, L2, and the L5 auto-probe HF branch.
- `_ms_snapshot(root: str, model: str) -> Optional[str]` — probe a ModelScope-layout cache root: return `<root>/models/<org>/<repo>/` iff it is a directory; else `None`. Used by L3, L4, and the L5 auto-probe MS branch.
- `_cache_dir_snapshot(cache_dir: str, model: str) -> Optional[str]` — implement the L5 auto-probe per 02 §3.2: try `_hf_snapshot` first, fall back to `_ms_snapshot`, return whichever is non-`None`; if both are `None`, return `None`. Used only by L5 (constructed inside `resolve()` when `cache_dir is not None`).
- `HF_DEFAULT_ROOT = os.path.expanduser('~/.cache/huggingface/hub/')` — module-level constant, computed at import time.
- `MS_DEFAULT_ROOT = os.path.expanduser('~/.cache/modelscope/hub/')` — module-level constant, computed at import time.

## 5. State and data flow

Stateless. The two module-level constants (`HF_DEFAULT_ROOT`, `MS_DEFAULT_ROOT`) are the only "data" the module owns; see §4.

Per-call state lives in the function arguments (`model`, `cache_dir`) plus `os.environ` reads at walk time. `os.environ` reads are atomic at the dict level; the module is safe under single-thread use. Multi-thread safety is not in scope (the sole caller `mcp_server` is single-process and serialises calls).

## 6. Dependencies

- **Other modules:** none. cache_resolver is a leaf module per 02 §3.2 "Dependencies on other modules: none".
- **External libraries:** `os` (path + env reads), `functools.partial` (for the L5 partial-bound `snapshot_for` closure), `dataclasses.dataclass`, `typing.Literal`, `typing.Optional`, `typing.Callable`, `typing.List`, `typing.Tuple` — all stdlib.
- **External systems:** the filesystem only. No HTTP, no subprocess, no network, no model loaders, no HuggingFace, no ModelScope.

## 7. Configuration

| Source | Key | Effect |
|--------|-----|--------|
| env var | `HF_HOME` | If set, enables L1 with root `<env>/hub/` |
| env var | `HUGGINGFACE_HUB_CACHE` | If set, enables L1 with root `<env>/hub/`. `HF_HOME` takes precedence when both are set. |
| env var | `MODELSCOPE_CACHE` | If set, enables L3 with root `<env>` verbatim |
| constant | `HF_DEFAULT_ROOT` | Compiled from `~/.cache/huggingface/hub/` at import time |
| constant | `MS_DEFAULT_ROOT` | Compiled from `~/.cache/modelscope/hub/` at import time |
| per-call | `cache_dir` arg | When not `None`, appends L5 (constructed inside `resolve()`) with root `<cache_dir>` verbatim |

Everything else is hardcoded per 02 §3.2 "fix your eyes on what, do not think about how (later steps think about how)". No new env var, no new config file, no new CLI flag.

## 8. Open questions

- **Q1 (HF env / `hub/` suffix)** — when `HF_HOME` is set, is the env var pointing at the cache root or its parent? 03 §3.3 step 2 currently assumes the env var is the cache **parent** and appends `hub/`. HuggingFace's own library appends `hub/` internally; 02 §3.2 doesn't disambiguate. **Status:** proposed; sub-agent review should confirm against HF source.
- **Q2 (HF multi-sha selection)** — when a snapshot dir contains multiple sha subdirectories, 03 §4 `_hf_snapshot` picks `sorted(shas)[0]`. 02 §3.2 doesn't specify determinism; this design picks lexicographic order for cross-run reproducibility. **Status:** proposed; alternative is to raise on multi-sha ("ambiguous cache") to surface the bug.
- **Q3 (L5 layout field semantics)** — L5 `CacheLevel.layout` is set to `'hf'` nominal, but the actual layout is decided per-call by `_cache_dir_snapshot`. 02 §3.2 doesn't address the `layout` field of the L5 level. **Status:** acceptable per 02 §3.2 (only `snapshot_for` is consulted by `resolve`), but the field is effectively unused for L5. Alternative: remove `layout` from the public API for L5 only.
- **Q4 (cache_dir mismatch)** — if `cache_dir` exists but contains neither HF nor MS layout for `model`, 03 §4 `_cache_dir_snapshot` returns `None` and L5 contributes no hit. 02 §3.2 is silent on this case; the alternative is to log an explicit "cache_dir present but no layout match" event. **Status:** proposed silent skip; alternative is logged warning.
