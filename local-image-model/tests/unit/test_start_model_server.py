import json
import os
import signal
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import sys

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

from scripts.start_model_server import start_model_server, MAX_SERVERS_REACHED, LOCAL_PATH_NOT_FOUND, STARTED
from scripts.list_model_caches import ModelCache


class TestStartModelServer(unittest.TestCase):
    def setUp(self):
        # patch list_model_cache
        self.local_path = "/haha/haha"

        self.patcher_list_model_cache = patch(
            "scripts.start_model_server.list_model_caches",
            return_value=[
                ModelCache(
                    repo_id="Tongyi-MAI/Z-Image-Turbo",
                    local_path=self.local_path,
                    model_server_states=[],
                )
            ]
        )
        self.patcher_list_model_cache.start()


        # 每个 test 拿到一个独立的临时 service.json
        self.tmp_json = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
        )

        with open(self.tmp_json.name, "w") as f:
            json.dump([
                {
                    "pid": os.getpid(),
                    "port": 5678,
                    "repo_id": "Tongyi-MAI/Z-Image-Turbo",
                    "local_path": 'test1',
                },
                {
                    "pid": 2345,
                    "port": 6789,
                    "repo_id": "Qwen/Qwen-Image",
                    "local_path": 'test2',
                }
            ], f, ensure_ascii=True)

        # 把模块里硬编码的 SERVICE_JSON_PATH 替换成 tmp 文件
        self.patcher_json = patch(
            "scripts.list_model_servers.SERVICE_JSON_PATH",
            self.tmp_json.name,
        )
        self.patcher_json.start()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"id": "Tongyi-MAI/Z-Image-Turbo"}]}

        # patch httpx.get to return the mock response for model server status checks
        self.patcher_httpx = patch(
            "scripts.list_model_servers.httpx.get",
            return_value=mock_resp,
        )
        self.patcher_httpx.start()

    def tearDown(self):
        self.patcher_list_model_cache.stop()
        self.tmp_json.close()
        self.patcher_json.stop()
        self.patcher_httpx.stop()

    def test_has_loaded_model(self):
        
        result = start_model_server("Tongyi-MAI/Z-Image-Turbo")
        self.assertEqual(result.status, MAX_SERVERS_REACHED)

    def test_repo_id_not_found(self):
        self.tmp_json.close()

        result = start_model_server("a")
        self.assertEqual(result.status, LOCAL_PATH_NOT_FOUND)

    def test_start_model_server(self):
        self.tmp_json.close()
        
        result = start_model_server(self.local_path)

        # 清理启动的模型服务进程
        os.kill(result.model_server_state.pid, signal.SIGTERM)
        print(f"Cleaned up model server process with PID {result.model_server_state.pid}", flush=True, file=sys.stderr)
        
        # 判断result
        self.assertEqual(result.model_server_state.repo_id, "Tongyi-MAI/Z-Image-Turbo")
        self.assertEqual(result.status, STARTED)
        
        # state文件item + 1
        with open(self.tmp_json.name, 'r') as file:
            json_object = json.load(file)
            self.assertEqual(len(json_object), 1)

        # 清理启动的模型服务进程
        os.kill(result.model_server_state.pid, signal.SIGTERM)
        print(f"Cleaned up model server process with PID {result.model_server_state.pid}", flush=True, file=sys.stderr)



if __name__ == "__main__":
    unittest.main()