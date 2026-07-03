import os
import subprocess
import re
from dataclasses import dataclass
from typing import Generator, Literal

from typeguard import typechecked
from modelscope_hub._cache_manager import scan_cache
from .list_model_servers import list_model_servers, ModelServerState


@typechecked
def get_size_bytes(path: str) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_size_bytes(entry.path)
    except (PermissionError, FileNotFoundError):
        pass
    return total


@typechecked
@dataclass
class ModelCache:
    repo_id: str
    local_path: str
    model_server_states: list[ModelServerState]

    def __post_init__(self):
        if not isinstance(self.repo_id, str):
            raise TypeError(f"repo_id must be a string, got {type(self.repo_id)}")
        if not isinstance(self.local_path, str):
            raise TypeError(f"local_path must be a string, got {type(self.local_path)}")
        if not isinstance(self.model_server_states, list):
            raise TypeError(f"model_server_states must be a list, got {type(self.model_server_states)}")
        for state in self.model_server_states:
            if not isinstance(state, ModelServerState):
                raise TypeError(f"Each item in model_server_states must be a ModelServerState instance, got {type(state)}")
            
    def get_status(self) -> Literal["not_loaded", "loading", "loaded"]:
        for model_server_state in self.model_server_states:
            if model_server_state.status == "loaded":
                return "loaded"
            elif model_server_state.status == "loading":
                return "loading"
        return "not_loaded"
    
    def get_size_bytes(self) -> float:
        return get_size_bytes(self.local_path)
    

@typechecked
def list_model_caches() -> Generator[ModelCache, None, None]:
    model_server_states = list(list_model_servers())

    # 运行modelscope cli
    cache_info = scan_cache()
    
    # 输出结构化ModelCache信息
    for repo in cache_info.repos:
        local_path = os.path.join(repo.local_path, 'snapshots', 'master')
        yield ModelCache(
            repo_id=repo.repo_id,
            local_path=local_path,
            model_server_states=[server for server in model_server_states if server.local_path == local_path]
        )
