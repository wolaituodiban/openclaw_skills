"""Unit tests for release_service MCP tool."""

import json
import os
import pathlib
import unittest
from unittest.mock import patch

import local_image_gen.mcp_server as srv
from tests.unit.mcp_server._mixins import _MockPopenMixin


class TestReleaseService(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()
        self._svc_data = {
            "model": "org/repo", "pid": 12345, "port": 9999,
            "started_at": 100.0, "status": "ready",
        }

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    # --- Happy path ---

    def test_stops_subprocess_and_removes_service_json(self) -> None:
        self.make_alive_pid_mock(pid=12345)
        self.write_service_json(self._svc_data)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_release_subprocess") as mock_release:
            srv.release_service("org/repo")

        mock_release.assert_called_once_with(12345)
        self.assertFalse(self.service_json_path.exists())

    def test_returns_released_true_with_model_pid_port(self) -> None:
        self.make_alive_pid_mock(pid=12345)
        self.write_service_json(self._svc_data)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_release_subprocess"):
            result = srv.release_service("org/repo")

        self.assertTrue(result["released"])
        self.assertEqual(result["model"], "org/repo")
        self.assertEqual(result["pid"], 12345)
        self.assertEqual(result["port"], 9999)

    def test_clears_poll_thread_for_released_pid(self) -> None:
        """release_service pops the background poll thread from the registry."""
        self.make_alive_pid_mock(pid=12345)
        self.write_service_json(self._svc_data)

        import threading
        srv._poll_threads[12345] = threading.Thread(
            target=lambda: None, daemon=True
        )

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_release_subprocess"):
            srv.release_service("org/repo")

        self.assertNotIn(12345, srv._poll_threads)

    def test_idempotent_no_service_returns_no_running_service(self) -> None:
        with patch.object(srv, "_read_service_json", return_value=None):
            result = srv.release_service("org/repo")
        self.assertEqual(result["error"]["code"], "no_running_service")

    def test_idempotent_dead_pid_returns_no_running_service(self) -> None:
        self.make_dead_pid_mock(pid=12345)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_prune_stale_service_json"):
            result = srv.release_service("org/repo")

        self.assertEqual(result["error"]["code"], "no_running_service")

    # --- Error path ---

    def test_model_mismatch_returns_model_not_loaded(self) -> None:
        self.make_alive_pid_mock(pid=12345)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data):
            result = srv.release_service("other/repo")

        self.assertEqual(result["error"]["code"], "model_not_loaded")

    def test_raises_oserror_when_service_json_unreadable(self) -> None:
        with patch.object(
            srv, "_read_service_json",
            side_effect=PermissionError("perm"),
        ):
            with self.assertRaises(PermissionError):
                srv.release_service("org/repo")

    def test_raises_oserror_when_remove_fails(self) -> None:
        self.make_alive_pid_mock(pid=12345)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_release_subprocess"), \
             patch("local_image_gen.mcp_server.os.remove", side_effect=OSError("perm")):
            with self.assertRaises(OSError):
                srv.release_service("org/repo")

    def test_raises_oserror_when_release_subprocess_fails(self) -> None:
        self.make_alive_pid_mock(pid=12345)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_release_subprocess", side_effect=OSError("kill failed")):
            with self.assertRaises(OSError):
                srv.release_service("org/repo")

    # --- Edge path ---

    def test_empty_model_string_returns_model_not_loaded(self) -> None:
        self.make_alive_pid_mock(pid=12345)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data):
            result = srv.release_service("")

        self.assertEqual(result["error"]["code"], "model_not_loaded")

    def test_clears_poll_thread_only_for_released_pid(self) -> None:
        """Other PIDs' poll threads are untouched."""
        import threading

        self.make_alive_pid_mock(pid=12345)
        self.write_service_json(self._svc_data)
        srv._poll_threads[12345] = threading.Thread(target=lambda: None, daemon=True)
        srv._poll_threads[88888] = threading.Thread(target=lambda: None, daemon=True)

        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_release_subprocess"):
            srv.release_service("org/repo")

        self.assertNotIn(12345, srv._poll_threads)
        self.assertIn(88888, srv._poll_threads)
