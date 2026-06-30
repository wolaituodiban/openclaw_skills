# 04 — Test design: `local_image_gen.cache_resolver`

Paired 1:1 with `03-design.md`. Every public symbol from 03 must appear here with at least one test case. References back to requirements use the long form in prose; the short ID is fine inside tables.

Cache-source enum used in assertions below:

```python
CacheSource = Literal['hf_env', 'hf_default', 'ms_env', 'ms_default', 'cache_dir']
```

## 1. Scope

What we test: every public function in `local_image_gen.cache_resolver` (`CacheLevel`, `resolve`, `walk_levels`); every branch of `resolve` (5-level walk + L5 conditional + first-hit-wins + all-miss returns `None`); the env-var precedence rules in `walk_levels`; the layout-snapshot helpers (`_hf_snapshot`, `_ms_snapshot`, `_cache_dir_snapshot`) because they implement the `snapshot_for` field. What we explicitly do not test: `os.path.isdir` (stdlib), `os.listdir` (stdlib), `os.path.expanduser` (stdlib), `functools.partial` (stdlib).

Satisfies functional requirement FR-3 (5-level cache lookup chain) from `01-requirements.md`. There are no NFR-1 (latency) or NFR-3 (durability) targets for this module — those are owned by the model-server, not the cache resolver.

## 2. Test layout

```
local_image_gen/
├── cache_resolver.py
└── tests/
    ├── unit/
    │   └── test_cache_resolver.py    ← all cases for this module
    └── integration/
        └── (none — cache_resolver is a leaf module per 02-architecture.md §3.2)
```

`test_cache_resolver.py` uses `tmp_path` (pytest built-in fixture) and `monkeypatch.setenv` to control env vars. No real cache directories are touched. No model weights are loaded.

## 3. Unit tests — per public function

### 3.1 `CacheLevel` (frozen dataclass)

**Construction**
- `test_construction_with_all_fields` — `CacheLevel(name='hf_env', root='/tmp/x', layout='hf', snapshot_for=lambda m: None)` constructs without error; fields are readable.
- `test_construction_layout_values` — both `'hf'` and `'ms'` are accepted for `layout` (Literal is `'hf' | 'ms'`).
- `test_construction_callable_accepts_model` — the `snapshot_for` callable is invoked with exactly one positional arg (`model: str`) and must return either `None` or a `str` (no exceptions on None return).

**Frozen**
- `test_frozen_rejects_field_mutation` — `level.name = 'hf_default'` after construction raises `dataclasses.FrozenInstanceError`. Same for `root`, `layout`, `snapshot_for`.

**Identity**
- `test_eq_by_value` — two `CacheLevel` instances with the same `(name, root, layout, snapshot_for)` are equal (dataclass `__eq__`).

### 3.2 `resolve`

**Happy path — L1 hit**
- `test_resolve_hits_l1_hf_env` — `HF_HOME=<tmp>/hf` set, `<tmp>/hf/hub/models--Tongyi-MAI--Z-Image-Turbo/snapshots/abc123/` exists. `resolve('Tongyi-MAI/Z-Image-Turbo')` returns `(<abs path>, 'hf_env')`.

**Happy path — L2 hit (L1 miss)**
- `test_resolve_hits_l2_hf_default_when_no_env` — `HF_HOME` unset, `<tmp_default>/models--Tongyi-MAI--Z-Image-Turbo/snapshots/abc123/` exists (set `HOME` to a tmp dir so `HF_DEFAULT_ROOT` resolves to it). `resolve('Tongyi-MAI/Z-Image-Turbo')` returns `(<abs path>, 'hf_default')`.

**Happy path — L3 hit (L1 + L2 miss)**
- `test_resolve_hits_l3_ms_env` — `MODELSCOPE_CACHE=<tmp>/ms` set, `<tmp>/ms/models/Tongyi-MAI/Z-Image-Turbo/` exists. `resolve('Tongyi-MAI/Z-Image-Turbo')` returns `(<abs path>, 'ms_env')`.

