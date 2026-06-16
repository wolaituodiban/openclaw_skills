"""Smoke tests for the dashscope_image CLI (env-gated).

Skipped unless RUN_INTEGRATION_TESTS=1. Verifies the script's argument
parser and that it exits non-zero on bad input. Does not contact the
dashscope API.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dashscope_image.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(SCRIPT.parent.parent)},
    )


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION_TESTS") == "1",
    "set RUN_INTEGRATION_TESTS=1 to run integration tests",
)
class HelpTest(unittest.TestCase):
    def test_help_exits_zero_and_lists_args(self) -> None:
        result = _run("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--image", "--prompt", "--output-dir", "--model", "--size", "--n"):
            self.assertIn(flag, result.stdout)
        self.assertNotIn("--config", result.stdout)


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION_TESTS") == "1",
    "set RUN_INTEGRATION_TESTS=1 to run integration tests",
)
class MissingArgsTest(unittest.TestCase):
    def test_missing_required_args_exits_nonzero(self) -> None:
        result = _run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage", result.stderr.lower())

    def test_missing_one_required_arg_exits_nonzero(self) -> None:
        result = _run("--prompt", "x")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
