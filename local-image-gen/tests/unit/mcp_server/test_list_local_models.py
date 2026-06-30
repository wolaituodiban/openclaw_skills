"""Unit tests for list_local_models MCP tool."""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import local_image_gen.mcp_server as srv
import local_image_gen.cache_resolver as cr
from local_image_gen.cache_resolver import CacheLevel
from tests.unit.mcp_server._mixins import _MockPopenMixin


class TestListLocalModels(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    # --- Happy path (7 tests) --- #

    def test_list_local_models_no_models_visible_returns_empty_list(self) -> None:
        """Empty levels, no service file → empty list."""
        with patch.object(srv, "_read_service_json", return_value=None):
            with patch.object(srv.cr, "walk_levels", return_value=[]):
                result = srv.list_local_models()
        self.assertEqual(result, [])

    def test_list_local_models_hf_layout_enumerates_models(self) -> None:
        """HF layout: models--org--repo/ → one model entry."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)

        with patch.object(srv, "_read_service_json", return_value=None):
            with patch.object(srv.cr, "walk_levels", return_value=[level]):
                result = srv.list_local_models()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["model"], "org/repo")
        self.assertEqual(result[0]["current_load_status"], "not_loaded")

    def test_list_local_models_ms_layout_enumerates_models(self) -> None:
        """MS layout: models/org/repo/ → one model entry."""
        ms_root = self.tmpdir / "ms_cache"
        ms_root.mkdir()
        (ms_root / "models" / "org" / "repo").mkdir(parents=True)

        level = CacheLevel(name="ms_default", root=str(ms_root), layout="ms", snapshot_for=lambda m: None)

        with patch.object(srv, "_read_service_json", return_value=None):
            with patch.object(srv.cr, "walk_levels", return_value=[level]):
                result = srv.list_local_models()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["model"], "org/repo")

    def test_list_local_models_service_ready_marks_model_loaded(self) -> None:
        """service.json with status=ready and PID alive → loaded."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv.cr, "walk_levels", return_value=[level]):
            with patch.object(srv, "_read_service_json", return_value={
                "model": "org/repo", "pid": 999, "status": "ready",
            }):
                result = srv.list_local_models()
        self.assertEqual(result[0]["current_load_status"], "loaded")

    def test_list_local_models_service_loading_marks_model_loading(self) -> None:
        """service.json with status=loading → loading."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv.cr, "walk_levels", return_value=[level]):
            with patch.object(srv, "_read_service_json", return_value={
                "model": "org/repo", "pid": 999, "status": "loading",
            }):
                result = srv.list_local_models()
        self.assertEqual(result[0]["current_load_status"], "loading")

    def test_list_local_models_single_service_invariant_holds(self) -> None:
        """Two models visible; only one can be loaded/loading."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()
        (hf_root / "models--org--other").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv.cr, "walk_levels", return_value=[level]):
            with patch.object(srv, "_read_service_json", return_value={
                "model": "org/repo", "pid": 999, "status": "ready",
            }):
                result = srv.list_local_models()
        loaded_count = sum(1 for e in result if e["current_load_status"] in ("loading", "loaded"))
        self.assertLessEqual(loaded_count, 1)

    def test_list_local_models_results_sorted_by_model(self) -> None:
        """Three models in non-sorted order → result sorted lexicographically."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--z--repo").mkdir()
        (hf_root / "models--a--repo").mkdir()
        (hf_root / "models--m--repo").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)

        with patch.object(srv.cr, "walk_levels", return_value=[level]):
            with patch.object(srv, "_read_service_json", return_value=None):
                result = srv.list_local_models()
        models = [e["model"] for e in result]
        self.assertEqual(models, sorted(models))

    # --- Error path (4 tests) --- #

    def test_list_local_models_raises_oserror_when_service_json_unreadable(self) -> None:
        """PermissionError on service.json read → raised."""
        with patch.object(srv, "_read_service_json", side_effect=PermissionError("perm denied")):
            with patch.object(srv.cr, "walk_levels", return_value=[]):
                with self.assertRaises(PermissionError):
                    srv.list_local_models()

    def test_list_local_models_raises_jsondecodeerror_when_service_json_malformed(self) -> None:
        """Malformed JSON in service.json → json.JSONDecodeError raised."""
        self.write_service_json({"model": "org/repo"})  # write valid JSON
        # Overwrite with invalid JSON
        self.service_json_path.write_text("{invalid", encoding="utf-8")

        with patch.object(srv.cr, "walk_levels", return_value=[]):
            with self.assertRaises(json.JSONDecodeError):
                srv.list_local_models()

    def test_list_local_models_raises_cache_resolver_error_when_all_levels_fail(self) -> None:
        """CacheResolverError from walk_levels → raised."""
        class CacheResolverError(Exception):
            pass

        with patch.object(srv.cr, "walk_levels", side_effect=CacheResolverError("all levels failed")):
            with self.assertRaises(CacheResolverError):
                srv.list_local_models()

    def test_list_local_models_prunes_stale_service_json_returns_enumeration(self) -> None:
        """Dead PID → file pruned, returns disk enumeration."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)
        self.make_dead_pid_mock(pid=999)

        with patch.object(srv.cr, "walk_levels", return_value=[level]):
            with patch.object(srv, "_read_service_json", return_value={
                "model": "org/repo", "pid": 999, "status": "ready",
            }):
                with patch.object(srv, "_prune_stale_service_json") as mock_prune:
                    result = srv.list_local_models()
        mock_prune.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["current_load_status"], "not_loaded")

    # --- Edge path (3 tests) --- #

    def test_list_local_models_empty_string_model_field_treated_as_not_loaded(self) -> None:
        """service.json with model="" → no entry gets loaded status."""
        hf_root = self.tmpdir / "hf_cache"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()

        level = CacheLevel(name="hf_default", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv.cr, "walk_levels", return_value=[level]):
            with patch.object(srv, "_read_service_json", return_value={
                "model": "", "pid": 999, "status": "ready",
            }):
                result = srv.list_local_models()
        loaded_count = sum(1 for e in result if e["current_load_status"] in ("loading", "loaded"))
        self.assertEqual(loaded_count, 0)

    def test_list_local_models_visibility_dedup_keeps_first_level(self) -> None:
        """Same model at L1 and L2 → one entry (L1 wins)."""
        hf_root = self.tmpdir / "hf_L1"
        hf_root.mkdir()
        (hf_root / "models--org--repo").mkdir()

        ms_root = self.tmpdir / "ms_L2"
        ms_root.mkdir()
        (ms_root / "models" / "org" / "repo").mkdir(parents=True)

        l1 = CacheLevel(name="hf_env", root=str(hf_root), layout="hf", snapshot_for=lambda m: None)
        l2 = CacheLevel(name="ms_env", root=str(ms_root), layout="ms", snapshot_for=lambda m: None)

        with patch.object(srv.cr, "walk_levels", return_value=[l1, l2]):
            with patch.object(srv, "_read_service_json", return_value=None):
                result = srv.list_local_models()
        self.assertEqual(len(result), 1)

    def test_list_local_models_visibility_dedup_keeps_first_level_across_all_5_levels_when_present(self) -> None:
        """Same model at L1-L4 → one entry (first level wins)."""
        levels = []
        for i in range(4):
            root = self.tmpdir / f"level_{i}"
            root.mkdir()
            (root / "models--org--repo").mkdir()
            levels.append(CacheLevel(name=f"level_{i}", root=str(root), layout="hf", snapshot_for=lambda m: None))

        with patch.object(srv.cr, "walk_levels", return_value=levels):
            with patch.object(srv, "_read_service_json", return_value=None):
                result = srv.list_local_models()
        self.assertEqual(len(result), 1)
