# -*- coding: utf-8 -*-
"""去重演示：10 条观测 -> 7 条唯一航迹。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    python tools\\demo_dedup.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.dedup import DedupEngine, Observation, distance_m  # noqa: E402

BASE_LAT, BASE_LON = 30.0, 120.0
T = 1000.0


def obs(source, tid, ts, dlat, dlon, alt=120.0, spd=12.0, hdg=45.0,
        ua=None, reg=None, q=0.8):
    return Observation(track_id=tid, source=source, ts=ts,
                       lat=BASE_LAT + dlat, lon=BASE_LON + dlon,
                       alt_msl=alt, speed=spd, heading=hdg,
                       ua_id=ua, reg_no=reg, quality=q)


def main() -> int:
    engine = DedupEngine(node_id="NODE-A")
    checks = []

    # ---------------------------------------------------------- 一、主场景
    frame = [
        # A 设备看到的 5 架
        obs("A-RID", "7A21", T, 0.0000, 0.0000, ua="1581F-0001"),
        obs("A-RID", "7A22", T, 0.0010, 0.0040, ua="1581F-0002"),
        obs("A-RID", "7A23", T, 0.0030, 0.0060, ua="1581F-0003"),
        obs("A-RID", "7A24", T, 0.0005, 0.0005, ua="1581F-0101"),
        obs("A-RID", "7A25", T, 0.0060, 0.0020, ua="1581F-0102"),
        # B 设备看到的 5 架（3 架共有，其中 1 架丢了 ua_id）
        obs("B-RID", "8B01", T, 0.00005, 0.00005, ua="1581F-0001", q=0.7),
        obs("B-RID", "8B02", T, 0.00108, 0.00406, ua=None, q=0.6),
        obs("B-RID", "8B03", T, 0.00304, 0.00603, ua="1581F-0003", q=0.7),
        obs("B-RID", "8B04", T, 0.00060, 0.00060, ua="1581F-0201", q=0.7),
        obs("B-RID", "8B05", T, 0.00700, 0.00300, ua="1581F-0202", q=0.7),
    ]

    res = engine.ingest(frame, now=T)

    print("=" * 96)
    print("一、输入：两个设备各自看到的航迹（共 %d 条）" % len(frame))
    print("=" * 96)
    print("%-8s %-8s %-14s %-22s %s" % ("来源", "本地ID", "ua_id", "位置(相对起降点)", "说明"))
    print("-" * 96)
    for o in frame:
        note = "共有目标" if (o.ua_id or "").startswith("1581F-000") else "独有目标"
        if o.source == "B-RID" and o.ua_id is None:
            note = "共有但丢 ID"
        print("%-8s %-8s %-14s (%7.1f,%7.1f) m      %s" % (
            o.source, o.track_id, o.ua_id or "—",
            (o.lat - BASE_LAT) * 111320,
            (o.lon - BASE_LON) * 111320 * 0.866, note))

    print()
    print("=" * 96)
    print("二、输出去重后的唯一航迹（共 %d 条）" % len(res.tracks))
    print("=" * 96)
    print("%-16s %-14s %-22s %-8s %s" % ("global_id", "ua_id", "来源", "置信度", "状态"))
    print("-" * 96)
    for t in res.tracks:
        print("%-16s %-14s %-22s %-8.2f %s" % (
            t.global_id, t.ua_id or "—", "+".join(t.source_names),
            t.confidence, t.status))

    s = res.stats
    print()
    print("统计：输入 %d 条 → 输出 %d 条（新建 %d，命中已有 %d，重复报文 %d）"
          % (s["input"], s["unique"], s["created"], s["matched"], s["duplicate"]))

    merged = [t for t in res.tracks if len(t.sources) > 1]
    print("其中多源融合 %d 条：" % len(merged))
    for t in merged:
        print("   %s ← %s" % (t.global_id, ", ".join(
            "%s:%s" % (k, v.local_id) for k, v in t.sources.items())))

    checks.append(("主场景 10 进 7 出", s["input"] == 10 and s["unique"] == 7))
    checks.append(("3 架共有目标被合并", len(merged) == 3))
    checks.append(("丢 ID 的目标靠几何合并",
                   any(t.ua_id == "1581F-0002" and len(t.sources) == 2 for t in res.tracks)))

    # ---------------------------------------------------------- 二、反例：ID 不同
    print()
    print("=" * 96)
    print("三、反例：两架不同无人机相距仅 13 m（交叉飞行）—— 不能合并")
    print("=" * 96)
    eng2 = DedupEngine(node_id="NODE-A")
    close = [
        obs("A-RID", "A1", T, 0.0000, 0.0000, ua="1581F-1001"),
        obs("B-RID", "B1", T, 0.00012, 0.00012, ua="1581F-1002"),
    ]
    r2 = eng2.ingest(close, now=T)
    d = distance_m(close[0].lat, close[0].lon, close[1].lat, close[1].lon)
    print("两架间距 %.1f m，输出 %d 条：%s" % (
        d, len(r2.tracks), [t.ua_id for t in r2.tracks]))
    checks.append(("ID 冲突时绝不合并", len(r2.tracks) == 2))

    # ---------------------------------------------------------- 三、断点续跟
    print()
    print("=" * 96)
    print("四、目标消失 8 秒后重新出现 —— 应仍是同一条航迹（TTL=15s）")
    print("=" * 96)
    eng3 = DedupEngine(node_id="NODE-A")
    eng3.ingest([obs("A-RID", "T1", T, 0.0, 0.0, ua="1581F-2001")], now=T)
    eng3.ingest([obs("A-RID", "T1", T + 1, 0.0001, 0.0, ua="1581F-2001")], now=T + 1)
    gid_before = eng3.tracks[eng3.by_ua["1581F-2001"]].global_id
    # 8 秒无该目标观测，但有别的目标在推进时间
    for k in range(2, 10):
        eng3.ingest([obs("A-RID", "OTHER", T + k, 0.02, 0.02, ua="1581F-2999")], now=T + k)
    r3 = eng3.ingest([obs("A-RID", "T1", T + 10, 0.0010, 0.0, ua="1581F-2001")], now=T + 10)
    target = [t for t in r3.tracks if t.ua_id == "1581F-2001"]
    print("重现后该目标航迹数：%d，global_id 是否不变：%s"
          % (len(target), target and target[0].global_id == gid_before))
    checks.append(("消失又出现不产生重复", len(target) == 1 and target[0].global_id == gid_before))

    # ---------------------------------------------------------- 四、报文幂等
    print()
    print("=" * 96)
    print("五、同一条广播被重复转发 —— 只处理一次")
    print("=" * 96)
    eng4 = DedupEngine(node_id="NODE-A")
    one = obs("A-RID", "X1", T, 0.0, 0.0, ua="1581F-3001")
    r4 = eng4.ingest([one, one], now=T)
    print("输入 2 条相同报文 → 唯一航迹 %d 条，重复丢弃 %d 条"
          % (r4.stats["unique"], r4.stats["duplicate"]))
    checks.append(("重复报文幂等", r4.stats["unique"] == 1 and r4.stats["duplicate"] == 1))

    # ---------------------------------------------------------- 汇总
    print()
    print("=" * 96)
    ok = True
    for name, passed in checks:
        print("  %s  %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("=" * 96)
    print("全部通过 ✅" if ok else "存在失败项 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
