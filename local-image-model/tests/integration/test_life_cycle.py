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
        print('release_model_server')
        result = await release_model_server(repo_id='Tongyi-MAI/Z-Image-Turbo')
        print(result)

        print('list_model_caches')
        result = await list_model_caches()
        print(result)

        print('start_model_server')
        result = await start_model_server('Tongyi-MAI/Z-Image-Turbo')
        print(result)

        loading = True
        while loading:
            print('list_model_servers')
            result = await list_model_servers()
            print(result)
            time.sleep(5)
            
            result = json.loads(result)
            for item in result:
                if item['status'] != 'loading':
                    loading = False

        print('invoke_model_server')
        result = await invoke_model_server(
            prompt='minimax-m3的编程能力相当于非软件专业低年级大学生水平，单个库能用，不会组合，写代码凭印象，不会查文档，解释原理靠想象，不看源码。',
            repo_id='Tongyi-MAI/Z-Image-Turbo',
            filename='~/.openclaw/example.png',
            num_inference_steps=20,
        )
        print(result)

        print('invoke_model_server')
        result = await invoke_model_server(
            prompt='在原图的基础上给minimax-m3画一个猪的形象',
            filename='~/.openclaw/example_0.png',
            image='~/.openclaw/example.png',
            num_inference_steps=20,
        )
        print(result)

        print('release_model_server')
        result = await release_model_server(repo_id='Tongyi-MAI/Z-Image-Turbo')
        print(result)


if __name__ == '__main__':
    unittest.main()

