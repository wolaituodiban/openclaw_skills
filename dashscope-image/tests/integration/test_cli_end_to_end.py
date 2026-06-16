"""End-to-end CLI test (env-gated). Calls dashscope, asserts an image is saved.

Skipped unless RUN_INTEGRATION_TESTS=1.
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dashscope_image.py"


def _make_png_1024() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1024, 1024, 8, 6, 0, 0, 0)

    def _chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b"\x00" + (b"\x00\x00\x00\x00" * 1024)
    idat = zlib.compress(raw, 9)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _run(image: Path, outdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--image", str(image),
            "--prompt", "make it blue",
            "--output-dir", str(outdir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(SCRIPT.parent.parent)},
    )


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION_TESTS") == "1",
    "set RUN_INTEGRATION_TESTS=1 to run integration tests",
)
class CliEndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.image = self.tmp / "in.png"
        self.image.write_bytes(_make_png_1024())
        self.outdir = self.tmp / "out"
        self.outdir.mkdir()

    def test_generates_image_and_saves_to_output_dir(self) -> None:
        result = _run(self.image, self.outdir)
        self.assertEqual(result.returncode, 0)
        out_file = self.outdir / "1.png"
        self.assertTrue(out_file.exists(), f"expected {out_file} to exist")
        # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
        self.assertEqual(out_file.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
