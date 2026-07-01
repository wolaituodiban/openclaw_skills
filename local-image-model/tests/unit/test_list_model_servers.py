import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../scripts')
sys.path.append(SCRIPTS_DIR)

from list_model_servers import list_model_servers


class TestListModelServers(unittest.TestCase):
    def setUp(self):
        # 创建一个临时目录，作为 model server 的 local_path
        self.tmp_local_path = tempfile.NamedTemporaryFile()

        # 每个 test 拿到一个独立的临时 service.json
        self.tmp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
        )
        self.tmp_json_path = self.tmp_file.name

        # 把模块里硬编码的 SERVICE_JSON_PATH 替换成 tmp 文件
        self.patcher = patch.object(
            __import__("list_model_servers"),
            "SERVICE_JSON_PATH",
            self.tmp_json_path,
        )
        self.patcher.start()

    def tearDown(self):
        self.tmp_local_path.close()
        self.tmp_file.close()
        self.patcher.stop()

    def test_empty_file(self):
        self.tmp_file.close()
        result = list(list_model_servers())
        self.assertEqual(result, [])
        # 然后文件应该被自动创建成 []
        with open(self.tmp_json_path) as f:
            self.assertEqual(json.load(f), [])

    def test_stopped_server(self):
        
        with open(self.tmp_json_path, "w") as f:
            json.dump([{
                "pid": 1234,
                "port": 5678,
                "repo_id": "Tongyi-MAI/Z-Image-Turbo",
                "local_path": self.tmp_local_path.name,
            }], f, ensure_ascii=True)

        # pid 1234 不是当前进程，os.kill(1234, 0) 会抛 OSError
        # status 变成 "stopped"，过滤掉
        result = list(list_model_servers())
        self.assertEqual(result, [])

    def test_loaded_server(self):

        with open(self.tmp_json_path, "w") as f:
            json.dump([{
                "pid": os.getpid(),
                "port": 5678,
                "repo_id": "Tongyi-MAI/Z-Image-Turbo",
                "local_path": self.tmp_local_path.name,
            }], f, ensure_ascii=True)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"id": "Tongyi-MAI/Z-Image-Turbo"}]}

        with patch("list_model_servers.httpx.get", return_value=mock_resp):
            result = list(list_model_servers())
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].status, "loaded")

    def test_loading_server(self):

        with open(self.tmp_json_path, "w") as f:
            json.dump([{
                "pid": os.getpid(),
                "port": 5678,
                "repo_id": "Tongyi-MAI/Z-Image-Turbo",
                "local_path": self.tmp_local_path.name,
            }], f, ensure_ascii=True)

        mock_resp = MagicMock()

        with patch("list_model_servers.httpx.get", return_value=mock_resp):
            result = list(list_model_servers())
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].status, "loading")


if __name__ == "__main__":
    unittest.main()