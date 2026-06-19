"""Call dashscope multimodal generation and download the generated images.

The dashscope API key is read by the dashscope SDK from the DASHSCOPE_API_KEY
environment variable. Set it in ~/.openclaw/.env (see SKILL.md, "Setup").

Usage examples:

    # 1 image: image edit / style transfer
    python3 dashscope_image.py input.jpg \\
        --prompt "Turn this cat into a dog" \\
        --output-dir /path/to/out

    # 2+ images: multi-reference edit; output size is the per-axis
    # average of input sizes, rounded down to a multiple of 8
    python3 dashscope_image.py a.jpg b.png \\
        --prompt "Combine these into one scene" \\
        --output-dir /path/to/out

    # 0 images: text-to-image (requires a model that supports it,
    # e.g. qwen-image; pass --model explicitly; --size required)
    python3 dashscope_image.py \\
        --prompt "A cat wearing a hat" \\
        --size 1024*1024 \\
        --output-dir /path/to/out
"""

import argparse
import base64
import datetime as _dt
import mimetypes
import os
import struct
import urllib.request
from pathlib import Path
from typing import NoReturn

from dashscope import MultiModalConversation
from dashscope.api_entities.dashscope_response import MultiModalConversationResponse
from typeguard import typechecked

DEFAULT_MODEL = "qwen-image-edit-plus"
DEFAULT_N = 1
DEFAULT_OUTPUT_DIR = "~/.openclaw/media/tool-image-generation"
FILENAME_TIMESTAMP_FMT = "%Y%m%d-%H%M%S"


# --- input / compute boundaries ---


@typechecked
def _image_value(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime is None or not mime.startswith("image/"):
        raise ValueError(
            f"_image_value: {path!r} is not a recognised image path. "
            f"Pass a local file with a known image extension."
        )
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


@typechecked
def _local_image_size(path: str) -> str:
    """Read width/height from a local PNG or JPEG file. Returns 'WIDTH*HEIGHT'.

    No third-party dependencies: parses the PNG IHDR chunk or the first JPEG
    SOFn marker. Raises ValueError for any other format.
    """
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return f"{width}*{height}"
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                raise ValueError(f"_local_image_size: malformed JPEG: {path!r}")
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                segment_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return f"{width}*{height}"
            segment_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + segment_len
        raise ValueError(f"_local_image_size: no SOF marker in JPEG: {path!r}")
    raise ValueError(
        f"_local_image_size: {path!r} is not PNG or JPEG; pass --size explicitly."
    )


@typechecked
def _extract_urls(response: MultiModalConversationResponse) -> list:
    urls: list = []
    choices = response.output.choices or []
    for choice in choices:
        for item in choice.message.content or []:
            if isinstance(item, dict) and isinstance(item.get("image"), str):
                urls.append(item["image"])
    return urls


# --- orchestration ---


@typechecked
def _inferred_size(images: list[str]) -> str:
    """Per-axis average of input image dimensions, floored to a multiple of 8.

    Renders as '<W>*<H>'. Raises ValueError when the image list is empty
    (caller must pass --size explicitly for text-to-image).
    """
    if not images:
        raise ValueError(
            "_inferred_size: cannot infer size from zero input images. "
            "Pass --size explicitly (e.g. --size 1024*1024)."
        )
    widths: list[int] = []
    heights: list[int] = []
    for p in images:
        w, h = _local_image_size(p).split("*")
        widths.append(int(w))
        heights.append(int(h))
    avg_w = (sum(widths) // len(widths)) // 8 * 8
    avg_h = (sum(heights) // len(heights)) // 8 * 8
    if avg_w <= 0 or avg_h <= 0:
        raise ValueError(
            f"_inferred_size: computed non-positive size {avg_w}*{avg_h} "
            f"from inputs {images}. Pass --size explicitly."
        )
    return f"{avg_w}*{avg_h}"


@typechecked
def dashscope_image(
    images: list[str],
    prompt: str,
    output_dir: str,
    model: str,
    size: str | None,
    n: int,
) -> list[Path]:
    effective_size = size if size is not None else _inferred_size(images)
    content: list[dict] = [{"image": _image_value(p)} for p in images]
    content.append({"text": prompt})
    response = MultiModalConversation.call(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        model=model,
        messages=[{"role": "user", "content": content}],
        n=n,
        size=effective_size,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"dashscope_image: dashscope returned status={response.status_code} "
            f"code={response.code} message={response.message}. "
            f"Check DASHSCOPE_API_KEY / --model / --size / --n."
        )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = _dt.datetime.now().strftime(FILENAME_TIMESTAMP_FMT)
    saved: list[Path] = []
    print(
        f"dashscope-image: saving {n} image(s) to {out}",
        flush=True,
    )
    for index, url in enumerate(_extract_urls(response), start=1):
        dest = out / f"{index}_{timestamp}.png"
        urllib.request.urlretrieve(url, dest)
        saved.append(dest)
        print(dest, flush=True)
    print("dashscope-image: done", flush=True)
    return saved


# --- entry ---


def main() -> NoReturn:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="*",
        help="Zero or more local image paths (jpg/jpeg/png/gif/bmp). "
             "Encoded as data URLs and sent to the model. Omit for text-to-image "
             "(requires a model that supports it, e.g. qwen-image).",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Text instruction for the model.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write generated images to (created if missing). "
             f"Files are named '<index>_<timestamp>.png' (e.g. '1_20260619-202500.png'). "
             f"Default: {DEFAULT_OUTPUT_DIR} (tilde is expanded to the user's home directory).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"dashscope model id (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--size",
        default=None,
        help="image size in '<width>*<height>' form. If omitted: "
             "with one image, read from the image (PNG/JPEG only); "
             "with multiple images, per-axis average of input sizes, "
             "floored to a multiple of 8; "
             "with zero images, this argument is required.",
    )
    parser.add_argument(
        "--n",
        type=int,
        choices=[1, 2, 3, 4],
        default=DEFAULT_N,
        help=f"number of images to generate (default: {DEFAULT_N}).",
    )
    args = parser.parse_args()
    dashscope_image(
        images=args.images,
        prompt=args.prompt,
        output_dir=os.path.expanduser(args.output_dir),
        model=args.model,
        size=args.size,
        n=args.n,
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
