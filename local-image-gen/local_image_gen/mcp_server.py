"""local_image_gen.mcp_server — MCP tool surface for local image generation.

Exposes 5 MCP tools (list_local_models, start_service, list_running_services,
invoke_model, release_service) over stdio JSON-RPC via FastMCP.

Design contract: see dev-doc/mcp_server/03-design.md v2.
"""

import asyncio
import base64
import binascii
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

import httpx
from typeguard import typechecked

import local_image_gen.cache_resolver as cr
from local_image_gen.cache_resolver import CacheLevel

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_START_TIMEOUT_S: int = 120
DEFAULT_INVOKE_TIMEOUT_S: int = 120
RELEASE_GRACE_S: int = 10
SHUTDOWN_GRACE_S: int = 30
READY_POLL_INTERVAL_S: float = 1.0
SERVICE_FILE_NAME: str = "service.json"
DEFAULT_STATE_DIR: str = "~/.local-image-gen/state/"

# Status enum values written to service.json["status"].
STATUS_LOADING: str = "loading"
STATUS_READY: str = "ready"
STATUS_FAILED: str = "failed"


# ---------------------------------------------------------------------------
# State directory (resolved once at import time)
# ---------------------------------------------------------------------------

_STATE_DIR: pathlib.Path = pathlib.Path(
    os.environ.get("LOCAL_IMAGE_GEN_STATE_DIR", DEFAULT_STATE_DIR)
).expanduser().resolve()


@typechecked
def _validate_state_dir() -> pathlib.Path:
    """Resolve and create the state directory. Returns absolute Path.

    Lets OSError propagate (§5).
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _STATE_DIR


_validate_state_dir()  # initialise at import time


# ---------------------------------------------------------------------------
# Background poll thread registry
# ---------------------------------------------------------------------------
# Maps pid → daemon poll Thread. Populated by start_service, cleared by
# release_service. Threads are daemons and self-exit when service.json is
# removed; this registry is for cleanup accounting, not thread lifecycle.

_poll_threads: dict[int, threading.Thread] = {}


# ---------------------------------------------------------------------------
# Process / IO helpers
# ---------------------------------------------------------------------------


@typechecked
def _pick_free_port(host: str = "127.0.0.1") -> int:
    """Open a TCP socket on `host` with port 0, read the assigned port, close."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


@typechecked
def _spawn_vllm_omni(args: list[str]) -> subprocess.Popen:
    """Launch vllm-omni subprocess. stdout→stderr, new session group."""
    return subprocess.Popen(
        args,
        stdout=sys.stderr,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


@typechecked
def _release_subprocess(pid: int) -> None:
    """Terminate (SIGTERM) the subprocess; kill (SIGKILL) after grace.

    Uses psutil when available; falls back to os.kill. Single boundary catch
    for TimeoutExpired→kill conversion (§5).
    """
    if psutil is not None:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=RELEASE_GRACE_S)
        except psutil.TimeoutExpired:
            proc.kill()
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(RELEASE_GRACE_S)
            os.kill(pid, 0)  # probe alive
        except ProcessLookupError:
            return  # already dead — nothing to do
        os.kill(pid, signal.SIGKILL)


# ---------------------------------------------------------------------------
# service.json I/O
# ---------------------------------------------------------------------------


@typechecked
def _read_service_json() -> Optional[dict]:
    """Read service.json; return parsed dict or None if file absent.

    Lets OSError / PermissionError / json.JSONDecodeError propagate (§5).
    """
    path = _STATE_DIR / SERVICE_FILE_NAME
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@typechecked
def _write_service_json(contents: dict) -> None:
    """Write service.json atomically via tempfile + os.replace.

    Lets OSError propagate (§5).
    """
    target = _STATE_DIR / SERVICE_FILE_NAME
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(_STATE_DIR),
        delete=False,
        suffix=".json",
        encoding="utf-8",
    ) as f:
        json.dump(contents, f)
        f.flush()
        tmp_name = f.name
    os.replace(tmp_name, target)


