import http.server
import socketserver
import threading
import tempfile
import shutil
import os
from typing import List
from contextlib import contextmanager

from typeguard import typechecked
from .start_model_server import HOST

@contextmanager
@typechecked
def local_http_server(path_list: List[str]):
    """
    将path_list转换成url_list，放在http server上，并输出mapping
    
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        """在 directory 上起 HTTP server，yield url，用完自动清理。"""
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
            *a, directory=temp_dir, **kw
        )

        with socketserver.TCPServer((HOST, 0), handler) as httpd:            
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            port = httpd.server_address[1]
            url = f'http://{HOST}:{port}'

            # 获得path与url的映射关系
            mapping = {}
            for i, path in enumerate(path_list):
                _, ext = os.path.splitext(path)
                new_file_name = f'{i}{ext}'
                shutil.copy2(os.path.expanduser(path), os.path.join(temp_dir, new_file_name))
                mapping[path] = f'{url}/{new_file_name}'

            try:                
                yield mapping
            finally:
                httpd.shutdown()
                httpd.server_close()
    