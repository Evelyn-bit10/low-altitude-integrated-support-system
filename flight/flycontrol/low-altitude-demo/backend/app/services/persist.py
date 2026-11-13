# -*- coding: utf-8 -*-
"""航迹状态快照：定期落盘 + 启动恢复。

为什么需要
----------
现在的航迹状态全在内存里，服务一重启（或崩溃）就全丢，客户端看到的是"目标突然消失"。
真实部署必须有这个；演示环境也能少一次"重启后要重新灌数据"。

实现
----
* 每 N 秒（默认 5s）把可见航迹写成一个 JSON 快照，原子替换（先写 .tmp 再 rename）
* 启动时（可选）读回快照，重建航迹与卡尔曼状态
* 只保存恢复所需的最小字段，文件不会无限增长
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def snapshot_tracks(engine) -> List[Dict[str, Any]]:
    out = []
    for t in engine.tracks.values():
        row = {
            "global_id": t.global_id, "ua_id": t.ua_id, "reg_no": t.reg_no,
            "lat": t.lat, "lon": t.lon, "alt_msl": t.alt_msl,
            "speed": t.speed, "heading": t.heading,
            "confidence": t.confidence, "status": t.status,
            "hits": t.hits, "miss": t.miss,
            "first_seen": t.first_seen, "last_seen": t.last_seen,
            "lat0": t.lat0, "lon0": t.lon0, "err_sigma": t.err_sigma,
            "sources": {
                src: {"local_id": so.local_id, "lat": so.lat, "lon": so.lon,
                      "alt_msl": so.alt_msl, "speed": so.speed, "heading": so.heading,
                      "ts": so.ts, "quality": so.quality, "sigma": so.sigma}
                for src, so in t.sources.items()
            },
        }
        if t.kf is not None:
            row["kf"] = {"px": t.kf.px, "py": t.kf.py, "vx": t.kf.vx, "vy": t.kf.vy,
                         "P": [[round(v, 6) for v in r] for r in t.kf.P],
                         "steps": t.kf.steps}
        out.append(row)
    return out


def save(path: str, engine, extra: Optional[dict] = None) -> bool:
    try:
        data = {"saved_at": time.time(), "tracks": snapshot_tracks(engine)}
        if extra:
            data.update(extra)
        d = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)      # 原子替换，避免读到半个文件
        return True
    except Exception as exc:       # 快照失败绝不能影响主流程
        log.warning("写航迹快照失败: %s", exc)
        return False


def load(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("读航迹快照失败: %s", exc)
        return None


def restore(engine, snap: dict) -> int:
    """把快照里的航迹塞回引擎（超过 TTL 的直接丢弃）。"""
    from app.services.dedup import _SourceObs, GlobalTrack
    from app.services.kalman import KalmanCV

    now = time.time()
    n = 0
    for row in snap.get("tracks", []):
        if now - float(row.get("last_seen", 0)) > engine.ttl:
            continue
        t = GlobalTrack(
            global_id=row["global_id"], ua_id=row.get("ua_id"), reg_no=row.get("reg_no"),
            lat=row["lat"], lon=row["lon"], alt_msl=row.get("alt_msl", 0.0),
            speed=row.get("speed", 0.0), heading=row.get("heading", 0.0),
            confidence=row.get("confidence", 0.5), status=row.get("status", "CONFIRMED"),
            hits=int(row.get("hits", 1)), miss=int(row.get("miss", 0)),
            first_seen=row.get("first_seen", now), last_seen=row.get("last_seen", now),
            lat0=row.get("lat0", row["lat"]), lon0=row.get("lon0", row["lon"]),
            err_sigma=row.get("err_sigma", 0.0),
        )
        for src, so in (row.get("sources") or {}).items():
            t.sources[src] = _SourceObs(so["local_id"], so["lat"], so["lon"],
                                        so.get("alt_msl", 0.0), so.get("speed", 0.0),
                                        so.get("heading", 0.0), so.get("ts", now),
                                        so.get("quality", 0.6), so.get("sigma", 20.0))
        kf = row.get("kf")
        if kf:
            k = KalmanCV(kf["px"], kf["py"])
            k.vx, k.vy = kf.get("vx", 0.0), kf.get("vy", 0.0)
            k.P = [list(r) for r in kf.get("P", k.P)]
            k.steps = int(kf.get("steps", 0))
            t.kf = k
        engine.tracks[t.global_id] = t
        if t.ua_id:
            engine.by_ua[t.ua_id] = t.global_id
        if t.reg_no:
            engine.by_reg[t.reg_no] = t.global_id
        n += 1
    return n
