import http.server
import socketserver
import threading
from contextlib import contextmanager

from .start_model_server import HOST

@contextmanager
def local_http_server(path: str):
    """在 directory 上起 HTTP server，yield url，用完自动清理。"""
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=path, **kw
    )
    with socketserver.TCPServer((HOST, 0), handler) as httpd:
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            url = f'http://{HOST}:{port}'
            yield url
        finally:
            httpd.shutdown()
            httpd.server_close()