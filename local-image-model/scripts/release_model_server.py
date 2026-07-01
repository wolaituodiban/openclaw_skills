import os
import signal
import sys
from typing import Optional, List

from typeguard import typechecked

from .list_model_servers import dump_model_server_states, list_model_servers, ModelServerState


@typechecked
def release_model_server(pid: Optional[int] = None, repo_id: Optional[str] = None) -> List[ModelServerState]:
    model_servers = list(list_model_servers())
    
    remained = []
    released = []
    for server in model_servers:
        if (pid is not None and server.pid == pid) or (repo_id is not None and server.repo_id == repo_id):
            os.kill(server.pid, signal.SIGTERM)
            released.append(server)
            print(f"realease model server pid ({server.pid}), repo_id ({server.repo_id})", flush=True, file=sys.stderr)
        else:
            remained.append(server)

    if len(remained) == len(model_servers):
        print(f'pid not found {pid}', flush=True, file=sys.stderr)

    dump_model_server_states(remained)
    return released