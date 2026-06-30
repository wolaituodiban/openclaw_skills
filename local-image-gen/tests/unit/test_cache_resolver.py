"""Unit tests for `local_image_gen.cache_resolver`.

Mirrors `dev-doc/cache_resolver/04-test-design.md` §3 + §4. Every public
function (CacheLevel, resolve, walk_levels) is covered; the three private
snapshot helpers (_hf_snapshot, _ms_snapshot, _cache_dir_snapshot) are
exercised in closed-form per §4.

Set-up pattern: every test runs in a tmpdir with `os.path.expanduser` patched
to redirect `~/.cache` into the tmpdir, and `local_image_gen.cache_resolver`
is reloaded so the module-level `HF_DEFAULT_ROOT` and `MS_DEFAULT_ROOT`
constants re-evaluate against the patched `HOME`. Without the reload, the
constants would still point at the real `~/.cache` (frozen at first import).
See 04-test-design §8 Q5.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import shutil
import tempfile
import unittest
import unittest.mock

from local_image_gen import cache_resolver as cr_module
from local_image_gen.cache_resolver import resolve, walk_levels


def current_cache_level_class() -> type:
    """Return the current `CacheLevel` class object from `cr_module`.

    Must be called at runtime (not at import time) because setUp reloads
    the module, which replaces the class object. A module-level import
    keeps a stale reference that fails `isinstance` after the reload.
    """
    return cr_module.CacheLevel


# ---------------------------------------------------------------------------
# Test fixture base
# ---------------------------------------------------------------------------

class _CacheResolverTestBase(unittest.TestCase):
    """Shared setUp: tmpdir + HOME patch + module reload.

    All test classes that need a clean HOME-rooted resolver inherit from this.
    `addCleanup` (stdlib unittest) is used over manual try/finally per
    python-coding-rules §5 + §8.5.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix='cr_test_')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        # Make `os.path.expanduser('~/.cache/...')` resolve inside tmpdir.
        # `~` -> tmpdir; `~/...` -> tmpdir/...
        self._expanduser_patcher = unittest.mock.patch(
            'os.path.expanduser',
            side_effect=lambda p: self.tmpdir + p[1:] if p.startswith('~') else p,
        )
        self._expanduser_patcher.start()
        self.addCleanup(self._expanduser_patcher.stop)

        # Keep HOME aligned so anything else that reads it sees the tmpdir.
        self._env_patcher = unittest.mock.patch.dict(
            os.environ, {'HOME': self.tmpdir}, clear=False,
        )
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)

        # Force the module-level HF_DEFAULT_ROOT / MS_DEFAULT_ROOT to re-evaluate
        # against the patched `os.path.expanduser` and patched `HOME`.
        importlib.reload(cr_module)

    def addCleanup(self, function, *args, **kwargs):  # type: ignore[override]
        # Convenience: route all cleanups through unittest's addCleanup.
        super().addCleanup(function, *args, **kwargs)


# ---------------------------------------------------------------------------
# §3.1 CacheLevel
# ---------------------------------------------------------------------------

