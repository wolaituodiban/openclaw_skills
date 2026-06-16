"""Unit tests for the dashscope_image script's encoding + orchestration paths."""

import base64
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashscope.api_entities.dashscope_response import MultiModalConversationResponse

from scripts.dashscope_image import (
    _extract_urls,
    _image_value,
    _local_image_size,
    dashscope_image,
)


def _png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )


class ImageValueTest(unittest.TestCase):
    def test_local_path_encodes_as_data_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.png"
            p.write_bytes(_png_bytes())
            result = _image_value(str(p))
        self.assertEqual(
            result,
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        )

    def test_jpg_extension_maps_to_jpeg_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.jpg"
            p.write_bytes(b"\xff\xd8\xff")
            result = _image_value(str(p))
        self.assertEqual(result, "data:image/jpeg;base64,/9j/")

    def test_jpeg_extension_maps_to_jpeg_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.jpeg"
            p.write_bytes(b"\xff\xd8\xff")
            result = _image_value(str(p))
        self.assertEqual(result, "data:image/jpeg;base64,/9j/")

    def test_gif_extension_maps_to_gif_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.gif"
            p.write_bytes(b"fakebytes")
            result = _image_value(str(p))
        self.assertEqual(
            result,
            "data:image/gif;base64,ZmFrZWJ5dGVz",
        )

    def test_bmp_extension_maps_to_bmp_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.bmp"
            p.write_bytes(b"fakebytes")
            result = _image_value(str(p))
        self.assertEqual(
            result,
            "data:image/bmp;base64,ZmFrZWJ5dGVz",
        )

    def test_unknown_extension_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.xyz"
            p.write_bytes(b"whatever")
            with self.assertRaises(ValueError) as cm:
                _image_value(str(p))
        self.assertEqual(
            str(cm.exception),
            f"_image_value: '{p}' is not a recognised image path. "
            f"Pass a local file with a known image extension.",
        )

    def test_webp_extension_not_recognised(self) -> None:
        # webp is a real-world image format but the system mimetypes
        # table on this skill's host does not register it. If a future
        # environment starts to recognise it, the SKILL.md supported
        # extensions list must be updated to match.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.webp"
            p.write_bytes(b"fakebytes")
            with self.assertRaises(ValueError) as cm:
                _image_value(str(p))
        self.assertEqual(
            str(cm.exception),
            f"_image_value: '{p}' is not a recognised image path. "
            f"Pass a local file with a known image extension.",
        )

    def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.png"
            with self.assertRaises(FileNotFoundError) as cm:
                _image_value(str(missing))
        self.assertEqual(
            str(cm.exception),
            f"[Errno 2] No such file or directory: '{missing}'",
        )


def _png_with_dims(width: int, height: int) -> bytes:
    """Minimal valid PNG with the given pixel dimensions, single transparent pixel."""
    """Minimal valid PNG with the given pixel dimensions, single transparent pixel."""
    import zlib
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_chunk = b"IHDR" + ihdr
    raw = b"\x00\x00\x00\x00\x00"
    idat = zlib.compress(raw)
    def chunk(t: bytes, d: bytes) -> bytes:
        crc = zlib.crc32(t + d) & 0xFFFFFFFF
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", crc)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg_with_dims(width: int, height: int) -> bytes:
    """Minimal JPEG with the given pixel dimensions (SOF0 marker)."""
    return (
        b"\xff\xd8"
        + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0"
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x01\x01\x11\x00"
    )


class LocalImageSizeTest(unittest.TestCase):
    def test_png_reads_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.png"
            p.write_bytes(_png_with_dims(1024, 768))
            self.assertEqual(_local_image_size(str(p)), "1024*768")

    def test_jpeg_reads_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.jpg"
            p.write_bytes(_jpeg_with_dims(800, 600))
            self.assertEqual(_local_image_size(str(p)), "800*600")

    def test_unsupported_format_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "img.webp"
            p.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
            with self.assertRaisesRegex(ValueError, "not PNG or JPEG"):
                _local_image_size(str(p))


def _fake_response(urls: list) -> MultiModalConversationResponse:
    """Build a MultiModalConversationResponse-shape object from a list of image URLs.

    Uses Mock for the nested structure so tests do not depend on the SDK's
    internal dataclass field names (the SDK accepts arbitrary kwargs and
    stores them in __dict__, not in a typed schema).
    """
    r = mock.Mock()
    r.status_code = 200
    r.code = ""
    r.message = ""
    r.output.choices = [
        mock.Mock(message=mock.Mock(content=[{"image": u}])) for u in urls
    ]
    return r  # type: ignore[return-value]


