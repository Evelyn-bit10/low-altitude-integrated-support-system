# -*- coding: utf-8 -*-
"""网页冒烟测试：用无头浏览器把演示台/实验室打开一遍。

为什么要它
----------
两个页面都是几千行的单文件 HTML，之前几次改动（融合点、门限、19 维特征）
都出现过"页面能打开但 JS 报错 / 内存数据变了但前端没同步"的问题，
靠人眼看截图成本太高，也容易漏。

检查三项：
    ① 控制台不能有 Uncaught / TypeError / SyntaxError；
    ② 截图必须生成，且体积正常（JS 崩掉时页面几乎是纯色，文件很小）。

注：这台机器上的 Edge 无头模式 `--dump-dom` 返回空，所以不做 DOM 文本断言，
    内容正确性交给后端的接口测试覆盖。

用法：
    python tools/smoke_web.py                # 默认 http://127.0.0.1:8082
    python tools/smoke_web.py --port 8081
"""
from __future__ import annotations

EDGE_PATHS = [r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
              r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
              r"C:/Program Files/Google/Chrome/Application/chrome.exe"]


def shot(url, out, w=1500, h=1000, budget=12000):
    """用 Edge/Chrome 无头模式截图（返回文件路径；失败返回 None）"""
    import subprocess, os, time
    exe = next((p for p in EDGE_PATHS if os.path.exists(p)), None)
    if not exe:
        print("未找到 Edge/Chrome")
        return None


import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Tuple

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_BACKEND))))
PORTAL = os.path.join(_ROOT, "platform", "portal")

# ---------------------------------------------------------------- 静态检查
# 踩过的坑：top-level 的 $('#xxx') 如果引用了 HTML 里不存在的 id，
# JS 会静默中断，后面所有初始化（URL 参数、定时器）全部不执行——
# 页面看起来"渲染正常"，实际是死的。这里在跑浏览器之前先做静态比对。

def check_js(path):
    """用 node --check 校验页面内联脚本语法（语法错会导致整页空白）"""
    import re, subprocess, tempfile, os, shutil
    node = shutil.which("node") or r"G:/Node/node"
    if not os.path.exists(node):
        return []
    s = open(path, encoding="utf-8").read()
    errs = []
    for i, b in enumerate(re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", s, re.S)):
        t = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
        t.write(b); t.close()
        r = subprocess.run([node, "--check", t.name], capture_output=True, text=True)
        os.unlink(t.name)
        if r.returncode != 0:
            errs.append("script%d: %s" % (i + 1, r.stderr.strip().splitlines()[-1][:100]))
    return errs


def check_ids(path: str) -> list:
    """返回 HTML 里被 JS 引用、但实际不存在的 id 列表。"""
    import re
    try:
        s = open(path, encoding="utf-8").read()
    except OSError:
        return []
    ids = set(re.findall(r'id="([^"]+)"', s))
    if "<script>" not in s:
        return []
    script = s[s.index("<script>"):]
    used = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", script))
    return sorted(used - ids)


BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# (页面, 查询串, 期望出现的中文片段)
PAGES: List[Tuple[str, str, List[str]]] = [
    # 注意：这里不放 gen= 参数。"生成程序"要等真实网络请求，而无头浏览器的
    # --virtual-time-budget 只推进虚拟时钟，不等网络 → 截图会随机缺失。
    # 生成链路由后端接口测试覆盖（test_directions_all_available 等）。
    ("demo.html", "?tab=p1&dir=NW", ["复飞"]),
    ("demo.html", "?tab=p2&run=1", ["多设备去重", "去重后"]),
    ("demo.html", "?tab=p3", ["推送"]),
    ("demo.html", "?tab=p4&cmp=1", ["RL 影子模式", "困难密集"]),
    ("rl_lab.html", "", ["判定结果", "策略网络"]),
    # 第一幕新版（独立页面）：雷达图 + 点击放置 + 航道匹配
    ("demo_p1.html", "", ["航道选择", "俯视图"]),
]


def find_browser() -> str | None:
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    return shutil.which("msedge") or shutil.which("chrome")


def run_one(browser: str, page: str, query: str, expect: List[str],
            workdir: str, budget: int, idx: int) -> Tuple[bool, str]:
    url = "file:///" + os.path.join(PORTAL, page).replace("\\", "/") + (query or "")
    shot = os.path.join(workdir, "shot%d.png" % idx)
    profile = os.path.join(workdir, "prof%d" % idx)
    if os.path.exists(shot):
        os.remove(shot)
    cmd = [
        browser, "--headless", "--disable-gpu", "--no-sandbox",
        f"--user-data-dir={profile}",          # 必须独立 profile，否则和已开的浏览器冲突
        "--hide-scrollbars", "--window-size=1400,1000",
        f"--virtual-time-budget={budget}",
        "--enable-logging=stderr", "--log-level=0",
        f"--screenshot={shot}", url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=180)
    log = (proc.stderr or "") + (proc.stdout or "")

    problems = []
    for bad in ("Uncaught", "SyntaxError", "TypeError"):
        if bad in log:
            line = next((l for l in log.splitlines() if bad in l), bad)
            problems.append("控制台异常: " + line.strip()[:160])

    # 截图是异步落盘的，要轮询等待
    size = 0
    for _ in range(30):
        if os.path.exists(shot):
            size = os.path.getsize(shot)
            if size > 0:
                break
        time.sleep(0.5)
    if size == 0:
        problems.append("没有生成截图")
    elif size < 60000:
        problems.append("截图偏小（%d 字节），疑似白屏或渲染失败" % size)

    return (not problems), "; ".join(problems)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=18000, help="页面虚拟运行时间(ms)")
    args = ap.parse_args()

    # ① 静态检查：JS 引用的元素 id 必须真实存在
    print("")
    print("[静态检查] JS 引用的元素 id")
    id_fail = 0
    for page in ("demo.html", "demo_p1.html", "rl_lab.html"):
        miss = check_ids(os.path.join(PORTAL, page))
        if miss:
            print("  [FAIL] %-14s 缺失 id: %s" % (page, ", ".join(miss)))
            id_fail += 1
        else:
            print("  [OK]   %-14s 引用完整" % page)

    browser = find_browser()
    if not browser:
        print("")
        print("找不到 Edge/Chrome，跳过浏览器检查（可用 SMOKE_BROWSER 指定）")
        return 0 if id_fail == 0 else 1
    browser = os.environ.get("SMOKE_BROWSER", browser)
    print("")
    print("浏览器:", browser)

    # ② 浏览器冒烟
    workdir = tempfile.mkdtemp(prefix="smoke-")
    fails = 0
    try:
        for i, (page, query, expect) in enumerate(PAGES):
            # 会触发"生成程序 + 可达性评估 + 气象计算"的用例需要更多虚拟时间
            budget = max(args.budget, 26000) if "gen=" in query else args.budget
            ok, msg = run_one(browser, page, query, expect, workdir, budget, i)
            if not ok:
                time.sleep(1.0)
                ok, msg = run_one(browser, page, query, expect, workdir, budget + 6000, i + 100)
            print(("  [OK]   " if ok else "  [FAIL] ") + page + query + ("" if ok else "  <- " + msg))
            if not ok:
                fails += 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    total = len(PAGES) + 3
    print("")
    print("%d/%d 通过（含 3 项静态检查）" % (total - fails - id_fail, total))
    return 1 if (fails or id_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