**Happy path — L4 hit (L1-L3 miss)**
- `test_resolve_hits_l4_ms_default_when_no_env` — `MODELSCOPE_CACHE` unset, `HOME` set so `MS_DEFAULT_ROOT` resolves to a tmp dir with `models/Tongyi-MAI/Z-Image-Turbo/`. `resolve('Tongyi-MAI/Z-Image-Turbo')` returns `(<abs path>, 'ms_default')`.

**Happy path — L5 hit (L1-L4 miss)**
- `test_resolve_hits_l5_cache_dir_hf` — no env vars set, `cache_dir=<tmp>` with HF layout `<tmp>/models--Tongyi-MAI--Z-Image-Turbo/snapshots/abc123/`. `resolve('Tongyi-MAI/Z-Image-Turbo', cache_dir=<tmp>)` returns `(<abs path>, 'cache_dir')`.
- `test_resolve_hits_l5_cache_dir_ms` — same setup but MS layout `<tmp>/models/Tongyi-MAI/Z-Image-Turbo/`. Returns `(<abs path>, 'cache_dir')` (cache_dir is the source; layout is internal).

**Happy path — L5 not appended when None**
- `test_resolve_omits_l5_when_cache_dir_none` — L1-L4 all miss, `cache_dir=None` (default). `resolve` returns `None`; L5 is not consulted (verified by setting `cache_dir` to a path that would hit — `resolve` still returns `None` because `cache_dir` is `None`).

**First-hit-wins (priority order)**
- `test_resolve_first_hit_wins` — both L1 and L2 contain the model. `resolve` returns `('hf_env', ...)` — L1 wins by walk order, not by tree comparison. (Confirms 03 §3.2 step 3.)

**All miss → None**
- `test_resolve_returns_none_when_all_levels_miss` — env vars set, no levels contain the model, `cache_dir=None`. `resolve` returns `None`. Same for `cache_dir=<some non-existent path>`.
- `test_resolve_returns_none_for_malformed_model_id` — `resolve('no-slash')` → all levels return `None` from `snapshot_for` (no `/` to split on) → `resolve` returns `None`. Same for `resolve('a/b/c/too-many')` — `os.path.join` handles extra `/` but `models--a--b--c--too-many` won't exist.

**Type-safety**
- `test_resolve_returns_tuple_of_str_and_cache_source` — on hit, return value is `tuple[str, str]` and second element is in `CacheSource` literal set. On miss, return is `None`. (Type-level: `Optional[Tuple[str, CacheSource]]`.)

### 3.3 `walk_levels`

**Length**
- `test_walk_levels_returns_1_to_4_entries` — never 5 (L5 is per-call, owned by `resolve`). Enumerate all 4 env-var combinations (`HF_*` set/unset × `MODELSCOPE_CACHE` set/unset) and assert length 1, 2, 3, or 4.
- `test_walk_levels_does_not_consult_anything_outside_env_and_constants` — returns the same list structure as documented in 03 §3.3.

**L1 (hf_env)**
- `test_walk_levels_l1_present_when_hf_home_set` — `HF_HOME=<tmp>` set, `monkeypatch.setenv('HF_HOME', str(tmp))`. `walk_levels()[0].name == 'hf_env'` and `.root == str(tmp) + '/hub'`. (Q1-dependent; `xfail(strict=True)` per §8 Q1.)
- `test_walk_levels_l1_present_when_huggingface_hub_cache_set` — `HF_HOME` unset, `HUGGINGFACE_HUB_CACHE=<tmp>` set. `walk_levels()[0].name == 'hf_env'` and `.root == str(tmp) + '/hub'`. (Q1-dependent; `xfail(strict=True)` per §8 Q1.)
- `test_walk_levels_l1_omitted_when_neither_set` — both unset, `walk_levels()` has no `'hf_env'` entry.
- `test_walk_levels_l1_hf_home_takes_precedence` — both `HF_HOME` and `HUGGINGFACE_HUB_CACHE` set; L1 `.root` uses `HF_HOME`. (Precedence is locked in 02-architecture.md §3.2 "Resolution rules" — not an Open question. Independent of Q1.)

