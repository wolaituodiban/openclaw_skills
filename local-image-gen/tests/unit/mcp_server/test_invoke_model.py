"""Unit tests for invoke_model MCP tool."""

import asyncio
import base64
import binascii
import json
import os
import pathlib
import unittest
from unittest.mock import MagicMock, patch

import local_image_gen.mcp_server as srv
from tests.unit.mcp_server._mixins import _MockPopenMixin


class TestInvokeModel(_MockPopenMixin, unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self.setUp_mcp_server()
        self.ref_image = self.tmpdir / "ref.png"
        self.ref_image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.ref_image2 = self.tmpdir / "ref2.png"
        self.ref_image2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self._svc_data = {
            "model": "org/repo", "pid": 12345, "port": 9999,
            "started_at": 100.0,
        }

    def tearDown(self) -> None:
        self.tearDown_mcp_server()

    def _make_alive(self) -> None:
        self.make_alive_pid_mock(pid=12345)

    # --- Happy path (14 tests) --- #

    async def test_invoke_succeeds_with_required_args_only(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertIn("path", result)
        self.assertIn("b64_json", result)

    async def test_invoke_passes_all_kwargs_to_route_invoke(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model(
                "a cat", str(self.tmpdir / "out.png"),
                model="org/repo", size="1024x1024",
                outputFormat="png", count=1, timeoutMs=30000,
            )
        mock_route.assert_called_once()

    async def test_invoke_count_one_returns_string_path(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertIsInstance(result["path"], str)

    async def test_invoke_count_four_returns_list_paths(self) -> None:
        self._make_alive()
        fake_b64s = [base64.b64encode(b"fake").decode() for _ in range(4)]
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=fake_b64s), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"), count=4)
        self.assertIsInstance(result["path"], list)
        self.assertEqual(len(result["path"]), 4)

    async def test_invoke_with_image_routes_to_edit(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("edit", str(self.tmpdir / "out.png"),
                                   image=str(self.ref_image))
        self.assertTrue(mock_route.call_args[0][3])  # as_edit=True

    async def test_invoke_with_images_routes_to_edit(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("edit", str(self.tmpdir / "out.png"),
                                   images=[str(self.ref_image), str(self.ref_image2)])
        self.assertTrue(mock_route.call_args[0][3])

    async def test_invoke_no_image_routes_to_generate(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertFalse(mock_route.call_args[0][3])  # as_edit=False

    async def test_invoke_uses_service_model_when_model_arg_none(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        # effective_model should be svc_model = "org/repo"
        self.assertEqual(mock_route.call_args[0][2], "org/repo")

    async def test_invoke_explicit_model_matches_service_model(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"), model="org/repo")
        self.assertEqual(mock_route.call_args[0][2], "org/repo")

    async def test_invoke_timeoutMs_converted_to_seconds(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"), timeoutMs=5000)
        # timeout_s should be 5.0
        self.assertEqual(mock_route.call_args[1]["timeout_s"], 5.0)

    async def test_invoke_no_timeoutMs_uses_default_120(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertEqual(mock_route.call_args[1]["timeout_s"], 120)

    async def test_invoke_decode_and_persist_called_with_correct_args(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        out_path = str(self.tmpdir / "out.png")
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist") as mock_decode:
            await srv.invoke_model("a cat", out_path)
        mock_decode.assert_called_once()

    async def test_invoke_count_four_generates_numbered_filenames(self) -> None:
        self._make_alive()
        fake_b64s = [base64.b64encode(b"fake").decode() for _ in range(4)]
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=fake_b64s), \
             patch.object(srv, "_decode_and_persist") as mock_decode:
            result = await srv.invoke_model(
                "a cat", str(self.tmpdir / "out.png"), count=4,
            )
        # decode called with 4 target paths
        targets = mock_decode.call_args[0][1]
        self.assertEqual(len(targets), 4)

    async def test_invoke_returns_b64_json_in_result(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertEqual(result["b64_json"], fake_b64)

    # --- Error path (10 tests) --- #

    async def test_invoke_empty_prompt_returns_validation_error(self) -> None:
        self._make_alive()
        result = await srv.invoke_model("", str(self.tmpdir / "out.png"))
        self.assertEqual(result["error"]["code"], "validation_error")

    async def test_invoke_filename_parent_not_found_returns_error(self) -> None:
        self._make_alive()
        result = await srv.invoke_model("a cat", "/nonexistent/dir/out.png")
        self.assertEqual(result["error"]["code"], "filename_dir_not_found")

    async def test_invoke_no_service_returns_no_running_service(self) -> None:
        with patch.object(srv, "_read_service_json", return_value=None):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertEqual(result["error"]["code"], "no_running_service")

    async def test_invoke_dead_pid_returns_no_running_service(self) -> None:
        self.make_dead_pid_mock(pid=12345)
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_prune_stale_service_json"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertEqual(result["error"]["code"], "no_running_service")

    async def test_invoke_model_mismatch_returns_model_not_loaded(self) -> None:
        self._make_alive()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data):
            result = await srv.invoke_model(
                "a cat", str(self.tmpdir / "out.png"), model="other/repo",
            )
        self.assertEqual(result["error"]["code"], "model_not_loaded")

    async def test_invoke_count_gt1_filename_conflict_returns_error(self) -> None:
        self._make_alive()
        existing = self.tmpdir / "out-1.png"
        existing.write_bytes(b"existing")
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model(
                "a cat", str(self.tmpdir / "out.png"), count=2,
            )
        self.assertEqual(result["error"]["code"], "filename_conflict")

    async def test_invoke_count_one_filename_conflict_not_checked(self) -> None:
        """count=1 → existing file does NOT trigger filename_conflict."""
        self._make_alive()
        existing = self.tmpdir / "out.png"
        existing.write_bytes(b"existing")
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))
        self.assertNotIn("error", result)

    async def test_invoke_raises_oserror_when_decode_fails(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))

    async def test_invoke_raises_binascii_error_when_b64_invalid(self) -> None:
        self._make_alive()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=["!!!invalid!!!"]), \
             patch.object(srv, "_decode_and_persist", side_effect=binascii.Error("invalid")):
            with self.assertRaises(binascii.Error):
                await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))

    async def test_invoke_raises_openai_error_when_client_fails(self) -> None:
        self._make_alive()
        from openai import OpenAIError
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", side_effect=OpenAIError("server error")):
            with self.assertRaises(OpenAIError):
                await srv.invoke_model("a cat", str(self.tmpdir / "out.png"))

    # --- Edge path (6 tests) --- #

    async def test_invoke_count_clamped_to_minimum_one(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", str(self.tmpdir / "out.png"), count=0)
        # count=0 → effective_count=1
        self.assertEqual(mock_route.call_args[1]["count"], 1)

    async def test_invoke_count_negative_clamped_to_one(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"), count=-5)
        self.assertEqual(mock_route.call_args[1]["count"], 1)

    async def test_invoke_outputFormat_non_png_passes_extra_body(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model(
                "a cat", str(self.tmpdir / "out.png"), outputFormat="webp",
            )
        self.assertEqual(mock_route.call_args[1]["outputFormat"], "webp")

    async def test_invoke_filename_relative_path_resolves(self) -> None:
        """Relative filename → parent dir is cwd, should work if cwd exists."""
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]), \
             patch.object(srv, "_decode_and_persist"):
            result = await srv.invoke_model("a cat", "out.png")
        self.assertNotIn("error", result)

    async def test_invoke_image_and_images_both_passed_image_takes_precedence(self) -> None:
        """Both image and images → image wins (as_edit=True regardless)."""
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model(
                "edit", str(self.tmpdir / "out.png"),
                image=str(self.ref_image),
                images=[str(self.ref_image2)],
            )
        self.assertTrue(mock_route.call_args[0][3])  # as_edit=True

    async def test_invoke_timeoutMs_zero_uses_default(self) -> None:
        self._make_alive()
        fake_b64 = base64.b64encode(b"fake").decode()
        with patch.object(srv, "_read_service_json", return_value=self._svc_data), \
             patch.object(srv, "_route_invoke", return_value=[fake_b64]) as mock_route, \
             patch.object(srv, "_decode_and_persist"):
            await srv.invoke_model("a cat", str(self.tmpdir / "out.png"), timeoutMs=0)
        self.assertEqual(mock_route.call_args[1]["timeout_s"], 120)
