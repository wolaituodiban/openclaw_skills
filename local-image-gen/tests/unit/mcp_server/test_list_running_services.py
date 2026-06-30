"""Unit tests for list_running_services MCP tool."""

import json
import os
import pathlib
import unittest
from unittest.mock import patch

import local_image_gen.mcp_server as srv
from tests.unit.mcp_server._mixins import _MockPopenMixin


class TestListRunningServices(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    # --- Happy path ---

    def test_returns_empty_when_no_service_file(self) -> None:
        """No service.json → empty list."""
        with patch.object(srv, "_read_service_json", return_value=None):
            self.assertEqual(srv.list_running_services(), [])

    def test_returns_one_entry_when_service_running(self) -> None:
        """service.json with alive PID → one entry."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0, "status": "ready",
        }):
            result = srv.list_running_services()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["model"], "org/repo")
        self.assertEqual(result[0]["pid"], 999)
        self.assertEqual(result[0]["port"], 4711)
        self.assertEqual(result[0]["status"], "ready")

    def test_entry_has_required_keys(self) -> None:
        """Entry dict has keys: model, pid, port, started_at, status."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0, "status": "ready",
        }):
            result = srv.list_running_services()

        for key in ("model", "pid", "port", "started_at", "status"):
            self.assertIn(key, result[0])

    def test_single_service_invariant(self) -> None:
        """At most 1 entry ever."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0, "status": "ready",
        }):
            result = srv.list_running_services()

        self.assertLessEqual(len(result), 1)

    def test_reads_status_from_service_json(self) -> None:
        """Status field is read directly from service.json (no in-memory cache)."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0, "status": "loading",
        }):
            result = srv.list_running_services()

        self.assertEqual(result[0]["status"], "loading")

    def test_status_defaults_to_ready_when_field_absent(self) -> None:
        """Backward-compat: missing status field → "ready" (legacy v1 files)."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0,
        }):
            result = srv.list_running_services()

        self.assertEqual(result[0]["status"], "ready")

    # --- Error path ---

    def test_raises_oserror_when_service_json_unreadable(self) -> None:
        """PermissionError on service.json → propagated."""
        with patch.object(
            srv, "_read_service_json",
            side_effect=PermissionError("perm denied"),
        ):
            with self.assertRaises(PermissionError):
                srv.list_running_services()

    def test_raises_jsondecodeerror_when_service_json_malformed(self) -> None:
        """Malformed JSON → json.JSONDecodeError raised."""
        self.service_json_path.write_text("{invalid", encoding="utf-8")

        with self.assertRaises(json.JSONDecodeError):
            srv.list_running_services()

    def test_prunes_stale_service_json(self) -> None:
        """Dead PID → file pruned, returns []."""
        self.make_dead_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
        }), \
             patch.object(srv, "_prune_stale_service_json") as mock_prune:
            result = srv.list_running_services()

        mock_prune.assert_called_once()
        self.assertEqual(result, [])

    # --- Edge path ---

    def test_returns_loading_status_during_background_poll(self) -> None:
        """service.json has status="loading" → entry status = "loading"."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0, "status": "loading",
        }):
            result = srv.list_running_services()

        self.assertEqual(result[0]["status"], "loading")

    def test_returns_failed_status_after_background_poll_timeout(self) -> None:
        """service.json has status="failed" → entry status = "failed"."""
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "port": 4711,
            "started_at": 100.0, "status": "failed",
        }):
            result = srv.list_running_services()

        self.assertEqual(result[0]["status"], "failed")
