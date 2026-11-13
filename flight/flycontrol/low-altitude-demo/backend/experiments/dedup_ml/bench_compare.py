# -*- coding: utf-8 -*-
"""改进前 vs 改进后：同一批仿真数据上的对比。

运行：
    python experiments\dedup_ml\bench_compare.py
"""
from __future__ import annotations
import os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

import sim
from app.services.dedup import DedupEngine, Observation
from _dedup_legacy import DedupEngine as LegacyEngine, Observation as LegacyObs

LAT0, LON0, K = 30.0, 120.0, 111320 * 0.866


def feed(eng, frames, legacy=False, ts_shift=None):
    t0 = time.perf_counter()
    counts = []
    for fr in frames:
        obs = []
        for o in fr["obs"]:
            ts = fr["t"] + (ts_shift or {}).get(o.src, 0.0)
            lat, lon = LAT0 + o.y / 111320.0, LON0 + o.x / K
            if legacy:
                obs.append(LegacyObs(track_id="%s-%d" % (o.src, o.truth), source=o.src, ts=ts,
                                     lat=lat, lon=lon, alt_msl=o.z, speed=o.speed,
                                     heading=o.heading, ua_id=o.ua_id, reg_no=o.reg_no))
            else:
                obs.append(Observation(track_id="%s-%d" % (o.src, o.truth), source=o.src, ts=ts,
                                       lat=lat, lon=lon, alt_msl=o.z, speed=o.speed,
                                       heading=o.heading, ua_id=o.ua_id, reg_no=o.reg_no,
                                       sigma=o.sigma))
        res = eng.ingest(obs, now=fr["t"])
        counts.append(len(res.tracks))
    ms = (time.perf_counter() - t0) / max(1, len(frames)) * 1000
    return sum(counts) / len(counts), ms


def main():
    print("=" * 82)
    print(" 改进前 vs 改进后（输出条数应等于真值 12；越接近越好）")
    print("=" * 82)
    print("%-26s %-16s %-16s" % ("场景", "改进前", "改进后"))
    print("-" * 82)

    cases = [
        ("稀疏", "sparse", "easy", 12, None),
        ("编队", "formation", "easy", 12, None),
        ("困难密集", "hard_dense", "hard", 12, None),
        ("极端密集", "extreme_dense", "extreme", 12, None),
        ("困难 + B 慢 3 秒", "hard_dense", "hard", 12, {"B-RID": -3.0}),
        ("困难 + B 快 3 秒", "hard_dense", "hard", 12, {"B-RID": +3.0}),
        ("500 架（稀疏）", "sparse", "easy", 500, None),
    ]
    for name, sc, lvl, n, shift in cases:
        frames = sim.generate(sc, n_planes=n, frames=40 if n > 100 else 60,
                              seed=31, level=lvl)
        a, ta = feed(LegacyEngine(), frames, legacy=True, ts_shift=shift)
        b, tb = feed(DedupEngine(node_id="N"), frames, ts_shift=shift)
        print("%-26s %6.1f 条 %5.1fms   %6.1f 条 %5.1fms" % (name, a, ta, b, tb))


if __name__ == "__main__":
    main()
