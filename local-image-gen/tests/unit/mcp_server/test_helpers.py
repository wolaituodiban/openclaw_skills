"""Unit tests for mcp_server internal helpers."""

import base64
import binascii
import json
import os
import pathlib
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import local_image_gen.mcp_server as srv
import local_image_gen.cache_resolver as cr
from local_image_gen.cache_resolver import CacheLevel
from tests.unit.mcp_server._mixins import _MockPopenMixin


class TestPickFreePort(unittest.TestCase):
    """_pick_free_port: open socket, read port, close."""

    def test_pick_free_port_returns_int_in_valid_range(self) -> None:
        port = srv._pick_free_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)

    def test_pick_free_port_returns_different_ports_on_sequential_calls(self) -> None:
        p1 = srv._pick_free_port()
        p2 = srv._pick_free_port()
        self.assertNotEqual(p1, p2)

    def test_pick_free_port_with_host_127_0_0_1(self) -> None:
        port = srv._pick_free_port("127.0.0.1")
        self.assertGreater(port, 0)

    def test_pick_free_port_socket_closed_after_use(self) -> None:
        port = srv._pick_free_port()
        # Verify the port is reusable (socket was closed)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))  # should not raise


class TestSpawnVllmOmni(unittest.TestCase):
    """_spawn_vllm_omni: Popen with stdout→stderr, new session."""

    @patch("local_image_gen.mcp_server.subprocess.Popen")
    def test_spawn_calls_popen_with_correct_args(self, mock_popen) -> None:
        args = ["vllm", "serve", "/model", "--port", "1234"]
        srv._spawn_vllm_omni(args)
        mock_popen.assert_called_once()

    @patch("local_image_gen.mcp_server.subprocess.Popen")
    def test_spawn_stdout_redirected_to_stderr(self, mock_popen) -> None:
        srv._spawn_vllm_omni(["vllm"])
        kwargs = mock_popen.call_args[1]
        self.assertEqual(kwargs["stdout"], srv.sys.stderr)

    @patch("local_image_gen.mcp_server.subprocess.Popen")
    def test_spawn_stderr_set_to_stdout(self, mock_popen) -> None:
        srv._spawn_vllm_omni(["vllm"])
        kwargs = mock_popen.call_args[1]
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)

    @patch("local_image_gen.mcp_server.subprocess.Popen")
    def test_spawn_start_new_session_true(self, mock_popen) -> None:
        srv._spawn_vllm_omni(["vllm"])
        kwargs = mock_popen.call_args[1]
        self.assertTrue(kwargs["start_new_session"])

    @patch("local_image_gen.mcp_server.subprocess.Popen")
    def test_spawn_raises_filenotfounderror_when_binary_missing(self, mock_popen) -> None:
        mock_popen.side_effect = FileNotFoundError("vllm not found")
        with self.assertRaises(FileNotFoundError):
            srv._spawn_vllm_omni(["vllm"])


class TestPollReady(unittest.TestCase):
    """_poll_ready: GET /v1/models until 200 or timeout."""

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_returns_true_on_200(self, mock_httpx) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp
        result = srv._poll_ready(9999, time.monotonic() + 10)
        self.assertTrue(result)

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_returns_false_on_timeout(self, mock_httpx) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_httpx.get.return_value = mock_resp
        # Very short deadline
        result = srv._poll_ready(9999, time.monotonic() + 0.01)
        self.assertFalse(result)

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_transient_http_error_retries(self, mock_httpx) -> None:
        import httpx as real_httpx
        mock_httpx.HTTPError = real_httpx.HTTPError
        mock_httpx.get.side_effect = real_httpx.HTTPError("conn refused")
        result = srv._poll_ready(9999, time.monotonic() + 0.01)
        self.assertFalse(result)

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_transient_connection_error_retries(self, mock_httpx) -> None:
        import httpx as real_httpx
        mock_httpx.HTTPError = real_httpx.HTTPError
        mock_httpx.get.side_effect = ConnectionError("refused")
        result = srv._poll_ready(9999, time.monotonic() + 0.01)
        self.assertFalse(result)

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_transient_oserror_retries(self, mock_httpx) -> None:
        import httpx as real_httpx
        mock_httpx.HTTPError = real_httpx.HTTPError
        mock_httpx.get.side_effect = OSError("net unreachable")
        result = srv._poll_ready(9999, time.monotonic() + 0.01)
        self.assertFalse(result)

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_sends_no_auth_header(self, mock_httpx) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp
        srv._poll_ready(9999, time.monotonic() + 10)
        call_kwargs = mock_httpx.get.call_args[1]
        self.assertNotIn("headers", call_kwargs)
        self.assertIn("timeout", call_kwargs)

    @patch("local_image_gen.mcp_server.httpx")
    def test_poll_url_uses_correct_port(self, mock_httpx) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp
        srv._poll_ready(4711, time.monotonic() + 10)
        call_args = mock_httpx.get.call_args[0]
        self.assertIn("4711", call_args[0])


