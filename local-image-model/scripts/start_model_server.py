import subprocess
from typing import Optional, Literal
from dataclasses import dataclass

import socket
from typeguard import typechecked


from .list_model_caches import list_model_caches
from .list_model_servers import ModelServerState, list_model_servers, dump_model_server_states


GLOBAL_MAX_MODEL_SERVERS = 1
HOST = "127.0.0.1"
 
MAX_SERVERS_REACHED = 'max_servers_reached'
REPO_ID_NOT_FOUND = 'repo_id_not_found'
START = 'start'

@typechecked
@dataclass(frozen=True)
class StartModelServerResult:
    status: Literal[MAX_SERVERS_REACHED, REPO_ID_NOT_FOUND, START]
    model_server_state: Optional[ModelServerState] = None

    def __post_init__(self):
        if self.status not in (MAX_SERVERS_REACHED, REPO_ID_NOT_FOUND, START):
            raise ValueError(f"status must be one of {MAX_SERVERS_REACHED}, {REPO_ID_NOT_FOUND}, {START}, got {self.status}")
        if self.model_server_state is not None and not isinstance(self.model_server_state, ModelServerState):
            raise TypeError(f"model_server_state must be a ModelServerState instance or None, got {type(self.model_server_state)}")


@typechecked
def start_model_server(repo_id: str) -> StartModelServerResult:
    model_servers = list(list_model_servers())
    if len(model_servers) >= GLOBAL_MAX_MODEL_SERVERS:
        return StartModelServerResult(status=MAX_SERVERS_REACHED)

    for model_cache in list_model_caches():
        if model_cache.repo_id == repo_id:
            break
    else:
        return StartModelServerResult(status=REPO_ID_NOT_FOUND)
    
    # Find an available port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]

    # 启动模型服务的逻辑
    p = subprocess.Popen(
        ["vllm", "serve", model_cache.local_path, "--omni", "--port", str(port), "--host", HOST],
    )

    model_server_state=ModelServerState(
        pid=p.pid,
        port=port,
        repo_id=model_cache.repo_id,
        local_path=model_cache.local_path,
    )

    # 新服务落盘
    model_servers.append(model_server_state)
    dump_model_server_states(model_servers)

    return StartModelServerResult(status=START, model_server_state=model_server_state)