"""5-level cache lookup chain walker.

Given an HF-style model id (e.g. 'Tongyi-MAI/Z-Image-Turbo') and an optional
per-call cache_dir, walk the chain HF env -> HF default -> MS env -> MS default
-> cache_dir and return the first on-disk snapshot. See 03-design.md in
dev-doc/cache_resolver/ for the full design.

Satisfies functional requirement FR-3 (5-level cache lookup chain) from
01-requirements.md.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from typing import Callable, List, Literal, Optional

from typeguard import typechecked

CacheSource = Literal['hf_env', 'hf_default', 'ms_env', 'ms_default', 'cache_dir']
Layout = Literal['hf', 'ms']

# Module-level constants computed at import time.
# `os.path.expanduser` reads `HOME`; tests that want to redirect these roots
# to a temp dir must patch `os.path.expanduser` BEFORE importing this module
# (or use `importlib.reload` after patching).
HF_DEFAULT_ROOT: str = os.path.expanduser('~/.cache/huggingface/hub/')
MS_DEFAULT_ROOT: str = os.path.expanduser('~/.cache/modelscope/hub/')


@dataclass(frozen=True)
class CacheLevel:
    """One slot in the 5-level cache lookup chain.

    Fields:
        name: identity of the level; reported as `cache_source` in responses.
        root: absolute path of the cache root resolved at walk time.
        layout: on-disk layout convention ('hf' for snapshots/<sha>/,
            'ms' for models/<org>/<repo>/).
        snapshot_for: pure function (model) -> absolute snapshot path | None.
    """

    name: CacheSource
    root: str
    layout: Layout
    snapshot_for: Callable[[str], Optional[str]]


@typechecked
def _hf_snapshot(root: str, model: str) -> Optional[str]:
    """Probe a HuggingFace-layout cache root.

    Returns the absolute path of the lexicographically-smallest sha subdir
    under `<root>/models--<org>--<repo>/snapshots/`, or None if any segment
    is missing. See 03-design.md §4 Q2: smallest-sha is the documented
    deterministic tie-breaker.
    """
    if '/' not in model:
        return None
    org, repo = model.split('/', 1)
    models_dir = os.path.join(root, f'models--{org}--{repo}', 'snapshots')
    if not os.path.isdir(models_dir):
        return None
    shas = sorted(
        entry for entry in os.listdir(models_dir)
        if os.path.isdir(os.path.join(models_dir, entry))
    )
    if not shas:
        return None
    return os.path.join(models_dir, shas[0])


@typechecked
def _ms_snapshot(root: str, model: str) -> Optional[str]:
    """Probe a ModelScope-layout cache root.

    Returns `<root>/models/<org>/<repo>/` iff it is a directory, else None.
    """
    if '/' not in model:
        return None
    org, repo = model.split('/', 1)
    candidate = os.path.join(root, 'models', org, repo)
    if os.path.isdir(candidate):
        return candidate
    return None


@typechecked
def _cache_dir_snapshot(cache_dir: str, model: str) -> Optional[str]:
    """L5 auto-probe: try HF layout, fall back to MS layout.

    Used only by the L5 CacheLevel constructed inside resolve() when the
    per-call cache_dir argument is not None. See 03-design.md §4.
    """
    hf_hit = _hf_snapshot(cache_dir, model)
    if hf_hit is not None:
        return hf_hit
    return _ms_snapshot(cache_dir, model)


@typechecked
def _hf_env_root() -> Optional[str]:
    """L1 root from `HF_HOME` or `HUGGINGFACE_HUB_CACHE`.

    Returns `<resolved>/hub` (parent -> cache root), or None if neither
    env var is set. `HF_HOME` takes precedence when both are set.
    See 03-design.md §3.3 step 2 and §7.
    """
    if 'HF_HOME' in os.environ and os.environ['HF_HOME']:
        return os.path.join(os.environ['HF_HOME'], 'hub')
    if 'HUGGINGFACE_HUB_CACHE' in os.environ and os.environ['HUGGINGFACE_HUB_CACHE']:
        return os.path.join(os.environ['HUGGINGFACE_HUB_CACHE'], 'hub')
    return None


@typechecked
def _ms_env_root() -> Optional[str]:
    """L3 root from `MODELSCOPE_CACHE`. The MS env var is the cache root
    directly (no `hub/` suffix). Returns None if unset.
    See 03-design.md §3.3 step 4 and §7.
    """
    if 'MODELSCOPE_CACHE' in os.environ and os.environ['MODELSCOPE_CACHE']:
        return os.environ['MODELSCOPE_CACHE']
    return None


@typechecked
def walk_levels() -> List[CacheLevel]:
    """Build the 4-level chain (L5 is appended inside `resolve()` when needed).

    L1 (hf_env) is included iff `HF_HOME` or `HUGGINGFACE_HUB_CACHE` is set.
    L2 (hf_default) is always present.
    L3 (ms_env) is included iff `MODELSCOPE_CACHE` is set.
    L4 (ms_default) is always present.

    Env reads happen at every call (the resolver has no env cache). See
    03-design.md §3.3 step 1 and §5.
    """
    levels: List[CacheLevel] = []

    hf_env = _hf_env_root()
    if hf_env is not None:
        levels.append(CacheLevel(
            name='hf_env',
            root=hf_env,
            layout='hf',
            snapshot_for=functools.partial(_hf_snapshot, hf_env),
        ))

    levels.append(CacheLevel(
        name='hf_default',
        root=HF_DEFAULT_ROOT,
        layout='hf',
        snapshot_for=functools.partial(_hf_snapshot, HF_DEFAULT_ROOT),
    ))

    ms_env = _ms_env_root()
    if ms_env is not None:
        levels.append(CacheLevel(
            name='ms_env',
            root=ms_env,
            layout='ms',
            snapshot_for=functools.partial(_ms_snapshot, ms_env),
        ))

    levels.append(CacheLevel(
        name='ms_default',
        root=MS_DEFAULT_ROOT,
        layout='ms',
        snapshot_for=functools.partial(_ms_snapshot, MS_DEFAULT_ROOT),
    ))

    return levels


@typechecked
def resolve(
    model: str,
    cache_dir: Optional[str] = None,
) -> Optional[CacheLevel]:
    """Walk the chain and return the first level whose snapshot_for hits.

    L5 (cache_dir) is appended to the chain when `cache_dir is not None`.
    First match wins by walk order; if no level's `snapshot_for(model)`
    is non-None, returns None.

    Returns the winning `CacheLevel` (not a tuple). The caller invokes
    `level.snapshot_for(model)` to obtain the absolute snapshot path —
    `resolve` does not pre-resolve. The MCP server maps a None return to
    the `model_not_found` error.

    See 03-design.md §3.2.
    """
    levels = walk_levels()
    if cache_dir is not None:
        levels.append(CacheLevel(
            name='cache_dir',
            root=cache_dir,
            layout='hf',  # nominal; L5 layout is decided per-call by _cache_dir_snapshot
            snapshot_for=functools.partial(_cache_dir_snapshot, cache_dir),
        ))

    for level in levels:
        if level.snapshot_for(model) is not None:
            return level
    return None