class TestReadServiceJson(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    def test_read_returns_none_when_file_absent(self) -> None:
        result = srv._read_service_json()
        self.assertIsNone(result)

    def test_read_returns_parsed_dict_when_file_present(self) -> None:
        self.write_service_json({"model": "org/repo", "pid": 123})
        result = srv._read_service_json()
        self.assertEqual(result["model"], "org/repo")

    def test_read_raises_jsondecodeerror_on_malformed_json(self) -> None:
        self.service_json_path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            srv._read_service_json()


class TestWriteServiceJson(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    def test_write_creates_file_with_json_content(self) -> None:
        srv._write_service_json({"model": "org/repo", "pid": 123})
        data = json.loads(self.service_json_path.read_text())
        self.assertEqual(data["model"], "org/repo")

    def test_write_uses_atomic_replace(self) -> None:
        """After write, file exists and is valid JSON."""
        srv._write_service_json({"model": "a/b"})
        self.assertTrue(self.service_json_path.exists())
        data = json.loads(self.service_json_path.read_text())
        self.assertEqual(data["model"], "a/b")

    def test_write_overwrites_existing_file(self) -> None:
        self.write_service_json({"model": "old/repo"})
        srv._write_service_json({"model": "new/repo"})
        data = json.loads(self.service_json_path.read_text())
        self.assertEqual(data["model"], "new/repo")

    def test_write_raises_oserror_on_disk_full(self) -> None:
        with patch("local_image_gen.mcp_server.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                srv._write_service_json({"model": "a/b"})


class TestPruneStaleServiceJson(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    def test_prune_noop_when_file_absent(self) -> None:
        srv._prune_stale_service_json()  # should not raise
        self.assertFalse(self.service_json_path.exists())

    def test_prune_removes_file_when_pid_dead(self) -> None:
        self.make_dead_pid_mock(pid=999)
        self.write_service_json({"model": "org/repo", "pid": 999})
        srv._prune_stale_service_json()
        self.assertFalse(self.service_json_path.exists())

    def test_prune_keeps_file_when_pid_alive(self) -> None:
        self.make_alive_pid_mock(pid=999)
        self.write_service_json({"model": "org/repo", "pid": 999})
        srv._prune_stale_service_json()
        self.assertTrue(self.service_json_path.exists())

    def test_prune_raises_oserror_when_remove_fails(self) -> None:
        self.make_dead_pid_mock(pid=999)
        self.write_service_json({"model": "org/repo", "pid": 999})
        with patch("local_image_gen.mcp_server.os.remove", side_effect=OSError("perm")):
            with self.assertRaises(OSError):
                srv._prune_stale_service_json()


class TestReleaseSubprocess(unittest.TestCase):

    def test_release_uses_psutil_terminate_then_wait(self) -> None:
        import psutil
        with patch("local_image_gen.mcp_server.psutil") as mock_psutil:
            mock_proc = MagicMock()
            mock_proc.terminate.return_value = None
            mock_proc.wait.return_value = 0
            mock_psutil.Process.return_value = mock_proc
            srv._release_subprocess(12345)
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()

    def test_release_kills_after_timeout(self) -> None:
        import psutil
        with patch("local_image_gen.mcp_server.psutil") as mock_psutil:
            mock_proc = MagicMock()
            mock_proc.terminate.return_value = None
            mock_proc.wait.side_effect = psutil.TimeoutExpired(10)
            mock_proc.kill.return_value = None
            mock_psutil.Process.return_value = mock_proc
            mock_psutil.TimeoutExpired = psutil.TimeoutExpired
            srv._release_subprocess(12345)
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_release_fallback_os_kill_when_psutil_none(self) -> None:
        with patch.object(srv, "psutil", None), \
             patch("local_image_gen.mcp_server.os.kill") as mock_kill, \
             patch("local_image_gen.mcp_server.time.sleep"):
            mock_kill.return_value = None  # alive check passes
            srv._release_subprocess(12345)
        # SIGTERM then SIGKILL (alive check passes → SIGKILL)
        self.assertGreaterEqual(mock_kill.call_count, 2)

    def test_release_fallback_process_already_dead(self) -> None:
        with patch.object(srv, "psutil", None), \
             patch("local_image_gen.mcp_server.os.kill") as mock_kill, \
             patch("local_image_gen.mcp_server.time.sleep"):
            # First call (SIGTERM) succeeds, second call (alive check) → ProcessLookupError
            mock_kill.side_effect = [None, ProcessLookupError("dead")]
            srv._release_subprocess(12345)
        self.assertEqual(mock_kill.call_count, 2)


class TestRouteInvoke(unittest.TestCase):

    def _make_mock_client(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(b64_json="aGVsbG8=")]
        mock_client.images.generate.return_value = mock_response
        mock_client.images.edit.return_value = mock_response
        return mock_client

    def test_route_generate_calls_images_generate(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, None, None, None, None, 30.0,
        )
        client.images.generate.assert_called_once()

    def test_route_edit_calls_images_edit(self) -> None:
        client = self._make_mock_client()
        # Need a real image file for _local_path_to_data_url
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNGfake")
            img_path = f.name
        try:
            srv._route_invoke(
                client, "edit", "org/repo", True,
                img_path, None, None, "png", 1,
                None, None, None, None, None, 30.0,
            )
        finally:
            os.unlink(img_path)
        client.images.edit.assert_called_once()

    def test_route_generate_passes_size_when_provided(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, "1024x1024", "png", 1,
            None, None, None, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["size"], "1024x1024")

    def test_route_generate_omits_size_when_none(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, None, None, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertNotIn("size", kwargs)

    def test_route_generate_passes_extra_body_for_non_png_format(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "webp", 1,
            None, None, None, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertIn("extra_body", kwargs)
        self.assertEqual(kwargs["extra_body"]["output_format"], "webp")

    def test_route_generate_passes_negative_prompt_in_extra_body(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            "ugly", None, None, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["extra_body"]["negative_prompt"], "ugly")

    def test_route_generate_passes_num_inference_steps(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, 30, None, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["extra_body"]["num_inference_steps"], 30)

    def test_route_generate_passes_guidance_scale(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, None, 7.5, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["extra_body"]["guidance_scale"], 7.5)

    def test_route_generate_passes_true_cfg_scale(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, None, None, 2.0, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["extra_body"]["true_cfg_scale"], 2.0)

    def test_route_generate_passes_seed(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, None, None, None, 42, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["extra_body"]["seed"], 42)

    def test_route_count_clamped_to_minimum_one(self) -> None:
        client = self._make_mock_client()
        srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 0,
            None, None, None, None, None, 30.0,
        )
        kwargs = client.images.generate.call_args[1]
        self.assertEqual(kwargs["n"], 1)

    def test_route_returns_b64_json_list(self) -> None:
        client = self._make_mock_client()
        result = srv._route_invoke(
            client, "a cat", "org/repo", False,
            None, None, None, "png", 1,
            None, None, None, None, None, 30.0,
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "aGVsbG8=")


class TestDecodeAndPersist(unittest.TestCase):

    def test_decode_writes_bytes_to_target_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = pathlib.Path(td) / "out.png"
            b64 = base64.b64encode(b"\x89PNGfake").decode()
            srv._decode_and_persist([b64], [target], "png")
            self.assertEqual(target.read_bytes(), b"\x89PNGfake")

    def test_decode_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            targets = [pathlib.Path(td) / f"out-{i}.png" for i in range(3)]
            b64s = [base64.b64encode(f"img{i}".encode()).decode() for i in range(3)]
            srv._decode_and_persist(b64s, targets, "png")
            for i, t in enumerate(targets):
                self.assertEqual(t.read_bytes(), f"img{i}".encode())

    def test_decode_raises_binascii_error_on_invalid_b64(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = pathlib.Path(td) / "out.png"
            with self.assertRaises(binascii.Error):
                srv._decode_and_persist(["!!!invalid!!!"], [target], "png")

    def test_decode_raises_oserror_on_write_failure(self) -> None:
        target = pathlib.Path("/nonexistent/dir/out.png")
        b64 = base64.b64encode(b"fake").decode()
        with self.assertRaises(OSError):
            srv._decode_and_persist([b64], [target], "png")


class TestLocalPathToDataUrl(unittest.TestCase):

    def test_png_file_returns_correct_data_url(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNGfake")
            path = f.name
        try:
            url = srv._local_path_to_data_url(path)
        finally:
            os.unlink(path)
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_jpg_file_returns_jpeg_mime(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8fake")
            path = f.name
        try:
            url = srv._local_path_to_data_url(path)
        finally:
            os.unlink(path)
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))

    def test_webp_file_returns_webp_mime(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            f.write(b"RIFFfake")
            path = f.name
        try:
            url = srv._local_path_to_data_url(path)
        finally:
            os.unlink(path)
        self.assertTrue(url.startswith("data:image/webp;base64,"))

    def test_no_extension_defaults_to_png(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            url = srv._local_path_to_data_url(path)
        finally:
            os.unlink(path)
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_unknown_extension_defaults_to_png(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            url = srv._local_path_to_data_url(path)
        finally:
            os.unlink(path)
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_raises_filenotfounderror_when_file_missing(self) -> None:
        with self.assertRaises(FileNotFoundError):
            srv._local_path_to_data_url("/nonexistent/file.png")


class TestScanLevelForModels(_MockPopenMixin, unittest.TestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    def test_scan_hf_layout_finds_models(self) -> None:
        (self.tmpdir / "models--org--repo").mkdir()
        level = CacheLevel(name="test", root=str(self.tmpdir), layout="hf",
                           snapshot_for=lambda m: None)
        result: dict = {}
        srv._scan_level_for_models(level, result)
        self.assertIn("org/repo", result)

    def test_scan_ms_layout_finds_models(self) -> None:
        (self.tmpdir / "models" / "org" / "repo").mkdir(parents=True)
        level = CacheLevel(name="test", root=str(self.tmpdir), layout="ms",
                           snapshot_for=lambda m: None)
        result: dict = {}
        srv._scan_level_for_models(level, result)
        self.assertIn("org/repo", result)

    def test_scan_empty_dir_returns_empty_dict(self) -> None:
        level = CacheLevel(name="test", root=str(self.tmpdir), layout="hf",
                           snapshot_for=lambda m: None)
        result: dict = {}
        srv._scan_level_for_models(level, result)
        self.assertEqual(result, {})

    def test_scan_nonexistent_root_returns_empty_dict(self) -> None:
        level = CacheLevel(name="test", root="/nonexistent/path", layout="hf",
                           snapshot_for=lambda m: None)
        result: dict = {}
        srv._scan_level_for_models(level, result)
        self.assertEqual(result, {})

    def test_scan_dedup_keeps_first_level(self) -> None:
        (self.tmpdir / "models--org--repo").mkdir()
        level = CacheLevel(name="test", root=str(self.tmpdir), layout="hf",
                           snapshot_for=lambda m: None)
        result = {"org/repo": "other_level"}
        srv._scan_level_for_models(level, result)
        self.assertEqual(result["org/repo"], "other_level")
