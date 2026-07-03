import unittest
import os
import sys
import tempfile
import subprocess
import json
from unittest.mock import patch

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

from scripts.release_model_server import release_model_server


class TestReleaseModelServer(unittest.TestCase):
    def setUp(self):
        # mock a server
        self.p = subprocess.Popen(["sleep", "3600"])

        # patch SERVICE_JSON_PATH
        self.temp_file = tempfile.NamedTemporaryFile()
        with open(self.temp_file.name, 'w') as file:
            json.dump(
                [
                    dict(
                        pid=self.p.pid,
                        port=5678,
                        repo_id="Tongyi-MAI/Z-Image-Turbo",
                        local_path="/tmp/model_server",
                        log_path='haha'
                    )
                ],
                file
            )

        self.patcher_server_json_path = patch(
            'scripts.list_model_servers.SERVICE_JSON_PATH',
            self.temp_file.name
        )
        self.patcher_server_json_path.start()


    def tearDown(self):
        self.patcher_server_json_path.stop()
        self.temp_file.close()
        self.p.kill()

    def test_release_pid(self):
        release_model_server(self.p.pid)

        # 判断json文件为空list
        with open(self.temp_file.name, 'r') as file:
            json_obj = json.load(file)

        self.assertEqual(len(json_obj), 0)

    def test_release_repo_id(self):
        release_model_server(repo_id="Tongyi-MAI/Z-Image-Turbo")

        # 判断json文件为空list
        with open(self.temp_file.name, 'r') as file:
            json_obj = json.load(file)

        self.assertEqual(len(json_obj), 0)



if __name__ == '__main__':
    unittest.main()