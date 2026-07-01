import atexit
import signal
import os
import json
from typing import Optional, Union, List
from dataclasses import asdict

from typeguard import typechecked
from mcp.server.fastmcp import FastMCP

from .list_model_servers import list_model_servers as _list_model_servers
from .list_model_caches import list_model_caches as _list_model_caches
from .start_model_server import start_model_server as _start_model_server
from .invoke_model_server import invoke_model_server as _invoke_model_server
from .release_model_server import release_model_server as _release_model_server


def cleanup():
    for s in _list_model_servers():
        try:
            os.killpg(s.pid, signal.SIGTERM)
        except OSError:
            pass

atexit.register(cleanup)


mcp_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))

mcp = FastMCP(mcp_name)


@mcp.tool()
async def list_model_servers() -> str:
    """
    list all running image model servers
    """
    msg = []
    for model_server in _list_model_servers():
        item = asdict(model_server)
        item['status'] = model_server.status
        msg.append(item)
    return json.dumps(msg, indent=2, ensure_ascii=False)


@typechecked
def humanize_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

@mcp.tool()
async def list_model_caches() -> str:
    """
    list all local cached model
    """
    msg = []
    for cache in _list_model_caches():
        item = asdict(cache)
        item['size_on_disk'] = humanize_bytes(cache.get_size_bytes())
        item['status'] = cache.get_status()
        msg.append(item)
    return json.dumps(msg, indent=2, ensure_ascii=False)


@mcp.tool()
async def start_model_server(repo_id: str) -> str:
    """
    starting a model server

    Args:
        repo_id: hugging face style model repo id
    """

    result = _start_model_server(repo_id)
    return json.dumps(asdict(result), indent=2, ensure_ascii=False)


@mcp.tool()
async def invoke_model_server(
    prompt: str,
    filename: Optional[str] = None,
    repo_id: Optional[str] = None,
    image: Optional[Union[List[str], str]] = None,
    size: Optional[str] = None,
    n: int = 1,
    negative_prompt: Optional[str] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
    true_cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
):
    """
    invoke model, when image is provided, invoke edit, else invoke generate

    Args:
        prompt (str): (required) Text description of the desired image
        filename (str): filename for output, must be full path
        repo_id (str): hugging face style model repo id
        image (str or list of str): path of The image(s) to edit.
        size (str): Image dimensions in WxH format (e.g., "1024x1024", "512x512"), when set to auto, it decide size from first input image.
        n (int): Number of images to generate (1-10)
        negative_prompt (str): Text describing what to avoid in the image
        num_inference_steps (int): Number of diffusion steps
        guidance_scale (float): Classifier-free guidance scale (typically 0.0-20.0)
        true_cfg_scale (float): True CFG scale (model-specific parameter, may be ignored if not supported)
        seed (int): Random seed for reproducibility
    """
    result = _invoke_model_server(
        prompt=prompt,
        filename=filename,
        repo_id=repo_id,
        image=image,
        size=size,
        n=n,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        true_cfg_scale=true_cfg_scale,
        seed=seed
    )
    return json.dumps(asdict(result), indent=2, ensure_ascii=False)


@mcp.tool()
async def release_model_server(pid: Optional[int] = None, repo_id: Optional[str] = None) -> str:
    """
    release model server

    release when pid is matched or repo_id is matched

    Args:
        pid: pid
        repo_id: hugging face style model repo id
    
    """
    result = _release_model_server(pid=pid, repo_id=repo_id)
    return json.dumps(list(map(asdict, result)), indent=2, ensure_ascii=False)


def main():
    # Initialize and run the server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()