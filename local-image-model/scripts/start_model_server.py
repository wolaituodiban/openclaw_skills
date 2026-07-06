import subprocess
import os
import time
import sys
import json
from typing import Optional, Literal
from dataclasses import dataclass

import socket
from typeguard import typechecked


from .list_model_caches import list_model_caches
from .list_model_servers import ModelServerState, list_model_servers, dump_model_server_states, BASE_DIR


GLOBAL_MAX_MODEL_SERVERS = 1
HOST = "127.0.0.1"
 
MAX_SERVERS_REACHED = 'max_servers_reached'
LOCAL_PATH_NOT_FOUND = 'local_path_not_found'
STARTED = 'started'

@typechecked
@dataclass(frozen=True)
class StartModelServerResult:
    status: Literal[MAX_SERVERS_REACHED, LOCAL_PATH_NOT_FOUND, STARTED]
    model_server_state: Optional[ModelServerState] = None

    def __post_init__(self):
        if self.status not in (MAX_SERVERS_REACHED, LOCAL_PATH_NOT_FOUND, STARTED):
            raise ValueError(f"status must be one of {MAX_SERVERS_REACHED}, {LOCAL_PATH_NOT_FOUND}, {STARTED}, got {self.status}")
        if self.model_server_state is not None and not isinstance(self.model_server_state, ModelServerState):
            raise TypeError(f"model_server_state must be a ModelServerState instance or None, got {type(self.model_server_state)}")


@typechecked
def start_model_server(
    local_path: str,
    quantization: Optional[Literal['fp8', 'int8']]=None,
) -> StartModelServerResult:
    """
    
    Args:
        local_path: 模型文件夹的绝对路径
        quantization: 量化类型，fp8 or int8
        gguf_model: loads pre-quantized diffusion transformer weights. accepts Local file (/models/z-image-Q4_K_M.gguf), Explicit HF file (QuantStack/Qwen-Image-GGUF/Qwen_Image-Q4_K_M.gguf)
            use list_model_caches to find proper gguf_model
    """
    model_servers = list(list_model_servers())
    if len(model_servers) >= GLOBAL_MAX_MODEL_SERVERS:
        return StartModelServerResult(status=MAX_SERVERS_REACHED)

    local_path = os.path.abspath(os.path.expanduser(local_path))
    for model_cache in list_model_caches():
        if model_cache.local_path == local_path:
            break
    else:
        return StartModelServerResult(status=LOCAL_PATH_NOT_FOUND)
    
    # Find an available port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]

    # log file
    log_path = os.path.join(BASE_DIR, 'logs', f'vllm-omni-{time.time()}.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # 启动模型服务的逻辑
    with open(log_path, 'a', buffering=1) as log: 
        args =["vllm", "serve", local_path, "--omni", "--port", str(port), "--host", HOST]
        if quantization is not None:
            args += ['--quantization', quantization]

        print(f'start model server with command: {args}', flush=True, file=sys.stderr)
        p = subprocess.Popen(
            args,
            stdout=log,
            stderr=subprocess.STDOUT,                       # 合并到 stdout
            start_new_session=True,                         # 独立进程组
            env={**os.environ, 'VLLM_LOGGING_LEVEL': 'DEBUG'},
        )

    model_server_state=ModelServerState(
        pid=p.pid,
        port=port,
        repo_id=model_cache.repo_id,
        local_path=model_cache.local_path,
        log_path=log_path
    )

    # 新服务落盘
    model_servers.append(model_server_state)
    dump_model_server_states(model_servers)

    return StartModelServerResult(status=STARTED, model_server_state=model_server_state)