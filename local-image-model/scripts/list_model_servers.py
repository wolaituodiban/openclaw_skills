import json
import sys
import os
from dataclasses import dataclass
from typing import Generator, Literal, List

import httpx
from typeguard import typechecked

BASE_DIR = os.path.expanduser("~/.local-image-model")
SERVICE_JSON_PATH = os.path.join(BASE_DIR, "service.json")


@typechecked
@dataclass(frozen=True)
class ModelServerState:
    pid: int
    port: int
    repo_id: str
    local_path: str

    def __post_init__(self):
        if not isinstance(self.pid, int):
            raise TypeError(f"pid must be an integer, got {type(self.pid)}")
        if not isinstance(self.port, int):
            raise TypeError(f"port must be an integer, got {type(self.port)}")
        if not isinstance(self.repo_id, str):
            raise TypeError(f"repo_id must be a string, got {type(self.repo_id)}")
        if not isinstance(self.local_path, str):
            raise TypeError(f"local_path must be a string, got {type(self.local_path)}")

    @property
    def status(self) -> Literal["stopped", "loading", "loaded"]:
        """Check the model's lifecycle by PID liveness + /v1/models probe."""
        try:
            os.kill(self.pid, 0)
        except OSError:
            return "stopped"

        try:
            resp = httpx.get(
                f"http://127.0.0.1:{self.port}/v1/models",
                timeout=0.1,
            )
            models = resp.json().get("data")
        except:
            models = []

        if isinstance(models, list) and len(models) > 0:
            return "loaded"
        else:
            return "loading"
        

@typechecked
def dump_model_server_states(model_servers: List[ModelServerState])-> None:
    with open(SERVICE_JSON_PATH, "w") as f:
        json.dump([{
            "pid": ms.pid,
            "port": ms.port,
            "repo_id": ms.repo_id,
            "local_path": ms.local_path,
        } for ms in model_servers], f, indent=4)
    print(f'write to {SERVICE_JSON_PATH} with {len(model_servers)} servers', flush=True, file=sys.stderr)


@typechecked
def list_model_servers() -> Generator[ModelServerState, None, None]:
    """
    List all model servers that are currently running and return their states.
    If the service.json file does not exist, it will be created and an empty list will be returned.
    write back to service.json only the model servers that are not stopped.
    """
    if not os.path.exists(SERVICE_JSON_PATH):
        os.makedirs(os.path.dirname(SERVICE_JSON_PATH), exist_ok=True)
        with open(SERVICE_JSON_PATH, "w") as f:
            json.dump([], f)
        return
    
    with open(SERVICE_JSON_PATH, "r") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f'[fatal] failed to load {SERVICE_JSON_PATH}, please validate this json file', flush=True, file=sys.stderr)
            raise e
            
    
    model_servers = []
    for i, item in enumerate(data):
        try:
            model_server = ModelServerState(
                pid=item["pid"],
                port=item["port"],
                repo_id=item["repo_id"],
                local_path=item["local_path"],
            )
        except Exception as e:
            print(f'[fatal] failed to transform item ({i}) {item} into ModelServerState', flush=True, file=sys.stderr)
            raise e
        if model_server.status != "stopped":
            yield model_server
            model_servers.append(model_server)
        
    dump_model_server_states(model_servers)