@typechecked
def _prune_stale_service_json() -> None:
    """If service.json's PID is dead, remove the file. No-op if file absent.

    Lets OSError on os.remove propagate (§5).
    """
    data = _read_service_json()
    if data is None:
        return
    pid = data.get("pid", -1)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        os.remove(_STATE_DIR / SERVICE_FILE_NAME)


# ---------------------------------------------------------------------------
# Readiness polling
# ---------------------------------------------------------------------------


@typechecked
def _probe_v1_models(port: int) -> bool:
    """Single-shot HTTP probe of GET /v1/models. True on 200, False otherwise.

    Boundary helper (§5): catches Exception to convert transient errors
    into a "not ready" typed return.
    """
    url = f"http://127.0.0.1:{port}/v1/models"
    try:
        resp = httpx.get(url, timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@typechecked
def _poll_ready(port: int, deadline_s: float) -> bool:
    """Poll /v1/models every READY_POLL_INTERVAL_S until 200 or deadline."""
    while time.monotonic() < deadline_s:
        if _probe_v1_models(port):
            return True
        time.sleep(READY_POLL_INTERVAL_S)
    return False


@typechecked
def _background_poll_ready(port: int, pid: int, timeout_s: float) -> None:
    """Daemon-thread target: poll ready, then update service.json status.

    On ready: set status=ready.
    On timeout: set status=failed, kill subprocess, remove service.json.
    On unexpected error: set status=failed, leave subprocess for post-mortem.
    """
    deadline = time.monotonic() + timeout_s
    ready = _poll_ready(port, deadline)
    try:
        svc = _read_service_json()
        if svc is None or svc.get("pid") != pid:
            return  # service.json was already cleaned up by release_service
        if ready:
            svc["status"] = STATUS_READY
        else:
            svc["status"] = STATUS_FAILED
        _write_service_json(svc)
        if not ready:
            # Best-effort cleanup; ignore errors (proc may already be gone)
            _release_subprocess(pid)
            try:
                os.remove(_STATE_DIR / SERVICE_FILE_NAME)
            except OSError:
                pass
    finally:
        _poll_threads.pop(pid, None)


# ---------------------------------------------------------------------------
# HTTP invoke helpers
# ---------------------------------------------------------------------------


@typechecked
def _local_path_to_data_url(path: str) -> str:
    """Convert a local file path to a data:image/<ext>;base64,... URL."""
    p = pathlib.Path(path)
    ext = p.suffix.lstrip(".").lower() or "png"
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }
    mime = mime_map.get(ext, "image/png")
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


@typechecked
def _route_invoke(
    client: object,
    prompt: str,
    model: str,
    as_edit: bool,
    image: Optional[str],
    images: Optional[list[str]],
    size: Optional[str],
    outputFormat: str,
    count: int,
    negative_prompt: Optional[str],
    num_inference_steps: Optional[int],
    guidance_scale: Optional[float],
    true_cfg_scale: Optional[float],
    seed: Optional[int],
    timeout_s: float,
) -> list[str]:
    """Route to client.images.generate or client.images.edit.

    Returns list of b64_json strings of length count.
    Lets openai.OpenAIError and OSError propagate (§5).
    """
    from openai import OpenAI

    openai_client: OpenAI = client  # type: ignore[assignment]
    effective_count = max(count, 1)

    extra_body: dict = {}
    if outputFormat != "png":
        extra_body["output_format"] = outputFormat
    if negative_prompt is not None:
        extra_body["negative_prompt"] = negative_prompt
    if num_inference_steps is not None:
        extra_body["num_inference_steps"] = num_inference_steps
    if guidance_scale is not None:
        extra_body["guidance_scale"] = guidance_scale
    if true_cfg_scale is not None:
        extra_body["true_cfg_scale"] = true_cfg_scale
    if seed is not None:
        extra_body["seed"] = seed

    kwargs: dict = {
        "prompt": prompt,
        "model": model,
        "n": effective_count,
        "response_format": "b64_json",
        "timeout": timeout_s,
    }
    if size is not None:
        kwargs["size"] = size
    if extra_body:
        kwargs["extra_body"] = extra_body

    if as_edit:
        edit_kwargs = dict(kwargs)
        if image is not None:
            edit_kwargs["image"] = _local_path_to_data_url(image)
        if images is not None and len(images) > 0:
            edit_kwargs["image"] = _local_path_to_data_url(images[0])
            if len(images) > 1:
                edit_kwargs.setdefault("extra_body", {})
                edit_kwargs["extra_body"]["image[]"] = [
                    _local_path_to_data_url(p) for p in images
                ]
        response = openai_client.images.edit(**edit_kwargs)
    else:
        response = openai_client.images.generate(**kwargs)

    return [item.b64_json or "" for item in response.data]


