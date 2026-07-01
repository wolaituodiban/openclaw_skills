import unittest
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock, PropertyMock
from openai.types.images_response import ImagesResponse, Image

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

from scripts.list_model_servers import ModelServerState
from scripts.invoke_model_server import invoke_model_server


mock_client = MagicMock()
mock_client.return_value = mock_client

mock_client.images.generate = MagicMock(
    return_value = ImagesResponse(
        created=1234567890,
        data=[
            Image(b64_json="aGVsbG8=", revised_prompt=None),
        ],
    )
)
mock_client.images.edit.return_value = mock_client.images.generate.return_value


class TestInvokeModelServer(unittest.TestCase):
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
                    local_path="/tmp/model_server",
                )
            ]
        )
        self.patcher_list_model_servers.start()

        # patch openai client
        self.patcher_openai_client = patch(
            "scripts.invoke_model_server.OpenAI",
            mock_client
        )
        self.patcher_openai_client.start()

        # patch DEFAULT_OUTPUT_DIR
        self.temp_output_dir = tempfile.TemporaryDirectory()
        os.makedirs(self.temp_output_dir.name, exist_ok=True)

        self.patcher_output_dir = patch(
            'scripts.invoke_model_server.DEFAULT_OUTPUT_DIR',
            self.temp_output_dir.name
        )
        self.patcher_output_dir.start()

    def tearDown(self):
        self.patcher_output_dir.stop()
        self.temp_output_dir.cleanup()
        self.patcher_openai_client.stop()
        self.patcher_list_model_servers.stop()
        self.patcher_model_server_state_status.stop()

    def test_repo_id_not_found(self):
        result = invoke_model_server(prompt="A beautiful landscape", repo_id="haha")
        self.assertEqual(result.status, "repo_id_not_found")

    def test_repo_id_is_none(self):
        result = invoke_model_server(prompt="A beautiful landscape")
        self.assertEqual(result.status, "succeed")
        self.assertEqual(len(result.output_files), 1)
        for output_path in result.output_files:
            self.assertTrue(os.path.exists(output_path))


if __name__ == "__main__":
    unittest.main()
        