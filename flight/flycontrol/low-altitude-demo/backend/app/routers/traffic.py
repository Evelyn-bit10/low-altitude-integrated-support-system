"""交通态势与统一快照路由(canonical v1.1)。

提供:
  GET  /api/sync/snapshot   -> 统一快照(机场/障碍物/空域/气象/程序/交通, 经纬度+MSL)
  GET  /api/traffic         -> 当前实时飞行器态势(已去重, 一架一条)
  GET  /api/traffic/stats   -> 去重统计(原始条数 / 唯一条数 / 融合条数 ...)
  POST /api/traffic/ingest  -> 接收各设备/节点回传的飞行器态势, 服务端去重后入库

去重规则见 app/services/dedup.py 与 shared/contract.md §3.8。
统一接口规范见 shared/contract.md;适配层见 shared/interface.py（工程根目录下的 shared/：
飞控后端向上逐层查找它，通讯态势前端用相对路径 ../../shared/ 引用）。
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from fastapi import APIRouter, Request

# 让本进程能导入 shared/ 下的统一接口适配层(纯标准库, 无第三方依赖)
# 从本文件所在目录逐层向上查找 shared/interface.py，不再依赖固定的目录层级，
# 这样调整工程目录结构(例如把 flycontrol 移到 flight/ 下)之后依然能找到契约目录。
def _find_shared_dir(start: Path) -> "Path | None":
    for candidate_parent in [start] + list(start.parents):
        candidate = candidate_parent / "shared"
        if (candidate / "interface.py").is_file():
            return candidate
    return None


_SHARED_DIR = _find_shared_dir(Path(__file__).resolve().parent)
if _SHARED_DIR is None:
    raise ImportError("未找到 shared/interface.py —— 统一接口契约目录缺失或位置异常")
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from interface import (  # noqa: E402
    SCHEMA_VERSION,
    canonical_snapshot,
    normalize_traffic_payload,
    normalize_traffic_record,
)

from ..services.dedup import DedupEngine, Observation  # noqa: E402

log = logging.getLogger("lowalt.traffic")
router = APIRouter()

TRAFFIC_TTL_SEC = 6.0     # 未启用去重时的过期时间（兼容旧行为）


def _to_epoch(value, default: float) -> float:
    """把 ts（ISO8601 字符串 / 秒 / 毫秒时间戳）统一成 epoch 秒。"""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:  # noqa: BLE001
        return default


class TrafficStore:
    """交通态势存储 + 去重。

    启用去重时（默认），对外只暴露「一架一条」的全局航迹；
    关闭去重（DEDUP_ENABLED=false）时退化为按 id 覆盖的旧行为，便于对比演示。
    """

    def __init__(self, settings=None):
        self.settings = settings
        self.enabled = bool(getattr(settings, "dedup_enabled", True))
        self.node_id = str(getattr(settings, "node_id", "NODE-A"))

        self.engine: Optional[DedupEngine] = None
        if self.enabled:
            self.engine = self._make_engine()

        # 影子模式：RL 策略跟跑、只记录不生效（DEDUP_SHADOW=1 打开）
        try:
            from app.services.shadow import build_from_env
            self.shadow = build_from_env()
        except Exception as _exc:  # noqa: BLE001  —— 影子不可用绝不能挡住主流程
            log.warning("影子模式加载失败: %s", _exc)
            self.shadow = None

        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.persist_path = os.environ.get(
            "DEDUP_SNAPSHOT", os.path.join(_root, "data", "tracks.json"))

        # 态势历史（缺口二）：去重后的航迹按帧落库，支撑交班摘要与看板
        self.history = None
        self._last_prune = 0.0
        if getattr(settings, "history_enabled", False):
            try:
                from app.services.history import HistoryStore
                self.history = HistoryStore(
                    os.path.join(_root, getattr(settings, "history_db", "data/history.db")),
                    getattr(settings, "history_retention_hours", 24.0),
                )
            except Exception as exc:
                log.warning("历史存储初始化失败: %s", exc)
        self._last_snap = 0.0
        # 启动恢复（DEDUP_RESTORE=1）：把上次的航迹快照装回来，避免重启后目标"集体消失"
        if os.environ.get("DEDUP_RESTORE", "0") == "1" and self.engine is not None:
            try:
                from app.services import persist
                snap = persist.load(self.persist_path) if self.persist_path else None
                if snap:
                    n = persist.restore(self.engine, snap)
                    log.info("已从快照恢复 %d 条航迹", n)
            except Exception as exc:
                log.warning("航迹快照恢复失败: %s", exc)

        self.records: dict = {}      # global_id / id -> canonical 记录（已融合）
        self.updated: dict = {}      # global_id -> epoch 秒
        self.origin = None           # (lat, lon, elevation) 机场，供 ENU 回显
        self.last_stats: dict = {
            "enabled": self.enabled, "node_id": self.node_id,
            "input": 0, "unique": 0, "merged": 0, "tentative": 0,
            "duplicate": 0, "created": 0, "matched": 0, "expired": 0, "split": 0,
            "updated_at": None,
        }

    def _maybe_snapshot(self, now: float) -> None:
        """每 5 秒落一次航迹快照（重启后能恢复，不至于"目标集体消失"）。"""
        if not self.persist_path:
            return
        if now - getattr(self, "_last_snap", 0.0) < 5.0:
            return
        self._last_snap = now
        try:
            from app.services import persist
            persist.save(self.persist_path, self.engine)
        except Exception:
            pass

    def _record_history(self, now: float) -> None:
        """把当前唯一航迹投递到历史队列；每 10 分钟清理一次过期行。"""
        if self.history is None:
            return
        try:
            self.history.record(self.records.values(), now)
            if now - getattr(self, "_last_prune", 0.0) > 600:
                self._last_prune = now
                self.history.prune()
        except Exception:
            pass

    def _make_engine(self) -> DedupEngine:
        st = self.settings
        sigmas = dict(getattr(st, "dedup_source_sigmas", None) or {})
        try:                                   # 设备台账优先覆盖配置
            from app.services.ledger import device_sigmas
            sigmas.update(device_sigmas())
        except Exception:
            pass
        return DedupEngine(
            node_id=self.node_id,
            v_max=float(getattr(st, "dedup_v_max", 30.0)),
            sigma_m=float(getattr(st, "dedup_sigma_m", 15.0)),
            ttl=float(getattr(st, "dedup_ttl", 15.0)),
            gate_k=float(getattr(st, "dedup_gate_k", 3.44)),
            source_sigmas=sigmas,
            default_sigma=float(getattr(st, "dedup_default_sigma", 20.0)),
            sigma_floor=float(getattr(st, "dedup_sigma_floor", 8.0)),
            sigma_autocalib=bool(getattr(st, "dedup_autocalib", True)),
            sigma_calib_samples=int(getattr(st, "dedup_calib_samples", 200)),
            # 分配策略：greedy（默认）/ hungarian（密集场景可选，实测暂无增益）
            assign_mode=str(getattr(st, "dedup_assign_mode", None)
                            or os.environ.get("DEDUP_ASSIGN", "greedy")),
            # 事后回并：把"同一架被拆成多条"合回去（默认开）
            post_merge=bool(getattr(st, "dedup_post_merge", None)
                            if getattr(st, "dedup_post_merge", None) is not None
                            else os.environ.get("DEDUP_POSTMERGE", "1") == "1"),
            # 匀速模型卡尔曼滤波：负责外推与门限（DEDUP_KALMAN=0 可关闭）
            use_kalman=os.environ.get("DEDUP_KALMAN", "1") == "1",
            kf_sigma_a=float(os.environ.get("DEDUP_KF_SIGMA_A", "2.0")),
            # 密度自适应门限：实测 4 个 seed 上收益为零（dense 误配 3.25→3.50），默认关
            density_gate=os.environ.get("DEDUP_DENSITY_GATE", "0") == "1",
        )

    # ------------------------------------------------------------ 基础
    def reset(self) -> dict:
        """清空去重状态（演示重开时用，避免上一轮的旧航迹干扰）。"""
        if self.enabled:
            self.engine = self._make_engine()
        self.records.clear()
        self.updated.clear()
        self.last_stats = {
            "enabled": self.enabled, "node_id": self.node_id,
            "input": 0, "unique": 0, "merged": 0, "tentative": 0,
            "duplicate": 0, "created": 0, "matched": 0, "expired": 0, "split": 0,
            "updated_at": None,
        }
        if self.shadow is not None:
            self.shadow.reset()
        return self.last_stats

    def set_origin(self, airport):
        self.origin = (float(airport.lat), float(airport.lon), float(airport.elevation))

    def snapshot(self, now: float | None = None) -> list:
        """当前对外可见的交通记录（已去重）。"""
        return list(self.records.values())

    # ------------------------------------------------------------ 写入
    def ingest(self, items: Iterable[dict], now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        raw = [r for r in (items or []) if isinstance(r, dict)]
        recs = [normalize_traffic_record(r) for r in raw]

        if not self.enabled:
            stats = self._ingest_legacy(recs, now)
            self._record_history(now)
            return stats

        observations = []
        for r in recs:
            if r.get("id") is None and r.get("ua_id") is None:
                continue
            try:
                observations.append(Observation(
                    track_id=str(r.get("id") or r.get("ua_id")),
                    source=str(r.get("source_node") or "LOCAL"),
                    ts=_to_epoch(r.get("ts"), now),
                    lat=float(r["lat"]), lon=float(r["lon"]),
                    alt_msl=float(r.get("alt_msl", 0.0)),
                    speed=float(r.get("speed", 0.0)),
                    heading=float(r.get("heading", 0.0)),
                    ua_id=(r.get("ua_id") or None),
                    reg_no=(r.get("reg_no") or None),
                    quality=float(r.get("quality", 0.6)),
                    sigma=(float(r["sigma"]) if r.get("sigma") is not None else None),
                    payload=r,
                ))
            except (KeyError, TypeError, ValueError):
                log.warning("忽略非法交通记录: %s", r)

        # ---- 影子模式：先拍快照（策略需要"更新前"的候选集合）----
        shadow_snap = None
        if self.shadow is not None and self.shadow.enabled and observations:
            try:
                from app.services.shadow import snapshot_tracks
                origin = (self.origin[0], self.origin[1]) if self.origin else \
                    (observations[0].lat, observations[0].lon)
                shadow_snap = snapshot_tracks(list(self.engine.tracks.values()), origin)
            except Exception as _exc:  # noqa: BLE001
                log.debug("影子快照失败: %s", _exc)
                shadow_snap = None

        t_start = time.perf_counter()
        res = self.engine.ingest(observations, now)
        try:
            from app.services.metrics import METRICS
            METRICS.observe_frame((time.perf_counter() - t_start) * 1000.0,
                                  res.stats.get("matched", 0) + res.stats.get("created", 0),
                                  res.stats.get("unique", 0),
                                  len(self.engine.tracks), now)
            for k in ("matched", "created", "split", "expired", "duplicate"):
                if res.stats.get(k):
                    METRICS.inc(k, res.stats[k])
        except Exception:
            pass
        self._rebuild(res, now)
        self._maybe_snapshot(now)
        self._record_history(now)

        # ---- 影子模式：规则跑完后再让策略判一次，只写日志 ----
        if shadow_snap is not None:
            try:
                rule_pick = {}
                for tr in self.engine.tracks.values():      # 含 TENTATIVE 航迹
                    for _src, so in tr.sources.items():
                        rule_pick[(_src, so.local_id)] = tr.global_id
                picks = {i: rule_pick.get((o.source, o.track_id))
                         for i, o in enumerate(observations)}
                self.shadow.observe(
                    observations, shadow_snap, origin, now, picks,
                    gate_fn=lambda o, tr: self.engine.gate_and_distance(o, tr, now))
            except Exception as _exc:  # noqa: BLE001
                log.debug("影子比对失败: %s", _exc)

        merged = sum(1 for t in res.tracks if len(t.sources) > 1)
        self.last_stats = {
            "enabled": True,
            "node_id": self.node_id,
            "input": res.stats.get("input", len(observations)),
            "unique": res.stats.get("unique", len(res.tracks)),
            "merged": merged,
            "tentative": res.stats.get("tentative", 0),
            "duplicate": res.stats.get("duplicate", 0),
            "created": res.stats.get("created", 0),
            "matched": res.stats.get("matched", 0),
            "expired": res.stats.get("expired", 0),
            "split": res.stats.get("split", 0),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return self.last_stats

    def _ingest_legacy(self, recs: List[dict], now: float) -> dict:
        """关闭去重时的旧逻辑：按 id 覆盖（保留用于对比演示）。"""
        for r in recs:
            rid = r.get("id")
            if not rid:
                continue
            ts = _to_epoch(r.get("ts"), now)
            if ts <= self.updated.get(rid, 0):
                continue
            self.records[rid] = r
            self.updated[rid] = ts
        # 过期清理
        for rid in [k for k, v in self.updated.items() if now - v > TRAFFIC_TTL_SEC]:
            self.records.pop(rid, None)
            self.updated.pop(rid, None)
        self.last_stats = {
            "enabled": False, "node_id": self.node_id,
            "input": len(recs), "unique": len(self.records), "merged": 0,
            "tentative": 0, "duplicate": 0, "created": len(recs),
            "matched": 0, "expired": 0, "split": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return self.last_stats

    def _rebuild(self, res, now: float) -> None:
        """把去重结果转回 canonical 记录（保留原始业务字段）。"""
        records = {}
        updated = {}
        for t in res.tracks:
            live = sorted(t.sources.items(), key=lambda kv: kv[1].ts, reverse=True)
            # 主源：质量最高（并列时按来源名），保证 callsign/业务字段稳定不跳变
            primary = sorted(t.sources.items(), key=lambda kv: (-kv[1].quality, kv[0]),
                             reverse=False)[0][1] if t.sources else None
            base = dict(primary.payload or {}) if primary else {}
            callsign = (base.get("id") or None)
            base.update({
                "id": t.ua_id or t.reg_no or t.global_id,
                "callsign": callsign,
                "global_id": t.global_id,
                "ua_id": t.ua_id,
                "reg_no": t.reg_no,
                "lat": round(t.lat, 7),
                "lon": round(t.lon, 7),
                "alt_msl": round(t.alt_msl, 1),
                "speed": round(t.speed, 1),
                "heading": round(t.heading, 1),
                "sources": t.source_names,
                "source_ids": t.local_ids,
                "confidence": round(t.confidence, 3),
                "merged": len(t.sources) > 1,
                "ts": live[0][1].payload.get("ts") if live and live[0][1].payload else None,
            })
            if not base.get("ts"):
                base["ts"] = datetime.fromtimestamp(t.last_seen, timezone.utc).isoformat(
                    timespec="seconds")
            records[t.global_id] = base
            updated[t.global_id] = t.last_seen
        self.records = records
        self.updated = updated

    # ------------------------------------------------------------ 统计
    def stats(self) -> dict:
        """当前统计（含按来源分布），供门户"组网协同"面板使用。"""
        by_source: dict = {}
        for rec in self.records.values():
            for s in rec.get("sources", []) or []:
                by_source[s] = by_source.get(s, 0) + 1
        out = dict(self.last_stats)
        out["sources"] = [{"source": k, "tracks": v}
                          for k, v in sorted(by_source.items())]
        if self.engine is not None:
            out["clock_offsets"] = {k: round(v, 2)
                                    for k, v in self.engine.clock_offset.items()}
            out["source_sigmas"] = {k: round(self.engine.sigma_of(k), 1)
                                    for k in (self.engine.source_sigmas or {})}
            out["sigma_scale"] = round(self.engine.sigma_scale, 3)
        out["merged_now"] = sum(1 for r in self.records.values() if r.get("merged"))
        out["unique_now"] = len(self.records)
        if self.shadow is not None:
            out["shadow"] = self.shadow.stats()
        return out


@router.get("/sync/snapshot")
def sync_snapshot(request: Request):
    """统一快照:communication 启动时拉取, 用于对齐环境/程序数据。"""
    store = request.app.state.store
    traffic_store = request.app.state.traffic
    to_latlon = store._to_latlon
    elev = float(store.airport.elevation)

    snap = canonical_snapshot(
        airport=store.airport,
        obstacles=store.obstacles,        # 仅生效中的障碍物
        airspaces=store.airspaces,
        meteo=store.meteo,
        program=store.current_program,
        traffic=[],                        # 交通单独填入(已去重)
        to_latlon=to_latlon,
        elevation=elev,
    )
    snap["traffic"] = traffic_store.snapshot()
    return snap


@router.get("/traffic")
def traffic_list(request: Request):
    """当前实时飞行器态势(canonical v1.1, 已去重: 一架一条)。"""
    return {"traffic": request.app.state.traffic.snapshot()}


@router.get("/traffic/stats")
def traffic_stats(request: Request):
    """去重统计: 原始条数 / 唯一条数 / 多源融合条数 / 各来源分布。"""
    return request.app.state.traffic.stats()


@router.post("/traffic/reset")
def traffic_reset(request: Request):
    """清空去重状态（演示重新开始时调用）。"""
    return {"ok": True, "stats": request.app.state.traffic.reset()}


@router.post("/traffic/shadow")
async def traffic_shadow_toggle(request: Request):
    """运行时开关影子模式（演示台用，不必重启服务）。

    body: {"enabled": true, "reset": true}
    """
    ts = request.app.state.traffic
    shadow = getattr(ts, "shadow", None)
    if shadow is None:
        return {"ok": False, "detail": "影子模式未加载"}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    on = bool(body.get("enabled", True))
    reset = bool(body.get("reset", False))
    return {"ok": True, "shadow": shadow.set_enabled(on, reset)}


@router.get("/traffic/shadow")
def traffic_shadow(request: Request):
    """影子模式统计(RL 策略与线上规则的一致率/分歧数)。未开启时 enabled=false。"""
    ts = request.app.state.traffic
    shadow = getattr(ts, "shadow", None)
    if shadow is None:
        return {"enabled": False, "reason": "未加载"}
    return shadow.stats()


@router.post("/traffic/ingest")
async def traffic_ingest(request: Request):
    """接收设备/节点回传的飞行器态势(支持数组/单对象/消息信封三种形式)。

    服务端统一做「同一性判定 + 去重 + 融合」, 下游只会看到唯一航迹。
    """
    store = request.app.state.store
    traffic_store = request.app.state.traffic
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None

    items = normalize_traffic_payload(body)
    traffic_store.set_origin(store.airport)
    stats = traffic_store.ingest(items)
    return {
        "ok": True,
        "received": len(items),
        "stored": stats.get("unique", 0),
        "merged": stats.get("merged", 0),
        "dedup": stats.get("enabled", False),
        "schema_version": SCHEMA_VERSION,
    }