@typechecked
def _decode_and_persist(
    b64_strings: list[str],
    target_paths: list[pathlib.Path],
    output_format: str,  # noqa: ARG001 — kept for vllm-omni format hint symmetry
) -> None:
    """Base64-decode each string, write bytes to corresponding target_path.

    Lets OSError / binascii.Error propagate (§5).
    """
    for b64_str, target in zip(b64_strings, target_paths):
        raw_bytes = base64.b64decode(b64_str)
        with open(target, "wb") as f:
            f.write(raw_bytes)


# ---------------------------------------------------------------------------
# Cache level scanner (for list_local_models)
# ---------------------------------------------------------------------------


@typechecked
def _scan_level_for_models(
    level: CacheLevel,
    visible_models: dict[str, str],
) -> None:
    """Scan a CacheLevel's root for model snapshot directories.

    HF layout: models--<org>--<repo>/  → model = org/repo
    MS layout: models/<org>/<repo>/    → model = org/repo
    Deduplicates by model name (first level wins per 5-level chain).
    """
    root = pathlib.Path(level.root)
    if not root.is_dir():
        return

    if level.layout == "hf":
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.startswith("models--"):
                parts = entry.name[len("models--"):].split("--")
                if len(parts) == 2:
                    model_name = f"{parts[0]}/{parts[1]}"
                    visible_models.setdefault(model_name, level.name)
    elif level.layout == "ms":
        models_dir = root / "models"
        if models_dir.is_dir():
            for org_dir in models_dir.iterdir():
                if not org_dir.is_dir():
                    continue
                for repo_dir in org_dir.iterdir():
                    if repo_dir.is_dir():
                        model_name = f"{org_dir.name}/{repo_dir.name}"
                        visible_models.setdefault(model_name, level.name)


# ---------------------------------------------------------------------------
# MCP tool functions
# ---------------------------------------------------------------------------

server = FastMCP("local-image-gen")


@server.tool()
@typechecked
def list_local_models() -> list[dict]:
    """Enumerate models visible on disk in the 5-level cache chain.

    Returns a list of {model, current_load_status} dicts, sorted by model.
    """
    levels = cr.walk_levels()
    visible_models: dict[str, str] = {}
    for level in levels:
        _scan_level_for_models(level, visible_models)

    running_model: Optional[str] = None
    running_status: Optional[str] = None
    svc = _read_service_json()
    if svc is not None:
        pid = svc.get("pid", -1)
        try:
            os.kill(pid, 0)
            running_model = svc.get("model", "")
            running_status = svc.get("status", STATUS_READY)
        except (ProcessLookupError, PermissionError):
            _prune_stale_service_json()

    result: list[dict] = []
    for model_name in sorted(visible_models.keys()):
        if model_name == running_model and running_status is not None:
            if running_status == STATUS_LOADING:
                load_status = "loading"
            elif running_status == STATUS_READY:
                load_status = "loaded"
            else:
                load_status = "not_loaded"
        else:
            load_status = "not_loaded"
        result.append({"model": model_name, "current_load_status": load_status})

    return result