class CacheLevelConstructionTests(_CacheResolverTestBase):
    """§3.1: construction, layout values, callable contract, frozen, identity."""

    def test_construction_with_all_fields(self) -> None:
        level = cr_module.CacheLevel(
            name='hf_env', root='/tmp/x', layout='hf',
            snapshot_for=lambda m: None,
        )
        self.assertEqual(level.name, 'hf_env')
        self.assertEqual(level.root, '/tmp/x')
        self.assertEqual(level.layout, 'hf')
        self.assertIsNone(level.snapshot_for('any-model'))

    def test_construction_layout_values(self) -> None:
        cr_module.CacheLevel(name='hf_env', root='/r', layout='hf', snapshot_for=lambda m: None)
        cr_module.CacheLevel(name='ms_env', root='/r', layout='ms', snapshot_for=lambda m: None)

    def test_construction_callable_accepts_model(self) -> None:
        captured: list[str] = []

        def snap(model: str) -> str | None:
            captured.append(model)
            return '/snap'

        level = cr_module.CacheLevel(name='hf_env', root='/r', layout='hf', snapshot_for=snap)
        out = level.snapshot_for('Tongyi-MAI/Z-Image-Turbo')
        self.assertEqual(out, '/snap')
        self.assertEqual(captured, ['Tongyi-MAI/Z-Image-Turbo'])

    def test_frozen_rejects_field_mutation(self) -> None:
        level = cr_module.CacheLevel(name='hf_env', root='/r', layout='hf', snapshot_for=lambda m: None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            level.name = 'hf_default'  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            level.root = '/other'  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            level.layout = 'ms'  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            level.snapshot_for = lambda m: None  # type: ignore[misc]

    def test_eq_by_value(self) -> None:
        snap = lambda m: None
        a = cr_module.CacheLevel(name='hf_env', root='/r', layout='hf', snapshot_for=snap)
        b = cr_module.CacheLevel(name='hf_env', root='/r', layout='hf', snapshot_for=snap)
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# §3.2 resolve
# ---------------------------------------------------------------------------

class _ResolveTestBase(_CacheResolverTestBase):
    """Builds the 4 standard snapshot fixtures (HF env, HF default, MS env, MS
    default, plus a cache_dir) inside the test's tmpdir so `resolve` can find
    the model. `cr_module` constants already point inside the tmpdir after
    the base class's reload.
    """

    MODEL = 'Tongyi-MAI/Z-Image-Turbo'
    SHA = 'abc123'

    def _make_hf_snapshot(self, root: str) -> str:
        # Replicate 03 §3.3: HF env root already has `/hub` appended by
        # _hf_env_root(), so the cache_resolver calls _hf_snapshot on `<root>`
        # directly with root == `<env>/hub` or root == `HF_DEFAULT_ROOT`.
        snapshot_dir = os.path.join(
            root, f'models--Tongyi-MAI--Z-Image-Turbo', 'snapshots', self.SHA,
        )
        os.makedirs(snapshot_dir, exist_ok=True)
        return snapshot_dir

    def _make_ms_snapshot(self, root: str) -> str:
        snapshot_dir = os.path.join(root, 'models', 'Tongyi-MAI', 'Z-Image-Turbo')
        os.makedirs(snapshot_dir, exist_ok=True)
        return snapshot_dir


class ResolveHappyPathTests(_ResolveTestBase):
    """§3.2 happy-path: each level is the first match in turn."""

    def test_resolve_hits_l1_hf_env(self) -> None:
        hf_env_root = os.path.join(self.tmpdir, 'hf', 'hub')
        os.makedirs(hf_env_root, exist_ok=True)
        expected = self._make_hf_snapshot(hf_env_root)
        with unittest.mock.patch.dict(os.environ, {'HF_HOME': os.path.join(self.tmpdir, 'hf')}, clear=False):
            result = resolve(self.MODEL)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, current_cache_level_class())
        self.assertEqual(result.name, 'hf_env')
        self.assertEqual(result.snapshot_for(self.MODEL), expected)

    def test_resolve_hits_l2_hf_default_when_no_env(self) -> None:
        # HF_DEFAULT_ROOT is tmpdir/'.cache/huggingface/hub/' after reload.
        default_root = cr_module.HF_DEFAULT_ROOT
        self.assertTrue(default_root.startswith(self.tmpdir))
        expected = self._make_hf_snapshot(default_root)
        # Make sure no HF env vars are set.
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE'):
            os.environ.pop(var, None)
        result = resolve(self.MODEL)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'hf_default')
        self.assertEqual(result.snapshot_for(self.MODEL), expected)

    def test_resolve_hits_l3_ms_env(self) -> None:
        ms_env_root = os.path.join(self.tmpdir, 'ms')
        os.makedirs(ms_env_root, exist_ok=True)
        expected = self._make_ms_snapshot(ms_env_root)
        with unittest.mock.patch.dict(os.environ, {'MODELSCOPE_CACHE': ms_env_root}, clear=False):
            result = resolve(self.MODEL)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'ms_env')
        self.assertEqual(result.snapshot_for(self.MODEL), expected)

    def test_resolve_hits_l4_ms_default_when_no_env(self) -> None:
        default_root = cr_module.MS_DEFAULT_ROOT
        self.assertTrue(default_root.startswith(self.tmpdir))
        expected = self._make_ms_snapshot(default_root)
        os.environ.pop('MODELSCOPE_CACHE', None)
        result = resolve(self.MODEL)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'ms_default')
        self.assertEqual(result.snapshot_for(self.MODEL), expected)

    def test_resolve_hits_l5_cache_dir_hf(self) -> None:
        # cache_dir itself hosts a HF-layout snapshot.
        cache_dir = os.path.join(self.tmpdir, 'user_cache')
        os.makedirs(cache_dir, exist_ok=True)
        expected = self._make_hf_snapshot(cache_dir)
        # Make sure all other levels miss.
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        result = resolve(self.MODEL, cache_dir=cache_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'cache_dir')
        self.assertEqual(result.snapshot_for(self.MODEL), expected)

    def test_resolve_hits_l5_cache_dir_ms(self) -> None:
        cache_dir = os.path.join(self.tmpdir, 'user_cache_ms')
        os.makedirs(cache_dir, exist_ok=True)
        expected = self._make_ms_snapshot(cache_dir)
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        result = resolve(self.MODEL, cache_dir=cache_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'cache_dir')
        self.assertEqual(result.snapshot_for(self.MODEL), expected)