**L2 (hf_default)**
- `test_walk_levels_l2_always_present` — `walk_levels()` always contains a `CacheLevel(name='hf_default', layout='hf', root=HF_DEFAULT_ROOT)`. Verify by setting `HOME` to a tmp dir and asserting `.root == <tmp>/.cache/huggingface/hub/`.

**L3 (ms_env)**
- `test_walk_levels_l3_present_when_modelscope_cache_set` — `monkeypatch.setenv('MODELSCOPE_CACHE', str(tmp))`. `walk_levels()` contains a `CacheLevel(name='ms_env', root=str(tmp), layout='ms')`. Note: **no** `/hub` suffix (MS env var is the cache root directly).
- `test_walk_levels_l3_omitted_when_unset` — no `MODELSCOPE_CACHE`, no `'ms_env'` entry.

**L4 (ms_default)**
- `test_walk_levels_l4_always_present` — `walk_levels()` always contains `CacheLevel(name='ms_default', root=MS_DEFAULT_ROOT, layout='ms')`. Set `HOME` to a tmp dir, verify root.

**Layout field**
- `test_walk_levels_l1_and_l2_layout_hf` — `.layout == 'hf'`.
- `test_walk_levels_l3_and_l4_layout_ms` — `.layout == 'ms'`.

**Ordering**
- `test_walk_levels_walk_order_l1_to_l4` — when all 4 levels are present, `walk_levels()` returns them in the order `[L1, L2, L3, L4]`. Verify by `.name` field.

**Env read at walk time (not at import)**
- `test_walk_levels_re_reads_env_each_call` — set `HF_HOME` after import, call `walk_levels()` → L1 appears. Unset, call again → L1 gone. Confirms 03 §3.3 behavior step 1 ("These reads happen at every call").

## 4. Internal helpers (cross-reference)

