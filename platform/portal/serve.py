# -*- coding: utf-8 -*-
"""静态文件服务（开发 / 演示用）：强制 no-store，改完前端代码刷新即生效。

为什么不用 `python -m http.server`
--------------------------------
    SimpleHTTPRequestHandler 不发送 Cache-Control，浏览器会按启发式规则缓存
    HTML / JS / CSS，导致「代码改了但页面没变」，必须 Ctrl+F5 强刷。
    这里统一加上 no-store / no-cache，普通刷新就能拿到最新文件。

用法
----
    python serve.py 5500 --host 0.0.0.0
    python serve.py 5502 --host 0.0.0.0 --dir ..\\..\\pilot-app\\flyer-app

参数
----
    port          监听端口
    --host        绑定地址，默认 0.0.0.0（手机同 Wi-Fi 可访问）
    --dir         站点根目录，默认当前目录
"""
from __future__ import annotations

import argparse
import functools
import http.server
import pathlib


class NoStoreHandler(http.server.SimpleHTTPRequestHandler):
    """静态文件 + 强制不缓存。"""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        """静默日志：避免每次刷新都刷屏（需要排障时临时注释掉）。"""
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="no-store static file server")
    parser.add_argument("port", type=int)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--dir", default=".")
    args = parser.parse_args()

    root = pathlib.Path(args.dir).resolve()
    if not root.is_dir():
        raise SystemExit("目录不存在: %s" % root)

    handler = functools.partial(NoStoreHandler, directory=str(root))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print("serving %s at http://%s:%d (no-store)" % (root, args.host, args.port))
        httpd.serve_forever()


if __name__ == "__main__":
    main()