class ResolveConditionalTests(_ResolveTestBase):
    """§3.2 conditional / ordering / miss behavior."""

    def test_resolve_omits_l5_when_cache_dir_none(self) -> None:
        # Set cache_dir to a path that WOULD hit; with cache_dir=None it must not.
        cache_dir = os.path.join(self.tmpdir, 'would_hit')
        self._make_hf_snapshot(cache_dir)
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        self.assertIsNone(resolve(self.MODEL))  # cache_dir=None
        # Sanity: with cache_dir supplied, it does hit.
        self.assertIsNotNone(resolve(self.MODEL, cache_dir=cache_dir))

    def test_resolve_first_hit_wins(self) -> None:
        # L1 (HF env) and L2 (HF default) both contain the model -> L1 wins.
        hf_env_root = os.path.join(self.tmpdir, 'hf', 'hub')
        os.makedirs(hf_env_root, exist_ok=True)
        self._make_hf_snapshot(hf_env_root)
        self._make_hf_snapshot(cr_module.HF_DEFAULT_ROOT)
        for var in ('HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        with unittest.mock.patch.dict(os.environ, {'HF_HOME': os.path.join(self.tmpdir, 'hf')}, clear=False):
            result = resolve(self.MODEL)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'hf_env')

    def test_resolve_returns_none_when_all_levels_miss(self) -> None:
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        self.assertIsNone(resolve(self.MODEL))
        # cache_dir that doesn't exist -> still None.
        self.assertIsNone(resolve(self.MODEL, cache_dir=os.path.join(self.tmpdir, 'nope')))

    def test_resolve_returns_none_for_malformed_model_id(self) -> None:
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        self.assertIsNone(resolve('no-slash'))
        self.assertIsNone(resolve('a/b/c/too-many'))

    def test_resolve_returns_cache_level_or_none(self) -> None:
        cache_dir = os.path.join(self.tmpdir, 'ct_user')
        os.makedirs(cache_dir, exist_ok=True)
        self._make_hf_snapshot(cache_dir)
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        result = resolve(self.MODEL, cache_dir=cache_dir)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, current_cache_level_class())
        self.assertIn(result.name, {'hf_env', 'hf_default', 'ms_env', 'ms_default', 'cache_dir'})
        # And on miss -> None.
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        self.assertIsNone(resolve('no-such-model-xyz/zzz'))


