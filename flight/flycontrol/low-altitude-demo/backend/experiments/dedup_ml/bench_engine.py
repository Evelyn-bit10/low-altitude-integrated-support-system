# -*- coding: utf-8 -*-
"""用真实引擎跑仿真数据：验证时间对齐、全局分配、网格索引的效果。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    python experiments\\dedup_ml\\bench_engine.py
"""

from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                   # sim.py
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))  # backend/

import sim  # noqa: E402
from app.services.dedup import DedupEngine, Observation  # noqa: E402

LAT0, LON0 = 30.0, 120.0
K_LON = 111320.0 * 0.866


def to_obs(o, ts_shift=0.0) -> Observation:
    return Observation(
        track_id="%s-%d" % (o.src, o.truth),
        source=o.src,
        ts=o.truth * 0 + ts_shift,          # 占位，下面覆盖
        lat=LAT0 + o.y / 111320.0,
        lon=LON0 + o.x / K_LON,
        alt_msl=o.z,
        speed=o.speed,
        heading=o.heading,
        ua_id=o.ua_id,
        reg_no=o.reg_no,
        sigma=o.sigma,
    )


def run(scenario, level, frames=80, seed=31, n_planes=12, ts_shift=None):
    data = sim.generate(scenario, n_planes=n_planes, frames=frames, seed=seed, level=level)
    _src = sim.LEVELS[level]
    sigmas = {_src[0].name: _src[0].sigma, _src[1].name: _src[1].sigma}
    eng = DedupEngine(node_id="BENCH", gate_k=3.44, source_sigmas=sigmas,
                      default_sigma=20.0, ttl=15.0)

    t0 = time.perf_counter()
    counts = []
    mixed_max = 0
    for fr in data:
        obs = []
        for o in fr["obs"]:
            ob = to_obs(o)
            ob.ts = fr["t"] + (ts_shift or {}).get(o.src, 0.0)
            obs.append(ob)
        res = eng.ingest(obs, now=fr["t"])
        counts.append(len(res.tracks))
        # 误配：同一条航迹里出现了两个不同真值来源
        mixed = 0
        for tr in eng.tracks.values():
            truths = set()
            for s_ in tr.sources.values():
                try:
                    truths.add(int(str(s_.local_id).rsplit("-", 1)[-1]))
                except Exception:
                    pass
            if len(truths) > 1:
                mixed += 1
        mixed_max = max(mixed_max, mixed)
    dt = (time.perf_counter() - t0) / max(1, len(data))

    n_truth = n_planes
    avg = sum(counts) / len(counts)
    print("  %-24s 输出 %5.1f / 真值 %-3d 误配航迹 %-2d 单帧 %5.2f ms  时钟 %s"
          % (scenario + "(" + level + ")", avg, n_truth, mixed_max, dt * 1000,
             {k: round(v, 1) for k, v in eng.clock_offset.items()} or "—"))
    return avg, n_truth, dt


def main() -> int:
    print("=" * 78)
    print(" 引擎基准：输出航迹数 vs 真值架数（理想值 = 真值）")
    print("=" * 78)

    print("\n[1] 常规 / 困难 / 极端场景")
    run("sparse", "easy")
    run("formation", "easy")
    run("hard_dense", "hard")
    run("extreme_dense", "extreme")

    print("\n[3] 纯几何（两个源都不带 ID）")
    run("sparse", "noid")
    run("dense", "noid")
    run("swarm", "noid")

    print("\n[2] 时钟偏差（B 设备慢 1 秒 / 3 秒）")
    run("hard_dense", "hard", ts_shift={"B-RID": -1.0})
    run("hard_dense", "hard", ts_shift={"B-RID": -3.0})

    print("\n[3] 规模与耗时（稀疏场景，目标数递增）")
    for n in (12, 50, 200, 500):
        run("sparse", "easy", frames=25, n_planes=n)

    print("\n说明：")
    print("  - 输出条数 > 真值 = 同一架被拆成多条（漏配）")
    print("  - 输出条数 < 真值 = 两架被并成一条（误配）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
