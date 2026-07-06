import os
import json
import sys
import unittest
import time

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')
sys.path.append(SKILL_DIR)

from scripts.mcp_server import (
    list_model_caches,
    start_model_server,
    list_model_servers,
    invoke_model_server,
    release_model_server
)


class TestLifeCycle(unittest.IsolatedAsyncioTestCase):
    async def test_life_cycle(self):
        print('list_model_caches')
        model_caches = await list_model_caches()
        model_caches = json.loads(model_caches)
        print(model_caches)


        print('start_model_server')
        local_path = [model_cache['local_path'] for model_cache in model_caches if model_cache['repo_id'] == 'Tongyi-MAI/Z-Image-Turbo'][0]
        result = await start_model_server(local_path, quantization='int8')
        print(result)

        loading = True
        while loading:
            print('list_model_servers')
            server_infos = await list_model_servers()
            print(server_infos)
            time.sleep(5)
            
            server_infos = json.loads(server_infos)
            for item in server_infos:
                if item['status'] != 'loading':
                    loading = False

        print('invoke_model_server')
        result = await invoke_model_server(
            prompt='minimax-m3的编程能力相当于非软件专业低年级大学生水平，单个库能用，不会组合，写代码凭印象，不会查文档，解释原理靠想象，不看源码。',
            repo_id=server_infos[0]['repo_id'],
            filename='~/.openclaw/example_quant.png',
            num_inference_steps=20,
        )
        print(result)

        print('release_model_server')
        result = await release_model_server(pid=server_infos[0]['pid'])
        print(result)


if __name__ == '__main__':
    unittest.main()