# ---------------------------------------------------------------------------
# §3.3 walk_levels
# ---------------------------------------------------------------------------

class WalkLevelsShapeTests(_CacheResolverTestBase):

    def test_walk_levels_returns_1_to_4_entries(self) -> None:
        cases = [
            ({'HF_HOME': '/h', 'MODELSCOPE_CACHE': '/m'}, 4),
            ({'HF_HOME': '/h'}, 3),
            ({'MODELSCOPE_CACHE': '/m'}, 3),
            ({}, 2),
        ]
        for env, expected_len in cases:
            with self.subTest(env=env):
                with unittest.mock.patch.dict(os.environ, env, clear=False):
                    levels = walk_levels()
                self.assertEqual(len(levels), expected_len)
                # L5 never appears.
                for level in levels:
                    self.assertNotEqual(level.name, 'cache_dir')

    def test_walk_levels_does_not_consult_anything_outside_env_and_constants(self) -> None:
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE'):
            os.environ.pop(var, None)
        levels = walk_levels()
        names = [l.name for l in levels]
        self.assertEqual(names, ['hf_default', 'ms_default'])
        self.assertEqual(levels[0].root, cr_module.HF_DEFAULT_ROOT)
        self.assertEqual(levels[1].root, cr_module.MS_DEFAULT_ROOT)


