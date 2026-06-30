"""Unit tests for start_service MCP tool.

start_service is NON-BLOCKING (returns status=loading within ms) and
launches a background daemon thread (_background_poll_ready) that polls
/v1/models and updates service.json["status"] to "ready" on success.

These tests mock threading.Thread to verify the thread is started with
the right target and args, and mock _background_poll_ready to verify the
right (port, pid, timeout) is passed.
"""

import asyncio
import json
import os
import pathlib
import threading
import unittest
from unittest.mock import MagicMock, patch

import local_image_gen.mcp_server as srv
import local_image_gen.cache_resolver as cr
from local_image_gen.cache_resolver import CacheLevel
from tests.unit.mcp_server._mixins import _MockPopenMixin


class TestStartService(_MockPopenMixin, unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    # --- Happy path ---

    async def test_returns_loading_dict_immediately(self) -> None:
        """Non-blocking start → dict with status='loading'."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        for key in ("model", "pid", "port", "status"):
            self.assertIn(key, result)
        self.assertEqual(result["status"], "loading")
        self.assertEqual(result["model"], "org/repo")
        self.assertEqual(result["pid"], 12345)
        self.assertEqual(result["port"], 4711)

    async def test_writes_service_json_with_loading_status(self) -> None:
        """service.json written with status='loading' immediately after spawn."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json") as mock_write, \
             patch("threading.Thread"):
            await srv.start_service("org/repo")

        written = mock_write.call_args[0][0]
        self.assertEqual(written["model"], "org/repo")
        self.assertEqual(written["port"], 4711)
        self.assertEqual(written["cache_source"], "hf_env")
        self.assertEqual(written["status"], "loading")
        self.assertIn("started_at", written)
        self.assertIn("pid", written)
        self.assertIn("model_path", written)

    async def test_starts_background_poll_thread(self) -> None:
        """Non-blocking start → threading.Thread is constructed and started."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread") as mock_thread_cls:
            await srv.start_service("org/repo")

        mock_thread_cls.assert_called_once()
        kwargs = mock_thread_cls.call_args[1]
        self.assertIs(kwargs["target"], srv._background_poll_ready)
        self.assertEqual(kwargs["args"], (4711, 12345, 120.0))
        self.assertTrue(kwargs["daemon"])
        # The constructed Thread was .start()'d
        mock_thread_cls.return_value.start.assert_called_once()

    async def test_picks_free_port(self) -> None:
        """_pick_free_port returns 4711 → result.port = 4711."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        self.assertEqual(result["port"], 4711)

    async def test_no_bearer_token_in_result_or_cli(self) -> None:
        """No api-key flag → no bearer_token in result or CLI args."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc) as mock_spawn, \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        self.assertNotIn("bearer_token", result)
        spawn_args = mock_spawn.call_args[0][0]
        self.assertNotIn("--api-key", spawn_args)

    async def test_passes_cache_dir_to_resolver(self) -> None:
        """cache_dir='/custom/cache' → resolve called with cache_dir."""
        resolved = CacheLevel(
            name="cache_dir", root="/custom/cache", layout="hf",
            snapshot_for=lambda m: "/custom/cache/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved) as mock_resolve, \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread"):
            await srv.start_service("org/repo", cache_dir="/custom/cache")

        mock_resolve.assert_called_once_with("org/repo", cache_dir="/custom/cache")

    async def test_timeoutMs_overrides_default(self) -> None:
        """timeoutMs=10_000 → background poll timeout = 10s."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread") as mock_thread_cls:
            await srv.start_service("org/repo", timeoutMs=10_000)

        kwargs = mock_thread_cls.call_args[1]
        self.assertEqual(kwargs["args"], (4711, 12345, 10.0))

    async def test_no_timeoutMs_uses_default_120(self) -> None:
        """No timeoutMs → background poll timeout = 120s."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread") as mock_thread_cls:
            await srv.start_service("org/repo")

        kwargs = mock_thread_cls.call_args[1]
        self.assertEqual(kwargs["args"], (4711, 12345, 120.0))

    async def test_poll_timeout_zero_uses_default(self) -> None:
        """timeoutMs=0 → treated as 'use default' → 120s."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread") as mock_thread_cls:
            await srv.start_service("org/repo", timeoutMs=0)

        kwargs = mock_thread_cls.call_args[1]
        self.assertEqual(kwargs["args"], (4711, 12345, 120.0))

    async def test_skips_thread_if_already_alive(self) -> None:
        """If a live poll thread already exists for this PID, don't start a new one."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        # Pre-populate the registry with a "live" thread for this PID
        live_thread = MagicMock(spec=threading.Thread)
        live_thread.is_alive.return_value = True
        srv._poll_threads[12345] = live_thread

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread") as mock_thread_cls:
            await srv.start_service("org/repo")

        mock_thread_cls.assert_not_called()
        # Registry still holds the same live thread
        self.assertIs(srv._poll_threads[12345], live_thread)
        # Cleanup the registry so tearDown doesn't crash on thread refs
        srv._poll_threads.pop(12345, None)

    async def test_replaces_dead_thread_in_registry(self) -> None:
        """If a dead poll thread exists for this PID, replace it with a new one."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snapshots/org/repo",
        )

        dead_thread = MagicMock(spec=threading.Thread)
        dead_thread.is_alive.return_value = False
        srv._poll_threads[12345] = dead_thread

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread") as mock_thread_cls:
            await srv.start_service("org/repo")

        mock_thread_cls.assert_called_once()
        # Registry now holds the new mock thread
        self.assertIs(srv._poll_threads[12345], mock_thread_cls.return_value)
        srv._poll_threads.pop(12345, None)

    # --- Error path ---

    async def test_returns_model_not_found_when_resolver_returns_none(self) -> None:
        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=None), \
             patch.object(srv, "_spawn_vllm_omni") as mock_spawn, \
             patch.object(srv, "_write_service_json") as mock_write, \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        self.assertEqual(result["error"]["code"], "model_not_found")
        mock_spawn.assert_not_called()
        mock_write.assert_not_called()

    async def test_returns_service_already_running(self) -> None:
        self.make_alive_pid_mock(pid=999)

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "status": "ready",
        }):
            result = await srv.start_service("org/repo")

        self.assertEqual(result["error"]["code"], "service_already_running")
        self.assertIn("org/repo", result["error"]["message"])

    async def test_prunes_stale_service_json_then_proceeds(self) -> None:
        """Dead PID → prune, then resolve and spawn."""
        self.make_dead_pid_mock(pid=999)
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snap/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value={
            "model": "org/repo", "pid": 999, "status": "ready",
        }), \
             patch.object(srv, "_prune_stale_service_json") as mock_prune, \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json"), \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        mock_prune.assert_called_once()
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "loading")

    async def test_returns_loading_even_if_proc_exits_immediately(self) -> None:
        """Non-blocking start does not check proc exit; returns loading."""
        self.mock_proc.poll.return_value = 1
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snap/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json") as mock_write, \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        self.assertEqual(result["status"], "loading")
        mock_write.assert_called_once()

    async def test_does_not_block_on_poll(self) -> None:
        """Non-blocking start returns immediately; _background_poll_ready
        is the thread target, not awaited."""
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snap/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json") as mock_write, \
             patch.object(srv, "_release_subprocess") as mock_release, \
             patch("threading.Thread"):
            result = await srv.start_service("org/repo")

        self.assertEqual(result["status"], "loading")
        mock_release.assert_not_called()
        mock_write.assert_called_once()

    async def test_raises_oserror_when_service_json_write_fails(self) -> None:
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snap/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", return_value=self.mock_proc), \
             patch.object(srv, "_write_service_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await srv.start_service("org/repo")

    async def test_raises_filenotfounderror_when_vllm_binary_missing(self) -> None:
        resolved = CacheLevel(
            name="hf_env", root="/hf_cache", layout="hf",
            snapshot_for=lambda m: "/snap/org/repo",
        )

        with patch.object(srv, "_read_service_json", return_value=None), \
             patch.object(srv.cr, "resolve", return_value=resolved), \
             patch.object(srv, "_pick_free_port", return_value=4711), \
             patch.object(srv, "_spawn_vllm_omni", side_effect=FileNotFoundError("vllm not found")):
            with self.assertRaises(FileNotFoundError):
                await srv.start_service("org/repo")
