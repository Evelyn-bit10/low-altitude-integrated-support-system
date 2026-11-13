# -*- coding: utf-8 -*-
"""双设备态势模拟器：演示「同一架无人机被两个设备看到 → 只输出一条」。

用法：
    # 先启动后端（默认 8080）
    python tools/sim_two_devices.py                 # 持续 60 秒，每秒一帧
    python tools/sim_two_devices.py --frames 10     # 跑 10 帧
    python tools/sim_two_devices.py --url http://192.168.1.20:8080

场景：
    UA-1/2/3  两个设备都能看到（其中 UA-2 在 B 设备侧丢失 ua_id，靠几何判定）
    UA-4/5    只有 A 设备能看到
    UA-6/7    只有 B 设备能看到
    → 每帧上报 10 条，去重后应只剩 7 条
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request

LAT0, LON0 = 30.0, 120.0
MPD_LAT = 111320.0
MPD_LON = 111320.0 * math.cos(math.radians(LAT0))


def to_latlon(east: float, north: float):
    return LAT0 + north / MPD_LAT, LON0 + east / MPD_LON


def make(tid, source, ua, east, north, ts, *, heading=45.0, speed=12.0,
         phase="CRUISE", battery=82, with_ua=True):
    lat, lon = to_latlon(east, north)
    rec = {
        "id": tid, "source_node": source, "ts": ts,
        "lat": round(lat, 7), "lon": round(lon, 7), "alt_msl": 120.0,
        "speed": speed, "heading": heading, "vertical_speed": 0.0,
        "battery_pct": battery, "link_quality": 4,
        "emergency": False, "rid_lost": False,
        "model": "EV-200", "reg_no": "REG-" + ua, "phase": phase,
    }
    if with_ua:
        rec["ua_id"] = ua
    return rec


def build_frame(t: float):
    """第 t 秒的一帧：10 条观测（两个设备各 5 条）。"""
    ts = time.time()
    east = 12.0 * t          # 整体缓慢向东移动
    north = 6.0 * t
    frame = []

    # ---- 设备 A ----
    for i, ua in enumerate(("UA-0001", "UA-0002", "UA-0003")):
        frame.append(make("A-%s" % ua[-1], "A-RID", ua,
                          east + i * 60, north + i * 25, ts, battery=82 - i))
    frame.append(make("A-U4", "A-RID", "UA-0004", east + 240, north - 40, ts, phase="APPROACH"))
    frame.append(make("A-U5", "A-RID", "UA-0005", east + 320, north + 90, ts, phase="DEPARTURE"))

    # ---- 设备 B（坐标略有偏差；UA-0002 丢了 ua_id） ----
    for i, ua in enumerate(("UA-0001", "UA-0002", "UA-0003")):
        frame.append(make("B-%s" % ua[-1], "B-RID", ua,
                          east + i * 60 + 6, north + i * 25 - 4, ts,
                          battery=78 - i, with_ua=(ua != "UA-0002")))
    frame.append(make("B-U6", "B-RID", "UA-0006", east - 120, north + 150, ts, phase="HOVER", speed=0.5))
    frame.append(make("B-U7", "B-RID", "UA-0007", east + 60, north - 130, ts, phase="CRUISE"))
    return frame


def post(url: str, payload, timeout: float = 5.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url + "/api/traffic/ingest", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def get(url: str, path: str, timeout: float = 5.0):
    with urllib.request.urlopen(url + path, timeout=timeout) as resp:
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser(description="双设备态势模拟器")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--interval", type=float, default=1.0, help="上报周期（秒）")
    ap.add_argument("--frames", type=int, default=60, help="总帧数（0=一直跑）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    url = args.url.rstrip("/")

    print("=" * 78)
    print(" 双设备模拟：A-RID / B-RID 各上报 5 条，期望去重后 7 条")
    print(" 后端：%s    周期：%.1fs" % (url, args.interval))
    print("=" * 78)

    k = 0
    try:
        while args.frames <= 0 or k < args.frames:
            frame = build_frame(k * args.interval)
            # 第 5 帧故意重复发一条（演示报文幂等）
            if k == 5:
                frame.append(dict(frame[0]))

            res = post(url, frame)
            if not args.quiet:
                st = get(url, "/api/traffic/stats")
                print("  t=%3ds  上报 %2d 条 → 唯一 %d 条（融合 %d，待确认 %d）  来源：%s"
                      % (k, res.get("received", 0), res.get("stored", 0),
                         res.get("merged", 0), st.get("tentative", 0),
                         ", ".join("%s=%d" % (s["source"], s["tracks"])
                                   for s in st.get("sources", []))))
            k += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止。")
    except urllib.error.URLError as exc:
        print("\n[错误] 连接后端失败：%s" % exc)
        print("       请先启动：uvicorn app.main:app --port 8080")
        return 1

    st = get(url, "/api/traffic/stats")
    print("-" * 78)
    print(" 最终：原始 %d 条 → 唯一 %d 条，其中多源融合 %d 条"
          % (st.get("input", 0), st.get("unique_now", 0), st.get("merged_now", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