These are private (`_*`), but their behavior is observable through `CacheLevel.snapshot_for`. Tests verify via the public interface; no direct import of `_hf_snapshot` etc. The exception is the **closed-form** tests below, which import the private functions directly to exercise edge cases the public tests cannot reach (e.g., `_hf_snapshot` returning `None` for a root that doesn't exist).

- `_hf_snapshot(root, model)`:
  - Returns the absolute path of the lexicographically-smallest sha subdir under `<root>/models--<org>--<repo>/snapshots/`.
  - Returns `None` if `<root>` does not exist, if `models--<org>--<repo>/` does not exist, or if `snapshots/` has no sha subdirs.
  - Test cases (closed-form): `test_hf_snapshot_returns_smallest_sha_when_multiple`, `test_hf_snapshot_returns_none_for_missing_root`, `test_hf_snapshot_returns_none_for_missing_model_subdir`, `test_hf_snapshot_returns_none_for_empty_snapshots_dir`.
- `_ms_snapshot(root, model)`:
  - Returns `<root>/models/<org>/<repo>/` iff it is a directory; else `None`.
  - Test cases (closed-form): `test_ms_snapshot_returns_path_for_existing_model`, `test_ms_snapshot_returns_none_for_missing_root`, `test_ms_snapshot_returns_none_for_missing_model`.
- `_cache_dir_snapshot(cache_dir, model)`:
  - Tries `_hf_snapshot(cache_dir, model)` first; falls back to `_ms_snapshot(cache_dir, model)`; returns whichever is non-`None`; returns `None` if both fail.
  - Test cases (closed-form): `test_cache_dir_snapshot_hf_layout_wins`, `test_cache_dir_snapshot_ms_layout_fallback`, `test_cache_dir_snapshot_returns_none_when_neither_layout_matches`, `test_cache_dir_snapshot_silent_skip_on_mismatch` (Q4 Open question currently; flag `xfail(strict=True)` if logging is later required).

> **Why not import the helpers through the public surface for these tests?** The public surface (`CacheLevel.snapshot_for`) only fires when a `CacheLevel` is constructed. Closed-form tests directly import the private function and call it; this is the canonical way to test private helpers without going through public re-routing. This is allowed for the **internal helpers section only**, not the public-function sections.

## 5. Coverage targets

| Metric | Target |
|--------|--------|
| Line coverage | ≥ 95 % |
| Branch coverage | ≥ 90 % |
| Public-function coverage | 100 % (`CacheLevel`, `resolve`, `walk_levels`) |
| Internal-helper coverage | 100 % (`_hf_snapshot`, `_ms_snapshot`, `_cache_dir_snapshot`) |

## 6. Test data

`tmp_path` (pytest built-in) for cache roots. `monkeypatch.setenv` / `monkeypatch.delenv` for env var control. `monkeypatch.setattr('os.path.expanduser', ...)` is **not** used — instead, set `HOME` to a tmp dir so `HF_DEFAULT_ROOT` / `MS_DEFAULT_ROOT` (computed at import time) land inside the tmp dir.

No fixtures file. No real model weights. No real HuggingFace or ModelScope library imports.

## 7. What is intentionally not tested

- **No integration tests** — cache_resolver is a leaf module (per 02-architecture.md §3.2 "Dependencies on other modules: none"). Cross-module behavior is exercised by `test_mcp_server.py` (in the next module's 04-test-design), not here.
- **No real-model testing** — tests use synthetic `models--<org>--<repo>/snapshots/<sha>/` directory trees. They do not load weights, do not import transformers / diffusers, do not import huggingface_hub or modelscope libraries.
- **No concurrency** — single-process, single-thread.
- **No error paths on stdlib** — `os.path.isdir` and `os.listdir` are assumed not to raise on missing paths (documented behavior of stdlib). If the stdlib's contract changes, tests will need updating.
- **`functools.partial`** — stdlib, not retested.
- **The R2-flagged closure form** — `resolve` constructs L5 with `functools.partial(_cache_dir_snapshot, cache_dir)`. Test `test_resolve_hits_l5_cache_dir_hf` (above) exercises this implicitly through the public `resolve` call. The closure form itself is not asserted directly (avoids whitebox testing on stdlib composition).

## 8. Open questions

- **Q1 (HF env / `hub/` suffix)** — `test_walk_levels_l1_present_when_hf_home_set` AND `test_walk_levels_l1_present_when_huggingface_hub_cache_set` both assert `str(tmp) + '/hub'`. If Q1 is resolved in 03 to "no suffix" (HF env var is the cache root directly), both tests must change. Marked `xfail(strict=True)` in 04 until 03 Q1 is closed by human review.
- **Q2 (HF multi-sha selection)** — `test_hf_snapshot_returns_smallest_sha_when_multiple` asserts `sorted(shas)[0]`. If Q2 is resolved to "raise on multi-sha", this test changes to `pytest.raises(...)`. Marked `xfail(strict=True)` until Q2 closed.
- **Q3 (L5 `layout` field semantics)** — 04 does **not** assert `level.layout` for the L5 level constructed inside `resolve`. The test surface treats `layout` as undefined for L5 (per Q3 in 03 §8). If Q3 is resolved to "remove `layout` from public API for L5 only", no 04 change is needed. If Q3 is resolved to "rename to `'auto'`", `test_resolve_hits_l5_cache_dir_*` would need to assert `level.layout == 'auto'` — but `resolve` does not return the level, only `(path, source)`, so this test cannot be expressed. Decision: Q3 resolution does not affect 04 surface either way (test only observes return value).
- **Q4 (cache_dir mismatch handling)** — `test_cache_dir_snapshot_silent_skip_on_mismatch` currently asserts silent `None`. If Q4 is resolved to "log warning", this test must be augmented with `caplog` assertion. Marked `xfail(strict=True)` until Q4 closed.
- **Whether `os.path.expanduser` re-computation on `HOME` change** is required (test 3.3 `test_walk_levels_re_reads_env_each_call` assumes `HF_DEFAULT_ROOT` was computed at import with the test's `HOME` already set). If the implementation later switches to lazy / `HOME`-sensitive resolution, the test must be re-evaluated.
