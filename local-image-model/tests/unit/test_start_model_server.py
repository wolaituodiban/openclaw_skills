import json
import os
import signal
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import sys

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

import scripts.list_model_servers
import scripts.list_model_caches
from scripts.start_model_server import start_model_server


class TestStartModelServer(unittest.TestCase):
    def setUp(self):
        # 创建一个临时目录，作为 model server 的 local_path
        self.tmp_cache_dir = tempfile.TemporaryDirectory()

        # patch MODEL_SCOPE_CACHE_DIR
        self.patcher_cache_dir = patch(
            "scripts.list_model_caches.MODEL_SCOPE_CACHE_DIR",
            self.tmp_cache_dir.name,
        )
        self.patcher_cache_dir.start()

        self.z_image_path = os.path.join(self.tmp_cache_dir.name, "Tongyi-MAI/Z-Image-Turbo")
        self.qwen_image_path = os.path.join(self.tmp_cache_dir.name, "Qwen/Qwen-Image")
        os.makedirs(self.z_image_path, exist_ok=True)
        os.makedirs(self.qwen_image_path, exist_ok=True)

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
                    "local_path": self.z_image_path,
                },
                {
                    "pid": 2345,
                    "port": 6789,
                    "repo_id": "Qwen/Qwen-Image",
                    "local_path": self.qwen_image_path,
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
        self.tmp_cache_dir.cleanup()
        self.patcher_cache_dir.stop()
        self.tmp_json.close()
        self.patcher_json.stop()
        self.patcher_httpx.stop()

    def test_has_loaded_model(self):
        
        result = start_model_server("Tongyi-MAI/Z-Image-Turbo")
        self.assertEqual(result.status, 'max_servers_reached')

    def test_repo_id_not_found(self):
        self.tmp_json.close()

        result = start_model_server("a")
        self.assertEqual(result.status, 'repo_id_not_found')

    def test_start_model_server(self):
        self.tmp_json.close()
        
        result = start_model_server("Tongyi-MAI/Z-Image-Turbo")
        # 清理启动的模型服务进程
        os.kill(result.model_server_state.pid, signal.SIGTERM)
        print(f"Cleaned up model server process with PID {result.model_server_state.pid}", flush=True, file=sys.stderr)

        # 判断result
        self.assertEqual(result.status, 'start')
        self.assertEqual(result.model_server_state.repo_id, "Tongyi-MAI/Z-Image-Turbo")

        # state文件item + 1
        with open(self.tmp_json.name, 'r') as file:
            json_object = json.load(file)
            self.assertEqual(len(json_object), 1)

        # 清理启动的模型服务进程
        os.kill(result.model_server_state.pid, signal.SIGTERM)
        print(f"Cleaned up model server process with PID {result.model_server_state.pid}", flush=True, file=sys.stderr)



if __name__ == "__main__":
    unittest.main()