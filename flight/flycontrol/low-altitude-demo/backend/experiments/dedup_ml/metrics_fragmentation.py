# -*- coding: utf-8 -*-
"""更严格的漏配/误配度量：按真值身份统计「航迹碎片」。

之前的 48% 是 (平均输出条数 − 真值数)/真值数，只是代理指标。
这里直接统计：
  - 每个真值（同一架飞机）在整个回放中被拆成了几条航迹 → 碎片数
  - 被拆过的真值占比（严格漏配率）
  - 混入两条以上真值的航迹数（误配）

运行：
    python experiments/dedup_ml/metrics_fragmentation.py
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

import sim
from app.services.dedup import DedupEngine, Observation
from _dedup_legacy import DedupEngine as LegacyEngine, Observation as LegacyObs

LAT0, LON0, K = 30.0, 120.0, 111320 * 0.866


def run(eng, frames, legacy=False):
    truth_tracks = defaultdict(set)   # 真值 -> 见过的 global_id
    mixed_tracks = set()              # 含多个真值的 global_id
    for fr in frames:
        obs = []
        for o in fr["obs"]:
            lat, lon = LAT0 + o.y / 111320.0, LON0 + o.x / K
            cls = LegacyObs if legacy else Observation
            kw = dict(track_id="%s-%d" % (o.src, o.truth), source=o.src, ts=fr["t"],
                      lat=lat, lon=lon, alt_msl=o.z, speed=o.speed, heading=o.heading,
                      ua_id=o.ua_id, reg_no=o.reg_no)
            if not legacy:
                kw["sigma"] = o.sigma
            obs.append(cls(**kw))
        eng.ingest(obs, now=fr["t"])

        for gid, tr in eng.tracks.items():
            truths = set()
            for s_ in tr.sources.values():
                try:
                    truths.add(int(str(s_.local_id).rsplit("-", 1)[-1]))
                except Exception:
                    pass
            for t_ in truths:
                truth_tracks[t_].add(gid)
            if len(truths) > 1:
                mixed_tracks.add(gid)
    return truth_tracks, mixed_tracks


def report(tag, frames, legacy):
    eng = LegacyEngine() if legacy else DedupEngine(node_id="N")
    tt, mixed = run(eng, frames, legacy=legacy)
    frags = [len(v) for v in tt.values()]
    split = sum(1 for f in frags if f > 1)
    n = max(1, len(frags))
    print("  %-18s 真值 %2d  平均碎片 %.2f 条  被拆过 %2d 架（%.0f%%）  误配航迹 %d"
          % (tag, len(frags), sum(frags) / n, split, split / n * 100, len(mixed)))
    return sum(frags) / n, split / n


def main():
    print("=" * 96)
    print(" 严格指标：按真值统计航迹碎片（场景：纯几何 noid，12 架，60 帧）")
    print("=" * 96)
    for scn in ("sparse", "dense"):
        frames = sim.generate(scn, n_planes=12, frames=60, seed=31, level="noid")
        report(scn + " 改进前", frames, True)
        report(scn + " 改进后", frames, False)
        print()


if __name__ == "__main__":
    main()
