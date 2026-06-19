---
name: dashscope-image
description: "Edit or generate images via the dashscope SDK and save them locally."
---

# dashscope-image

Edit or generate images via the dashscope SDK and save them locally.

## When to reach for this skill

- The user has a local image and a prompt and wants
  the model to edit it.
- The user wants to generate an image from a prompt with a dashscope
  image model.
- The user has `DASHSCOPE_API_KEY` set in the environment and wants
  the images saved to disk without writing any extra glue code.

## When NOT to reach for this skill

- The user wants a non-dashscope image model (OpenAI `gpt-image-1`,
  Google Imagen, etc.). Wire format and SDK are different.
- The user wants text-only generation or embeddings.
- The user wants to inspect the raw JSON response. This script does
  not print response bodies — it only downloads images.
- The user wants retries on transient failures, streaming, or partial
  success. The script calls the API once, downloads every returned
  image, and propagates any error as an exception.

## Setup

Set the API key in `~/.openclaw/.env` (the OpenClaw global dotenv
file, recommended for provider credentials). Replace `<your-key>`
with the real key from the dashscope console:

```bash
grep -q '^DASHSCOPE_API_KEY=' ~/.openclaw/.env \
  || echo 'DASHSCOPE_API_KEY=<your-key>' >> ~/.openclaw/.env
chmod 600 ~/.openclaw/.env
```

The dashscope SDK reads `DASHSCOPE_API_KEY` from the process
environment directly. OpenClaw loads `~/.openclaw/.env` into the
gateway process environment, so any script the agent runs inherits
the key. If the key is missing the SDK raises its own error.

## Inputs

The script takes two required CLI arguments and four optional ones:

| Argument | Required? | What it is |
|---|---|---|
| `--image <path>` | yes | Local image file (jpg/jpeg/png/gif/bmp). Encoded as a `data:image/...;base64,...` URL and sent to the model as the edit/generation seed. |
| `--prompt <text>` | yes | Text instruction for the model. |
| `--output-dir <path>` | no | Directory to save the generated images. Created if missing. Files are named `<index>_<timestamp>.png` (e.g. `1_20260619-202500.png`) in the order dashscope returns them. Default: `~/.openclaw/media/tool-image-generation` (tilde is expanded to the user's home directory). |
| `--model <id>` | no | dashscope model id. Default: `qwen-image-edit-plus`. |
| `--size <w*h>` | no | Image size in `<width>*<height>` form. Default: `1024*1024`. |
| `--n <1-4>` | no | Number of images to generate. Default: `1`. |

## Output

One PNG file per generated image, written to `--output-dir` as
`<index>_<timestamp>.png` (e.g. `1_20260619-202500.png`) in the
order dashscope returns them. `<timestamp>` is local wall-clock
time formatted as `YYYYMMDD-HHMMSS`; all images from a single
call share the same timestamp.

Stdout on success has three sections so both humans and agents
can pick out the saved file paths at a glance:

```
dashscope-image: saving <N> image(s) to <output_dir>
<output_dir>/1_<timestamp>.png
<output_dir>/2_<timestamp>.png
...
dashscope-image: done
```

The file paths are the only lines that look like real filesystem
paths — humans and agents can grep `^/` (or any anchored prefix)
to extract them. Any error traceback goes to stderr and the
process exits non-zero; the footer line is only printed on the
success path.

## Workflow

1. Parse CLI arguments. `--image` / `--prompt` are required;
   `--output-dir` defaults to `~/.openclaw/media/tool-image-generation`
   (tilde is expanded to the user's home directory via `os.path.expanduser`);
   `--model` / `--size` / `--n` fall back to the script defaults.
2. Resolve `--image` to a model-ready value: local path →
   `data:image/...;base64,...`. URL inputs are not supported —
   download the image first and pass the local path.
3. Call `dashscope.MultiModalConversation.call(model=..., messages=...,
   n=..., size=...)`. The SDK reads the API key from
   `DASHSCOPE_API_KEY`.
4. If the response status is not 200, raise `RuntimeError` with the
   dashscope `code` and `message`.
5. Extract every `output.choices[*].message.content[*].image` URL
   and download each one into `--output-dir` as
   `<index>_<timestamp>.png` (e.g. `1_20260619-202500.png`). Print
   each saved path to stdout.

## Code structure

Single file: `scripts/dashscope_image.py`. Four small functions
plus `main`:

| Function | Job |
|---|---|
| `_image_value(path)` | local path → `data:image/...;base64,...` string |
| `_local_image_size(path)` | local png/jpeg → `"<width>*<height>"` |
| `_extract_urls(response)` | SDK response object → list of URL strings |
| `dashscope_image(image, prompt, output_dir, model, size, n)` | orchestration: build messages → call SDK → download all URLs → print saved paths → return list[Path] |
| `main()` | argparse → one call to `dashscope_image(...)` → `raise SystemExit(0)` |

No `try`/`except`. Errors from the SDK, file IO, and `urlretrieve`
all propagate. The unhandled-exception handler prints the traceback;
the process exits non-zero.

## Example invocation

```bash
# Edit a local image with the default model
python3 scripts/dashscope_image.py \
    --image path/to/cat.jpg \
    --prompt "Turn this cat into a dog" \
    --output-dir ./out

# Same edit, non-default model and size
python3 scripts/dashscope_image.py \
    --image path/to/cat.jpg \
    --prompt "A calico cat sleeping on a windowsill" \
    --output-dir ./out \
    --model qwen-image-2.0-pro \
    --size 1536*1024 \
    --n 2
```

## Tests

Unit tests (`tests/unit/test_dashscope_image.py`) cover every
function with exact-value assertions. They mock the dashscope SDK
and `urlretrieve` so no network access is needed.

Integration tests live in `tests/integration/`:

- `test_cli_smoke.py` — drives the script as a subprocess and
  asserts on `--help` output and exit codes. No API call.
- `test_cli_end_to_end.py` — runs a real image-edit round trip
  against the live API and asserts a PNG is written. Env-gated:
  skipped unless `RUN_INTEGRATION_TESTS=1`.

```bash
# Unit + smoke (default, fast)
PYTHONPATH=. python3 -m unittest discover -s tests

# Everything (real API call; needs DASHSCOPE_API_KEY)
RUN_INTEGRATION_TESTS=1 PYTHONPATH=. python3 -m unittest discover -s tests
```

## Caveats

- The script does not retry on 429 / 5xx. Wrap the call in your own
  retry loop if you need it.
- `--image` is a seed, not a "must include" constraint. For
  generation-only models the image biases the output; it is not
  literally embedded.
- The script does not read a config file. Pass the API key via
  `DASHSCOPE_API_KEY` in `~/.openclaw/.env` (or the process
  environment). Missing key → dashscope SDK raises.
