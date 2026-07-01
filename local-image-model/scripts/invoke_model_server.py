import base64
import os
import sys
import time
from pathlib import Path

from typing import Optional, Union, List, Literal
from dataclasses import dataclass

from openai import OpenAI
from typeguard import typechecked

from .list_model_servers import list_model_servers, ModelServerState, BASE_DIR
from .start_model_server import HOST, REPO_ID_NOT_FOUND

DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

SUCCEED = 'succeed'

@typechecked
@dataclass(frozen=True)
class InvokeModelServerResult:
    status: Literal[REPO_ID_NOT_FOUND, SUCCEED]
    model_server_state: Optional[ModelServerState] = None
    output_files: Optional[List[str]] = None

    def __post_init__(self):
        if self.status not in (REPO_ID_NOT_FOUND, SUCCEED):
            raise ValueError(f"status must be one of {REPO_ID_NOT_FOUND}, {SUCCEED}, got {self.status}")
        if self.model_server_state is not None and not isinstance(self.model_server_state, ModelServerState):
            raise TypeError(f"model_server_state must be a ModelServerState instance or None, got {type(self.model_server_state)}")
        if self.output_files is not None and not isinstance(self.output_files, list):
            raise TypeError(f"output_files must be a list or None, got {type(self.output_files)}")


@typechecked
def invoke_model_server(
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
) -> InvokeModelServerResult:

    for server in list_model_servers():
        if (repo_id is None or server.repo_id == repo_id) and server.status == "loaded":
            break
    else:
        print(f"Model server not found or not loaded for {repo_id}", flush=True, file=sys.stderr)
        return InvokeModelServerResult(status=REPO_ID_NOT_FOUND)

    extra_body = {}
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
    
    client = OpenAI(api_key="None", base_url=f"http://{HOST}:{server.port}/v1")
    print(f"Invoking model server at {client.base_url} for repo_id {repo_id}", flush=True, file=sys.stderr)
    if image is None:
        print(f"Generating image with prompt: {prompt}", flush=True, file=sys.stderr)
        response = client.images.generate(
            prompt=prompt,
            model=repo_id,
            n=n,
            size=size,
            extra_body=extra_body
        )
    else:
        if isinstance(image, str):
            image = [image]
        
        image = [os.path.expanduser(path) for path in image]
        
        for path in image:
            if not os.path.exists(path):
                raise ValueError(f"{path} not exists")
        
        image_text = ', '.join(image)
        print(f"Editing image with prompt: {prompt}, image: {image_text}", flush=True, file=sys.stderr)

        response = client.images.edit(
            prompt=prompt,
            model=repo_id,
            image=[],
            n=n,
            size=size,
            extra_body=extra_body
        )

    if filename is None:
        filename = os.path.join(DEFAULT_OUTPUT_DIR, f"{int(time.time())}.png")

    stem, ext = os.path.splitext(os.path.expanduser(filename))
    output_files = []
    for i, item in enumerate(response.data):
        filename = f"{stem}_{i}{ext}"
        output_files.append(filename)
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(item.b64_json)  # 解码
        path.write_bytes(raw) 
        print(f"Saved image to {filename}", flush=True, file=sys.stderr)

    return InvokeModelServerResult(
        status=SUCCEED,
        model_server_state=server,
        output_files=output_files
    )