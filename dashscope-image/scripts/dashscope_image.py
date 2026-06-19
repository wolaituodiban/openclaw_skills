"""Call dashscope multimodal generation and download the generated images.

The dashscope API key is read by the dashscope SDK from the DASHSCOPE_API_KEY
environment variable. Set it in ~/.openclaw/.env (see SKILL.md, "Setup").

Usage example:
    python3 dashscope_image.py \\
        --image input.jpg \\
        --prompt "Turn this cat into a dog" \\
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
def dashscope_image(
    image: str,
    prompt: str,
    output_dir: str,
    model: str,
    size: str | None,
    n: int,
) -> list[Path]:
    effective_size = size if size is not None else _local_image_size(image)
    response = MultiModalConversation.call(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"image": _image_value(image)},
                {"text": prompt},
            ],
        }],
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
        "--image",
        required=True,
        help="Local image path (PNG or JPEG) to send to the model as the seed.",
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
             f"Files are named 1.png, 2.png, ... "
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
        help="image size in '<width>*<height>' form. If omitted, read from the input image (PNG/JPEG only).",
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
        image=args.image,
        prompt=args.prompt,
        output_dir=os.path.expanduser(args.output_dir),
        model=args.model,
        size=args.size,
        n=args.n,
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
