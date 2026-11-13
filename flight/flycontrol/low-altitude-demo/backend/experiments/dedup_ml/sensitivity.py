# -*- coding: utf-8 -*-
"""参数敏感度分析：哪一个参数对去重结果影响最大？

做法：固定场景与数据，只改一个参数，看误配率/漏配率怎么变。

运行：
    python experiments\\dedup_ml\\sensitivity.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sim  # noqa: E402


def angle_diff(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def rule_match(frames, sigma_scale=1.0, k=3.0, alt_gate=30.0, hdg_gate=30.0,
               dt_offset=0.0, v_max=30.0):
    """可调参数的规则匹配器（结构同 dedup.py）。"""
    correct = wrong = missed = 0
    for fr in frames:
        t, obs, tracks = fr["t"], fr["obs"], fr["tracks"]
        edges = []
        for oi, o in enumerate(obs):
            for ti, tr in enumerate(tracks):
                if o.ua_id and tr.ua_id and o.ua_id != tr.ua_id:
                    continue
                if o.reg_no and tr.reg_no and o.reg_no != tr.reg_no:
                    continue
                dt = max(0.0, t - tr.last_t + dt_offset)
                gate = v_max * dt + k * (o.sigma * sigma_scale)
                d = math.hypot(o.x - tr.x, o.y - tr.y)
                if d > gate:
                    continue
                if abs(o.z - tr.z) > alt_gate:
                    continue
                if min(o.speed, tr.speed) >= 2.0 and angle_diff(o.heading, tr.heading) > hdg_gate:
                    continue
                edges.append((1.0 - d / max(gate, 1e-6), oi, ti))
        edges.sort(reverse=True)
        used_o, used_t = set(), set()
        for _, oi, ti in edges:
            key = (obs[oi].src, ti)
            if oi in used_o or key in used_t:
                continue
            used_o.add(oi); used_t.add(key)
            if obs[oi].truth == tracks[ti].truth:
                correct += 1
            else:
                wrong += 1
        missed += len(obs) - len(used_o)
    total = correct + wrong + missed
    return wrong / max(1, total), missed / max(1, total)


def main() -> int:
    print("=" * 84)
    print(" 参数敏感度：只改一个参数，看误配率 / 漏配率")
    print("=" * 84)

    frames = sim.generate("hard_dense", n_planes=12, frames=80, seed=31, level="hard")
    print("场景：hard_dense（12 架 / 大噪声 / B 有系统偏差），%d 帧\n" % len(frames))

    base_w, base_m = rule_match(frames)
    print("基线（σ×1.0, k=3, 高差30, 航向30, 时钟无偏差）：误配 %.2f%% / 漏配 %.2f%%\n"
          % (base_w * 100, base_m * 100))

    cases = [
        ("σ ×0.5（更相信观测）", dict(sigma_scale=0.5)),
        ("σ ×2", dict(sigma_scale=2.0)),
        ("σ ×4", dict(sigma_scale=4.0)),
        ("σ ×8", dict(sigma_scale=8.0)),
        ("k=2（门限收紧）", dict(k=2.0)),
        ("k=4（门限放宽）", dict(k=4.0)),
        ("高差门限 15 m", dict(alt_gate=15.0)),
        ("高差门限 60 m", dict(alt_gate=60.0)),
        ("航向门限 15°", dict(hdg_gate=15.0)),
        ("航向门限 60°", dict(hdg_gate=60.0)),
        ("时钟慢 1 s（Δt 偏大）", dict(dt_offset=1.0)),
        ("时钟快 1 s（Δt 偏小）", dict(dt_offset=-1.0)),
        ("时钟偏差 3 s", dict(dt_offset=3.0)),
        ("v_max 20（低估速度）", dict(v_max=20.0)),
        ("v_max 50（高估速度）", dict(v_max=50.0)),
    ]

    rows = []
    for name, kw in cases:
        w, m = rule_match(frames, **kw)
        rows.append((name, w, m, abs(w - base_w) + abs(m - base_m)))

    print("%-26s %10s %10s %12s" % ("改动", "误配率", "漏配率", "总变化"))
    print("-" * 84)
    for name, w, m, delta in rows:
        print("%-26s %9.2f%% %9.2f%% %11.2f%%" % (name, w * 100, m * 100, delta * 100))

    rows.sort(key=lambda r: -r[3])
    print("\n影响从大到小：")
    for i, (name, w, m, delta) in enumerate(rows[:6], 1):
        print("  %d. %-24s 误配 %5.2f%%  漏配 %5.2f%%" % (i, name, w * 100, m * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