class WalkLevelsL1Tests(_CacheResolverTestBase):

    def test_walk_levels_l1_present_when_hf_home_set(self) -> None:
        with unittest.mock.patch.dict(os.environ, {'HF_HOME': self.tmpdir}, clear=False):
            levels = walk_levels()
        self.assertEqual(levels[0].name, 'hf_env')
        self.assertEqual(levels[0].root, os.path.join(self.tmpdir, 'hub'))

    def test_walk_levels_l1_present_when_huggingface_hub_cache_set(self) -> None:
        env = {'HUGGINGFACE_HUB_CACHE': self.tmpdir}
        env.pop('HF_HOME', None)
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            levels = walk_levels()
        self.assertEqual(levels[0].name, 'hf_env')
        self.assertEqual(levels[0].root, os.path.join(self.tmpdir, 'hub'))

    def test_walk_levels_l1_omitted_when_neither_set(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE'):
                os.environ.pop(var, None)
            levels = walk_levels()
        names = [l.name for l in levels]
        self.assertNotIn('hf_env', names)

    def test_walk_levels_l1_hf_home_takes_precedence(self) -> None:
        env = {'HF_HOME': os.path.join(self.tmpdir, 'a'), 'HUGGINGFACE_HUB_CACHE': os.path.join(self.tmpdir, 'b')}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            levels = walk_levels()
        self.assertEqual(levels[0].root, os.path.join(self.tmpdir, 'a', 'hub'))


class WalkLevelsL2L3L4Tests(_CacheResolverTestBase):

    def test_walk_levels_l2_always_present(self) -> None:
        levels = walk_levels()
        names = [l.name for l in levels]
        self.assertIn('hf_default', names)
        l2 = next(l for l in levels if l.name == 'hf_default')
        self.assertEqual(l2.root, cr_module.HF_DEFAULT_ROOT)
        self.assertEqual(l2.layout, 'hf')

    def test_walk_levels_l3_present_when_modelscope_cache_set(self) -> None:
        with unittest.mock.patch.dict(os.environ, {'MODELSCOPE_CACHE': self.tmpdir}, clear=False):
            levels = walk_levels()
        names = [l.name for l in levels]
        self.assertIn('ms_env', names)
        l3 = next(l for l in levels if l.name == 'ms_env')
        # MS env var is the cache root DIRECTLY (no /hub suffix).
        self.assertEqual(l3.root, self.tmpdir)
        self.assertEqual(l3.layout, 'ms')

    def test_walk_levels_l3_omitted_when_unset(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MODELSCOPE_CACHE', None)
            levels = walk_levels()
        names = [l.name for l in levels]
        self.assertNotIn('ms_env', names)

    def test_walk_levels_l4_always_present(self) -> None:
        levels = walk_levels()
        l4 = next(l for l in levels if l.name == 'ms_default')
        self.assertEqual(l4.root, cr_module.MS_DEFAULT_ROOT)
        self.assertEqual(l4.layout, 'ms')


class WalkLevelsLayoutAndOrderTests(_CacheResolverTestBase):

    def test_walk_levels_l1_and_l2_layout_hf(self) -> None:
        with unittest.mock.patch.dict(os.environ, {'HF_HOME': self.tmpdir}, clear=False):
            levels = walk_levels()
        for level in levels:
            if level.name in ('hf_env', 'hf_default'):
                self.assertEqual(level.layout, 'hf')

    def test_walk_levels_l3_and_l4_layout_ms(self) -> None:
        with unittest.mock.patch.dict(os.environ, {'MODELSCOPE_CACHE': self.tmpdir}, clear=False):
            levels = walk_levels()
        for level in levels:
            if level.name in ('ms_env', 'ms_default'):
                self.assertEqual(level.layout, 'ms')

    def test_walk_levels_walk_order_l1_to_l4(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {'HF_HOME': self.tmpdir, 'MODELSCOPE_CACHE': self.tmpdir},
            clear=False,
        ):
            levels = walk_levels()
        self.assertEqual(
            [l.name for l in levels],
            ['hf_env', 'hf_default', 'ms_env', 'ms_default'],
        )

    def test_walk_levels_re_reads_env_each_call(self) -> None:
        # 1) baseline (no HF env vars) -> L1 absent
        for var in ('HF_HOME', 'HUGGINGFACE_HUB_CACHE'):
            os.environ.pop(var, None)
        self.assertNotIn('hf_env', [l.name for l in walk_levels()])

        # 2) set HF_HOME -> L1 appears immediately
        os.environ['HF_HOME'] = self.tmpdir
        self.assertIn('hf_env', [l.name for l in walk_levels()])

        # 3) unset -> L1 gone again
        del os.environ['HF_HOME']
        self.assertNotIn('hf_env', [l.name for l in walk_levels()])


# ---------------------------------------------------------------------------
# §4 closed-form: _hf_snapshot
# ---------------------------------------------------------------------------

class HfSnapshotTests(_CacheResolverTestBase):

    MODEL = 'Tongyi-MAI/Z-Image-Turbo'

    def _make_hf(self, root: str, shas: list[str]) -> str:
        snapshots = os.path.join(root, 'models--Tongyi-MAI--Z-Image-Turbo', 'snapshots')
        for sha in shas:
            os.makedirs(os.path.join(snapshots, sha), exist_ok=True)
        return snapshots

    def test_hf_snapshot_returns_smallest_sha_when_multiple(self) -> None:
        root = os.path.join(self.tmpdir, 'hf')
        os.makedirs(root, exist_ok=True)
        self._make_hf(root, ['zzz', 'aaa', 'mmm'])
        out = cr_module._hf_snapshot(root, self.MODEL)
        self.assertIsNotNone(out)
        # aaa < mmm < zzz lexicographically.
        self.assertTrue(out.endswith('aaa'))

    def test_hf_snapshot_returns_none_for_missing_root(self) -> None:
        missing = os.path.join(self.tmpdir, 'never_created')
        self.assertIsNone(cr_module._hf_snapshot(missing, self.MODEL))

    def test_hf_snapshot_returns_none_for_missing_model_subdir(self) -> None:
        root = os.path.join(self.tmpdir, 'hf')
        os.makedirs(root, exist_ok=True)
        # snapshots dir itself does not exist for the model.
        self.assertIsNone(cr_module._hf_snapshot(root, self.MODEL))

    def test_hf_snapshot_returns_none_for_empty_snapshots_dir(self) -> None:
        root = os.path.join(self.tmpdir, 'hf')
        os.makedirs(root, exist_ok=True)
        os.makedirs(
            os.path.join(root, 'models--Tongyi-MAI--Z-Image-Turbo', 'snapshots'),
            exist_ok=True,
        )
        self.assertIsNone(cr_module._hf_snapshot(root, self.MODEL))


# ---------------------------------------------------------------------------
# §4 closed-form: _ms_snapshot
# ---------------------------------------------------------------------------

class MsSnapshotTests(_CacheResolverTestBase):

    MODEL = 'Tongyi-MAI/Z-Image-Turbo'

    def test_ms_snapshot_returns_path_for_existing_model(self) -> None:
        root = os.path.join(self.tmpdir, 'ms')
        expected = os.path.join(root, 'models', 'Tongyi-MAI', 'Z-Image-Turbo')
        os.makedirs(expected, exist_ok=True)
        self.assertEqual(cr_module._ms_snapshot(root, self.MODEL), expected)

    def test_ms_snapshot_returns_none_for_missing_root(self) -> None:
        self.assertIsNone(cr_module._ms_snapshot(os.path.join(self.tmpdir, 'nope'), self.MODEL))

    def test_ms_snapshot_returns_none_for_missing_model(self) -> None:
        root = os.path.join(self.tmpdir, 'ms')
        os.makedirs(root, exist_ok=True)
        # models/Tongyi-MAI/Z-Image-Turbo not present.
        self.assertIsNone(cr_module._ms_snapshot(root, self.MODEL))


# ---------------------------------------------------------------------------
# §4 closed-form: _cache_dir_snapshot
# ---------------------------------------------------------------------------

class CacheDirSnapshotTests(_CacheResolverTestBase):

    MODEL = 'Tongyi-MAI/Z-Image-Turbo'

    def test_cache_dir_snapshot_hf_layout_wins(self) -> None:
        # Both layouts present; HF wins (probed first).
        cache_dir = os.path.join(self.tmpdir, 'both')
        os.makedirs(cache_dir, exist_ok=True)
        hf_snap = os.path.join(
            cache_dir, 'models--Tongyi-MAI--Z-Image-Turbo', 'snapshots', 'hf_sha',
        )
        ms_dir = os.path.join(cache_dir, 'models', 'Tongyi-MAI', 'Z-Image-Turbo')
        os.makedirs(hf_snap, exist_ok=True)
        os.makedirs(ms_dir, exist_ok=True)
        self.assertEqual(cr_module._cache_dir_snapshot(cache_dir, self.MODEL), hf_snap)

    def test_cache_dir_snapshot_ms_layout_fallback(self) -> None:
        cache_dir = os.path.join(self.tmpdir, 'ms_only')
        os.makedirs(cache_dir, exist_ok=True)
        ms_dir = os.path.join(cache_dir, 'models', 'Tongyi-MAI', 'Z-Image-Turbo')
        os.makedirs(ms_dir, exist_ok=True)
        self.assertEqual(cr_module._cache_dir_snapshot(cache_dir, self.MODEL), ms_dir)

    def test_cache_dir_snapshot_returns_none_when_neither_layout_matches(self) -> None:
        cache_dir = os.path.join(self.tmpdir, 'empty')
        os.makedirs(cache_dir, exist_ok=True)
        self.assertIsNone(cr_module._cache_dir_snapshot(cache_dir, self.MODEL))

    def test_cache_dir_snapshot_silent_skip_on_mismatch(self) -> None:
        # cache_dir contains some other model -> silent None, no exception.
        cache_dir = os.path.join(self.tmpdir, 'wrong_model')
        os.makedirs(os.path.join(cache_dir, 'models', 'Other', 'Repo'), exist_ok=True)
        self.assertIsNone(cr_module._cache_dir_snapshot(cache_dir, self.MODEL))


if __name__ == '__main__':
    unittest.main()