@server.tool()
@typechecked
async def start_service(
    model: str,
    cache_dir: Optional[str] = None,
    timeoutMs: Optional[int] = None,
) -> dict:
    """Spawn vllm-omni for `model` and return immediately with status=loading.

    A background daemon thread polls /v1/models and flips service.json's
    status to "ready" (or "failed" on timeout). Call list_running_services
    to observe the transition.

    Error codes: service_already_running, model_not_found,
    subprocess_launch_failed.
    """
    # 1. Check if a service is already running
    svc = _read_service_json()
    if svc is not None:
        pid = svc.get("pid", -1)
        try:
            os.kill(pid, 0)
            return {
                "error": {
                    "code": "service_already_running",
                    "message": (
                        f"A service for model '{svc.get('model', '')}' "
                        f"is already running (pid={pid})"
                    ),
                },
            }
        except (ProcessLookupError, PermissionError):
            _prune_stale_service_json()

    # 2. Resolve model to an on-disk snapshot
    if cache_dir is not None:
        resolved = await asyncio.to_thread(cr.resolve, model, cache_dir=cache_dir)
    else:
        resolved = await asyncio.to_thread(cr.resolve, model)
    if resolved is None:
        return {
            "error": {
                "code": "model_not_found",
                "message": f"Model '{model}' not found in any cache level",
            },
        }

    model_path = resolved.snapshot_for(model)
    if model_path is None:
        return {
            "error": {
                "code": "model_not_found",
                "message": (
                    f"Model '{model}' snapshot not found at level "
                    f"'{resolved.name}'"
                ),
            },
        }
    cache_source = resolved.name

    # 3. Pick a free port and spawn vllm-omni
    port = await asyncio.to_thread(_pick_free_port)
    args = [
        "vllm", "serve", model_path,
        "--omni",
        "--port", str(port),
        "--host", "127.0.0.1",
    ]
    proc = await asyncio.to_thread(_spawn_vllm_omni, args)
    pid = proc.pid

    # 4. Write service.json immediately with status=loading
    svc_record = {
        "model": model,
        "pid": pid,
        "port": port,
        "started_at": time.time(),
        "cache_source": cache_source,
        "model_path": model_path,
        "status": STATUS_LOADING,
    }
    await asyncio.to_thread(_write_service_json, svc_record)

    # 5. Fire the background poll thread (idempotent: skip if a live one exists)
    effective_timeout_s = DEFAULT_START_TIMEOUT_S
    if timeoutMs is not None and timeoutMs > 0:
        effective_timeout_s = timeoutMs / 1000.0

    existing = _poll_threads.get(pid)
    if existing is None or not existing.is_alive():
        t = threading.Thread(
            target=_background_poll_ready,
            args=(port, pid, effective_timeout_s),
            daemon=True,
        )
        _poll_threads[pid] = t
        t.start()

    return {
        "model": model,
        "pid": pid,
        "port": port,
        "status": STATUS_LOADING,
    }


@server.tool()
@typechecked
def list_running_services() -> list[dict]:
    """Return 0 or 1 entries describing the currently running service.

    Prunes stale service.json before responding. Status is read from the
    file (not from an in-memory cache).
    """
    svc = _read_service_json()
    if svc is None:
        return []

    pid = svc.get("pid", -1)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        _prune_stale_service_json()
        return []

    return [{
        "model": svc.get("model", ""),
        "pid": pid,
        "port": svc.get("port", 0),
        "started_at": svc.get("started_at", 0),
        "status": svc.get("status", STATUS_READY),
    }]