class ExtractUrlsTest(unittest.TestCase):
    def test_extracts_image_strings_in_order(self) -> None:
        resp = _fake_response(["https://x/1.png", "https://x/2.png"])
        self.assertEqual(_extract_urls(resp), ["https://x/1.png", "https://x/2.png"])

    def test_empty_choices_returns_empty(self) -> None:
        resp = _fake_response([])
        self.assertEqual(_extract_urls(resp), [])

    def test_non_string_image_skipped(self) -> None:
        resp = mock.Mock()
        resp.status_code = 200
        resp.code = ""
        resp.message = ""
        resp.output.choices = [
            mock.Mock(message=mock.Mock(content=[
                {"image": 12345},
                {"image": "https://x/ok.png"},
            ]))
        ]
        self.assertEqual(_extract_urls(resp), ["https://x/ok.png"])  # type: ignore[arg-type]


class DashscopeImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.image = self.tmpdir / "in.png"
        self.image.write_bytes(_png_with_dims(1024, 768))
        self.outdir = self.tmpdir / "out"
        self._env_patch = mock.patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_calls_sdk_and_downloads_all_urls(self) -> None:
        fake = _fake_response(["https://x/1.png", "https://x/2.png"])
        with mock.patch(
            "scripts.dashscope_image.MultiModalConversation.call", return_value=fake
        ) as call, mock.patch(
            "scripts.dashscope_image.urllib.request.urlretrieve"
        ) as retrieve:
            dashscope_image(
                image=str(self.image),
                prompt="make it a dog",
                output_dir=str(self.outdir),
                model="qwen-image-edit-plus",
                size="2048*2048",
                n=2,
            )
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["model"], "qwen-image-edit-plus")
        self.assertEqual(kwargs["size"], "2048*2048")
        self.assertEqual(kwargs["n"], 2)
        self.assertEqual(kwargs["api_key"], "test-key")
        content = kwargs["messages"][0]["content"]
        self.assertTrue(content[0]["image"].startswith("data:image/png;base64,"))
        self.assertEqual(content[1]["text"], "make it a dog")
        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(
            [c.args[1] for c in retrieve.call_args_list],
            [self.outdir / "1.png", self.outdir / "2.png"],
        )

    def test_size_inferred_from_input_when_omitted(self) -> None:
        fake = _fake_response(["https://x/1.png"])
        with mock.patch(
            "scripts.dashscope_image.MultiModalConversation.call", return_value=fake
        ) as call, mock.patch("scripts.dashscope_image.urllib.request.urlretrieve"):
            dashscope_image(
                image=str(self.image),
                prompt="x",
                output_dir=str(self.outdir),
                model="qwen-image-edit-plus",
                size=None,
                n=1,
            )
        self.assertEqual(call.call_args.kwargs["size"], "1024*768")

    def test_creates_output_dir(self) -> None:
        fake = _fake_response(["https://x/1.png"])
        with mock.patch("scripts.dashscope_image.MultiModalConversation.call", return_value=fake), \
             mock.patch("scripts.dashscope_image.urllib.request.urlretrieve"):
            self.assertFalse(self.outdir.exists())
            dashscope_image(
                image=str(self.image),
                prompt="x",
                output_dir=str(self.outdir),
                model="qwen-image-edit-plus",
                size=None,
                n=1,
            )
        self.assertTrue(self.outdir.exists())

    def test_nonzero_status_raises(self) -> None:
        fake = mock.Mock()
        fake.status_code = 401
        fake.code = "InvalidApiKey"
        fake.message = "bad key"
        fake.output.choices = []
        with mock.patch("scripts.dashscope_image.MultiModalConversation.call", return_value=fake), \
             mock.patch("scripts.dashscope_image.urllib.request.urlretrieve") as retrieve:
            with self.assertRaisesRegex(RuntimeError, "dashscope_image.*401.*InvalidApiKey") as cm:
                dashscope_image(
                    image=str(self.image),
                    prompt="x",
                    output_dir=str(self.outdir),
                    model="qwen-image-edit-plus",
                    size=None,
                    n=1,
                )
        self.assertIn("DASHSCOPE_API_KEY", str(cm.exception))
        retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
