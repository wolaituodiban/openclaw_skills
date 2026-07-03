import http.server
import socketserver
import threading
import os
from typing import List, Dict
from contextlib import contextmanager

from typeguard import typechecked
from .start_model_server import HOST

@contextmanager
@typechecked
def local_http_server(path_list: List[str]):
    """把 path_list 里的文件挂到本地 HTTP server 上，URL → 原始文件，不复制。"""

    # 1. URL path → 原始文件绝对路径 的映射
    url_to_file: Dict[str, str] = {
        f'/{i}{os.path.splitext(p)[1]}': os.path.expanduser(p)
        for i, p in enumerate(path_list)
    }

    class FileHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url_path = self.path.split('?', 1)[0]              # 去 query string
            file_path = url_to_file.get(url_path)
            if not file_path or not os.path.exists(file_path):
                self.send_error(404, 'Not Found'); return
            try:
                with open(file_path, 'rb') as f:
                    data = f.read()
            except OSError:
                self.send_error(500); return

            ext = os.path.splitext(file_path)[1].lower()
            ctype = {'.png': 'image/png', '.jpg': 'image/jpeg',
                     '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(ext,
                          'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a, **kw):                       # 关掉默认 stderr 日志
            pass

    with socketserver.TCPServer((HOST, 0), FileHandler) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        url = f'http://{HOST}:{port}'

        # 2. 输出映射（外部 API 不变）：原路径 → URL
        mapping = {
            path: f'{url}/{i}{os.path.splitext(path)[1]}'
            for i, path in enumerate(path_list)
        }

        try:
            yield mapping
        finally:
            httpd.shutdown()
            httpd.server_close()
    