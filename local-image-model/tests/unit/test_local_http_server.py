import requests
import os
import tempfile
import unittest
import secrets

import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..')
sys.path.append(SCRIPTS_DIR)

from scripts.local_http_server import local_http_server


class TestLocalHttpServer(unittest.TestCase):
    def test(self):
        with tempfile.NamedTemporaryFile() as temp_file:
            with open(temp_file.name, 'w') as file:
                file.write(secrets.token_hex(16))

            with local_http_server([temp_file.name]) as url_map:
                for path, url in url_map.items():
                    with open(path, 'r') as file:
                        origin_content = file.read()

                    url_content = requests.get(url).content.decode()
                    self.assertEqual(origin_content, url_content)


if __name__ == '__main__':
    unittest.main()