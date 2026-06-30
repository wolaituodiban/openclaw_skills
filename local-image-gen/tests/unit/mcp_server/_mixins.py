"""Shared test scaffolding for mcp_server unit tests.

Provides _MockPopenMixin — a setUp helper that builds a mock Popen object
configured with per-test pid, exit code, poll/wait/terminate behavior.
"""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import local_image_gen.mcp_server as srv


class _MockPopenMixin:
    """Mixin for test classes that need to mock subprocess.Popen."""

    def setUp_mcp_server(self) -> None:
        """Create a temp state dir and set up common patches."""
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = pathlib.Path(self._tmpdir_ctx.name)
        self.service_json_path = self.tmpdir / srv.SERVICE_FILE_NAME

        # Patch state dir to use tmpdir
        self._patches = [
            patch.object(srv, "_STATE_DIR", self.tmpdir),
            patch.object(srv, "_validate_state_dir", return_value=self.tmpdir),
        ]

        # Create a mock Popen
        self.mock_proc = MagicMock()
        self.mock_proc.pid = 12345
        self.mock_proc.poll.return_value = None  # still running
        self.mock_proc.wait.return_value = 0
        self.mock_proc.terminate.return_value = None
        self.mock_proc.kill.return_value = None

        # Start all patches
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown_mcp_server(self) -> None:
        """Clean up temp dir."""
        self._tmpdir_ctx.cleanup()

    def write_service_json(self, record: dict) -> None:
        """Write a service.json file in tmpdir."""
        self.service_json_path.write_text(json.dumps(record), encoding="utf-8")

    def remove_service_json(self) -> None:
        """Remove service.json if it exists."""
        if self.service_json_path.exists():
            self.service_json_path.unlink()

    def make_alive_pid_mock(self, pid: int = 12345) -> None:
        """Patch os.kill so the given pid appears alive."""
        self._os_kill_patch = patch("local_image_gen.mcp_server.os.kill")
        mock_kill = self._os_kill_patch.start()
        mock_kill.return_value = None  # no exception = alive
        self.addCleanup(self._os_kill_patch.stop)

    def make_dead_pid_mock(self, pid: int = 12345) -> None:
        """Patch os.kill so the given pid raises ProcessLookupError."""
        self._os_kill_patch = patch("local_image_gen.mcp_server.os.kill")
        mock_kill = self._os_kill_patch.start()
        mock_kill.side_effect = ProcessLookupError(f"No process {pid}")
        self.addCleanup(self._os_kill_patch.stop)

    def create_hf_snapshot_dir(self, org: str, repo: str) -> pathlib.Path:
        """Create a HF-layout snapshot dir models--org--repo under tmpdir."""
        d = self.tmpdir / f"models--{org}--{repo}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_ms_snapshot_dir(self, org: str, repo: str) -> pathlib.Path:
        """Create a MS-layout snapshot dir models/org/repo under tmpdir."""
        d = self.tmpdir / "models" / org / repo
        d.mkdir(parents=True, exist_ok=True)
        return d
