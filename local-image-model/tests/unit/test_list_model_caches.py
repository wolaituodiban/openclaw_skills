import os
import unittest
from unittest.mock import patch, PropertyMock

import sys

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

from scripts.list_model_caches import list_model_caches, ModelServerState


class TestListModelCaches(unittest.TestCase):
    def setUp(self):
        # patch ModelServerState.status
        mock_prop = PropertyMock(return_value='loaded')
        self.patcher_model_server_state_status = patch.object(
            ModelServerState, 'status', new=mock_prop
        )
        self.patcher_model_server_state_status.start()
        
        # patch list_model_servers
        self.patcher_list_model_servers = patch(
            "scripts.invoke_model_server.list_model_servers",
            return_value=[
                ModelServerState(
                    pid=1234,
                    port=5678,
                    repo_id="Tongyi-MAI/Z-Image-Turbo",
                    local_path="/home/cxt/.cache/modelscope/models/Tongyi-MAI--Z-Image-Turbo",
                    log_path='haha'
                )
            ]
        )
        self.patcher_list_model_servers.start()

    def tearDown(self):
        self.patcher_list_model_servers.stop()
        self.patcher_model_server_state_status.stop()

    def test_list_model_caches(self):
        result = list(list_model_caches())
        self.assertTrue('Tongyi-MAI/Z-Image-Turbo' in [item.repo_id for item in result])


if __name__ == "__main__":
    unittest.main()