@server.tool()
@typechecked
async def invoke_model(
    prompt: str,
    filename: str,
    model: Optional[str] = None,
    image: Optional[str] = None,
    images: Optional[list[str]] = None,
    size: Optional[str] = None,
    outputFormat: str = "png",
    count: int = 1,
    negative_prompt: Optional[str] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
    true_cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    timeoutMs: Optional[int] = None,
) -> dict:
    """Forward an image-generation/edit request to the running vllm-omni.

    Returns {path, b64_json} on success; {error: {code, message}} on failure.
    Error codes: no_running_service, service_loading, model_not_loaded,
    filename_dir_not_found, filename_conflict, validation_error, vllm_error.
    """
    # 1. Validate prompt
    if not prompt:
        return {
            "error": {
                "code": "validation_error",
                "message": "prompt must be non-empty",
            },
        }

    # 2. Validate filename parent dir exists
    target = pathlib.Path(filename)
    parent_dir = target.parent
    if not parent_dir.exists():
        return {
            "error": {
                "code": "filename_dir_not_found",
                "message": f"Directory '{parent_dir}' does not exist",
            },
        }

    # 3. Compute multi-file targets for count > 1
    effective_count = max(count, 1)
    if effective_count > 1:
        multi_targets = [
            parent_dir / f"{target.stem}-{i}{target.suffix}"
            for i in range(1, effective_count + 1)
        ]
        for mt in multi_targets:
            if mt.exists():
                return {
                    "error": {
                        "code": "filename_conflict",
                        "message": f"File '{mt}' already exists",
                    },
                }
    else:
        multi_targets = [target]

    # 4. Read service.json
    svc = _read_service_json()
    if svc is None:
        return {
            "error": {
                "code": "no_running_service",
                "message": "No model service is currently running",
            },
        }

    pid = svc.get("pid", -1)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        _prune_stale_service_json()
        return {
            "error": {
                "code": "no_running_service",
                "message": "No model service is currently running (stale service file pruned)",
            },
        }

    # 5. Reject if still loading
    status = svc.get("status", STATUS_READY)
    if status == STATUS_LOADING:
        return {
            "error": {
                "code": "service_loading",
                "message": "Model service is still loading, please wait and retry",
            },
        }

    # 6. Check model match
    svc_model = svc.get("model", "")
    effective_model = model if model is not None else svc_model
    if model is not None and model != svc_model:
        return {
            "error": {
                "code": "model_not_loaded",
                "message": (
                    f"Requested model '{model}' does not match running model "
                    f"'{svc_model}'"
                ),
            },
        }

    # 7. Build the openai client and call vllm-omni
    from openai import OpenAI
    port = svc.get("port", 0)
    client = OpenAI(
        base_url=f"http://127.0.0.1:{port}/v1",
        api_key="dummy",
    )

    if timeoutMs is not None and timeoutMs > 0:
        timeout_s = timeoutMs / 1000.0
    else:
        timeout_s = float(DEFAULT_INVOKE_TIMEOUT_S)

    as_edit = image is not None or images is not None
    b64_list = await asyncio.to_thread(
        _route_invoke,
        client, prompt, effective_model, as_edit,
        image, images, size,
        outputFormat=outputFormat,
        count=effective_count,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        true_cfg_scale=true_cfg_scale,
        seed=seed,
        timeout_s=timeout_s,
    )

    # 8. Persist decoded images
    await asyncio.to_thread(
        _decode_and_persist,
        b64_list,
        multi_targets,
        outputFormat,
    )

    # 9. Build return value
    if effective_count == 1:
        return {
            "path": str(multi_targets[0]),
            "b64_json": b64_list[0],
        }
    return {
        "path": [str(t) for t in multi_targets],
        "b64_json": b64_list,
    }


@server.tool()
@typechecked
def release_service(model: str) -> dict:
    """Stop the running vllm-omni subprocess and remove service.json.

    Idempotent: returns no_running_service if no service is running.
    Error codes: no_running_service, model_not_loaded.
    """
    svc = _read_service_json()
    if svc is None:
        return {
            "error": {
                "code": "no_running_service",
                "message": "No model service is currently running",
            },
        }

    pid = svc.get("pid", -1)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        _prune_stale_service_json()
        return {
            "error": {
                "code": "no_running_service",
                "message": "No model service is currently running (stale service file pruned)",
            },
        }

    svc_model = svc.get("model", "")
    if svc_model != model:
        return {
            "error": {
                "code": "model_not_loaded",
                "message": (
                    f"Running model '{svc_model}' does not match requested "
                    f"'{model}'"
                ),
            },
        }

    _release_subprocess(pid)
    _poll_threads.pop(pid, None)
    os.remove(_STATE_DIR / SERVICE_FILE_NAME)

    return {
        "released": True,
        "model": svc_model,
        "pid": pid,
        "port": svc.get("port", 0),
    }


if __name__ == "__main__":
    server.run()
