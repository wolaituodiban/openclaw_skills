import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import sys

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

from scripts.list_model_caches import list_model_caches


class TestListModelCaches(unittest.TestCase):
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

    def tearDown(self):
        self.tmp_cache_dir.cleanup()
        self.patcher_cache_dir.stop()
        self.tmp_json.close()
        self.patcher_json.stop()

    def test_list_model_caches(self):
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"id": "Tongyi-MAI/Z-Image-Turbo"}]}

        with patch("scripts.list_model_servers.httpx.get", return_value=mock_resp):
            result = list(list_model_caches())
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].repo_id, "Qwen/Qwen-Image")
            self.assertEqual(result[0].get_status(), "not_loaded")
            self.assertEqual(result[1].repo_id, "Tongyi-MAI/Z-Image-Turbo")
            self.assertEqual(len(result[1].model_server_states), 1)
            self.assertEqual(result[1].get_status(), "loaded")


if __name__ == "__main__":
    unittest.main()