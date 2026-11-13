# utils/tile_server.py
import http.server
import socketserver
import threading
import os
from functools import partial
from urllib.parse import urlparse

class TileServerThread(threading.Thread):
    def __init__(self, port=8081, tile_dir="offline_data/tiles"):
        super().__init__()
        self.port = port
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.tile_dir = os.path.join(base_dir, tile_dir)
        self.daemon = True
        self.httpd = None

    def run(self):
        try:
            os.makedirs(self.tile_dir, exist_ok=True)
            class QuietCORSRequestHandler(http.server.SimpleHTTPRequestHandler):
                def end_headers(self):
                    self.send_header('Access-Control-Allow-Origin', '*')
                    super().end_headers()
                
                def log_message(self, format, *args):
                    pass # 屏蔽普通的终端请求日志，保持界面干净
                    
                def do_GET(self):
                    # 剥离 ?v=xxx 等查询参数，避免干扰文件路径解析
                    parsed = urlparse(self.path)
                    self.path = parsed.path
                    local_path = "." + self.path
                    
                    # 纯读取模式：如果本地不存在该图片，直接静默返回404，不执行任何下载
                    if not os.path.exists(local_path) or not os.path.isfile(local_path):
                        self.send_response(404)
                        self.end_headers()
                        return
                        
                    # 如果本地有该图片，则正常返回给前端地图
                    try:
                        super().do_GET()
                    except ConnectionAbortedError:
                        pass # 屏蔽拖动地图时浏览器主动断开连接引发的报错

            handler = partial(QuietCORSRequestHandler, directory=self.tile_dir)
            self.httpd = socketserver.TCPServer(("", self.port), handler)
            print(f"🚀 纯离线双层地图服务已启动: http://127.0.0.1:{self.port} (仅读取本地 15-18 层切片)")
            self.httpd.serve_forever()
            
        except Exception as e:
            print(f"❌ 切片服务器启动失败: {e}")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
