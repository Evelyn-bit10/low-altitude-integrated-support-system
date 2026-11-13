# -*- coding: utf-8 -*-
"""航迹同一性判定与去重（避免同一架无人机被重复输出）。

问题
----
同一条 RID 广播可能被多个接收机转发；同一架飞机也可能被两个设备各自
建一条航迹。下游（门户 / App / 快照 / 政府推送）必须只看到「一架一条」。

判定依据（严格分级）
--------------------
1. 强正证据：``ua_id`` 相同      -> 同一架（置信度 1.0）
2. 强正证据：``reg_no`` 相同     -> 同一架（0.95）
3. 强负证据：两者都有 ``ua_id`` 但不同 -> **一定不是同一架**（几何再像也不合并）
4. 弱证据  ：位置/航向/高度时空一致 -> 疑似同一架（仅用于缺 ID 的情况）
5. 中性    ：一方无 ID -> 匹配成功后「继承」有 ID 一方的身份，
             但有前置条件（防止「身份冒领」）：同一来源 / 该航迹上一帧仍在跟踪 /
             失联后位置几乎重合（≤ σ）

输出可见性
----------
无 ID 的新航迹先处于 TENTATIVE，**不对外输出**；连续 merge_frames（默认 2）帧
命中后才转为 CONFIRMED 并对外可见，避免单帧异常报文造出「幽灵航迹」。
带 ua_id / reg_no 的航迹创建即确认（身份本身就是强证据）。

默认门限（可按现场调整）
------------------------
    v_max            30 m/s      门限随时间的增长速度
    sigma_m          15 m        单源位置误差（用于门限与融合）
    gate_sigma       3.0         门限 = v_max*Δt + gate_sigma*sigma_m
    heading_gate     30°         航向差上限
    alt_gate         30 m        高差上限
    ttl              15 s        无观测后保留时长（避免「消失又出现」变两条）
    merge_frames     2           连续命中多少帧才确认
    split_frames     3           连续分歧多少帧才拆分

用法
----
::

    eng = DedupEngine()
    res = eng.ingest(observations, now=time.time())
    for t in res.tracks:
        print(t.global_id, t.ua_id, t.lat, t.lon, t.sources)
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

__all__ = ["Observation", "GlobalTrack", "DedupResult", "DedupEngine", "distance_m"]

M_PER_DEG_LAT = 111320.0

# ------------------------------------------------------------------ 小工具


def _m_per_deg_lon(lat: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """等距圆柱近似，几十公里内误差可忽略。"""
    dy = (lat2 - lat1) * M_PER_DEG_LAT
    dx = (lon2 - lon1) * _m_per_deg_lon((lat1 + lat2) * 0.5)
    return math.hypot(dx, dy)


def _angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _circular_mean(items: Sequence[Tuple[float, float]]) -> float:
    """items: [(heading_deg, weight)]"""
    sx = sum(w * math.cos(math.radians(h)) for h, w in items)
    sy = sum(w * math.sin(math.radians(h)) for h, w in items)
    if abs(sx) < 1e-9 and abs(sy) < 1e-9:
        return items[0][0] if items else 0.0
    return math.degrees(math.atan2(sy, sx)) % 360.0


# ------------------------------------------------------------------ 数据结构


@dataclass
class Observation:
    """一条观测（可能来自任何设备/节点）。"""

    track_id: str                      # 来源本地的临时 ID
    source: str                        # 设备 / 节点标识
    ts: float                          # 观测时刻（epoch 秒）
    lat: float
    lon: float
    alt_msl: float
    speed: float = 0.0
    heading: float = 0.0
    ua_id: Optional[str] = None        # 唯一产品识别码（RID）
    reg_no: Optional[str] = None       # 实名登记号
    quality: float = 0.6               # 该源可信度 0~1
    payload: Optional[dict] = None      # 原始 canonical 记录（下游用来保留业务字段）

    @property
    def dedup_key(self) -> str:
        """报文级幂等键：同一条广播被重复转发时用它拦掉。"""
        raw = "|".join((
            self.ua_id or self.track_id,
            "%.3f" % self.ts,
            "%.5f" % self.lat,
            "%.5f" % self.lon,
        ))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class _SourceObs:
    local_id: str
    lat: float
    lon: float
    alt_msl: float
    speed: float
    heading: float
    ts: float
    quality: float
    payload: Optional[dict] = None


@dataclass
class GlobalTrack:
    """去重后的唯一航迹（对外输出）。"""

    global_id: str
    ua_id: Optional[str]
    reg_no: Optional[str]
    lat: float
    lon: float
    alt_msl: float
    speed: float
    heading: float
    sources: Dict[str, _SourceObs] = field(default_factory=dict)
    confidence: float = 0.5
    status: str = "TENTATIVE"          # TENTATIVE / CONFIRMED / AMBIGUOUS
    hits: int = 0
    miss: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    _divergent: int = 0                # 连续分歧帧数（用于拆分）

    # -- 对外视图 -------------------------------------------------
    @property
    def source_names(self) -> List[str]:
        return sorted(self.sources.keys())

    @property
    def local_ids(self) -> Dict[str, str]:
        return {s: o.local_id for s, o in self.sources.items()}

    def as_dict(self) -> dict:
        return {
            "global_id": self.global_id,
            "ua_id": self.ua_id,
            "reg_no": self.reg_no,
            "lat": round(self.lat, 7),
            "lon": round(self.lon, 7),
            "alt_msl": round(self.alt_msl, 1),
            "speed": round(self.speed, 1),
            "heading": round(self.heading, 1),
            "sources": self.source_names,
            "local_ids": self.local_ids,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "last_seen": round(self.last_seen, 3),
        }


@dataclass
class DedupResult:
    tracks: List[GlobalTrack] = field(default_factory=list)
    matches: List[dict] = field(default_factory=list)   # 合并明细
    conflicts: List[dict] = field(default_factory=list)  # 歧义/冲突
    stats: dict = field(default_factory=dict)


# ------------------------------------------------------------------ 引擎


class DedupEngine:
    """同一性判定引擎：输入多源观测，输出唯一航迹。"""

    def __init__(self,
                 node_id: str = "NODE",
                 v_max: float = 30.0,
                 sigma_m: float = 15.0,
                 gate_sigma: float = 3.0,
                 heading_gate_deg: float = 30.0,
                 alt_gate_m: float = 30.0,
                 ttl: float = 15.0,
                 merge_frames: int = 2,
                 split_frames: int = 3,
                 idempotent_window: float = 10.0,
                 sync_window: float = 0.5,
                 half_life: float = 0.7):
        self.node_id = node_id
        self.v_max = float(v_max)
        self.sigma_m = float(sigma_m)
        self.gate_sigma = float(gate_sigma)
        self.heading_gate_deg = float(heading_gate_deg)
        self.alt_gate_m = float(alt_gate_m)
        self.ttl = float(ttl)
        self.merge_frames = int(merge_frames)
        self.split_frames = int(split_frames)
        self.idempotent_window = float(idempotent_window)
        # 融合只用「同一时刻窗口内」的观测：异步到达的旧观测只保留身份，不参与位置计算，
        # 否则会把移动目标的位置拖回上一帧（这是异步多源融合最常见的坑）。
        self.sync_window = float(sync_window)
        # 异步到达的观测按「新旧」衰减加权：越旧权重越低，避免把位置拖回上一帧
        self.half_life = float(half_life)

        self.tracks: Dict[str, GlobalTrack] = {}
        self.by_ua: Dict[str, str] = {}
        self.by_reg: Dict[str, str] = {}
        self._seen_keys: Dict[str, float] = {}
        self._seq = 0

    # ---------------------------------------------------------- 对外
    def ingest(self, observations: Iterable[Observation], now: float) -> DedupResult:
        """处理一帧观测。

        参数
        ----
        observations : 本帧收到的全部观测（可来自任意多个设备）
        now          : 本帧时刻（epoch 秒）。用于门限外推与 TTL

        返回
        ----
        DedupResult：唯一航迹 + 合并明细 + 统计
        """
        obs_list = list(observations)
        res = DedupResult()
        res.stats = {"input": len(obs_list), "duplicate": 0, "matched": 0,
                     "created": 0, "expired": 0, "split": 0}

        self._purge_seen(now)

        # ① 报文幂等 + ② 帧内去重（同一 source 同一 local_id 只取最新一条）
        fresh: List[Observation] = []
        for o in obs_list:
            k = o.dedup_key
            if k in self._seen_keys:
                res.stats["duplicate"] += 1
                continue
            self._seen_keys[k] = now
            fresh.append(o)

        # 强标识优先处理：避免「无名」观测抢走已命名航迹
        fresh.sort(key=lambda o: (
            0 if o.ua_id else (1 if o.reg_no else 2),
            -o.quality,
        ))

        # 同一帧里，一条航迹允许被多个「不同来源」的观测更新（这正是多设备协同），
        # 但同一来源对同一条航迹只允许一次几何匹配，避免把两个真目标并成一个。
        geo_claimed: Set[Tuple[str, str]] = set()
        touched: Set[str] = set()

        for o in fresh:
            gid, score, reason = self._resolve(o, now, geo_claimed)

            # 连续性接管：同一设备短暂报错（航向跳变/GPS 抖动）时，
            # 不要把同一个目标拆成两条航迹
            if gid is None:
                gid = self._reacquire(o, now, geo_claimed)
                if gid is not None:
                    score, reason = 0.5, "reacquire"

            if gid is None:
                track = self._create(o, now)
                res.stats["created"] += 1
            else:
                track = self.tracks[gid]
                self._apply(track, o, now)
                res.stats["matched"] += 1
                res.matches.append({
                    "source": o.source, "local_id": o.track_id,
                    "global_id": gid, "score": round(score, 3), "reason": reason,
                })
            if reason == "geo":
                geo_claimed.add((track.global_id, o.source))
            touched.add(track.global_id)

        # ③ 未命中的航迹累加 miss，超 TTL 删除
        for gid in list(self.tracks.keys()):
            t = self.tracks[gid]
            if gid not in touched:
                t.miss += 1
                if now - t.last_seen > self.ttl:
                    self._remove(gid)
                    res.stats["expired"] += 1
                    continue
            self._refresh(t, now)
            # ④ 状态推进 / 拆分
            if t.status == "TENTATIVE" and t.hits >= self.merge_frames:
                t.status = "CONFIRMED"
            if self._check_split(t, now, res):
                res.stats["split"] += 1

        res.tracks = self.visible_tracks()
        res.stats["unique"] = len(res.tracks)
        res.stats["tentative"] = len(self.tracks) - len(res.tracks)
        return res

    def visible_tracks(self) -> List[GlobalTrack]:
        """对外输出的航迹：TENTATIVE（未确认）不输出，避免抖动瞬间多出一条。"""
        vis = [t for t in self.tracks.values() if t.status != "TENTATIVE"]
        return sorted(vis, key=lambda t: (-t.confidence, t.global_id))

    # ---------------------------------------------------------- 匹配
    def _resolve(self, o: Observation, now: float,
                 geo_claimed: Set[Tuple[str, str]]) -> Tuple[Optional[str], float, str]:
        """返回 (命中的 global_id, 分数, 原因)。"""
        # 强标识：哈希直接命中
        if o.ua_id:
            gid = self.by_ua.get(o.ua_id)
            if gid and gid in self.tracks:
                return gid, 1.0, "ua_id"
        if o.reg_no:
            gid = self.by_reg.get(o.reg_no)
            if gid and gid in self.tracks:
                return gid, 0.95, "reg_no"

        # 空间匹配（只对缺失/单边缺失标识的情况）
        best: Tuple[Optional[str], float, float] = (None, 0.0, 0.0)
        for gid, t in self.tracks.items():
            if (gid, o.source) in geo_claimed:
                continue
            if not self._identity_compatible(o, t):
                continue
            score, _, d = self._geo_score(o, t, now)
            if score <= 0.0:
                continue
            if not self._absorbable(o, t, d):
                continue
            if score > best[1]:
                best = (gid, score, score)
        if best[0] is not None:
            return best[0], best[1], "geo"
        return None, 0.0, ""

    def _absorbable(self, o: Observation, t: GlobalTrack, d: float) -> bool:
        """无名观测能否并入「有身份」的航迹。

        防止「身份冒领」：一架没有 ID 的无人机飞到某架已失联飞机的旧位置附近，
        不能直接继承对方的 ua_id。只有下列情况才允许：
          1) 观测自身带 ID（冲突已由 _identity_compatible 拦截）
          2) 双方都无名
          3) 同一设备一直在跟踪（该源已在这条航迹里）
          4) 该航迹上一帧仍在跟踪（设备间接力）
          5) 失联后，只有位置几乎重合（≤ σ）才接受
        """
        if o.ua_id or o.reg_no:
            return True
        if not (t.ua_id or t.reg_no):
            return True
        if o.source in t.sources:
            return True
        if t.miss <= 1:
            return True
        return d <= self.sigma_m

    def _reacquire(self, o: Observation, now: float,
                   geo_claimed: Set[Tuple[str, str]]) -> Optional[str]:
        """同一来源的连续性接管（用放宽 1.5 倍的门限）。

        设备偶尔报一条异常数据（航向跳变、GPS 抖动）时，宁可继续跟原来那条，
        也不要在旁边新建一条「幽灵航迹」。
        """
        best: Optional[str] = None
        best_d: Optional[float] = None
        for gid, t in self.tracks.items():
            if (gid, o.source) in geo_claimed:
                continue
            if not self._identity_compatible(o, t):
                continue
            src = t.sources.get(o.source)
            if src is None:            # 必须是同一设备之前报过的目标
                continue
            dt = max(0.0, now - src.ts)
            gate = (self.v_max * dt + self.gate_sigma * self.sigma_m) * 1.5
            d = distance_m(o.lat, o.lon, src.lat, src.lon)
            if d <= gate and (best_d is None or d < best_d):
                best, best_d = gid, d
        return best

    def _identity_compatible(self, o: Observation, t: GlobalTrack) -> bool:
        """强负证据优先：双方都有 ua_id 且不同 -> 绝不合并。"""
        if o.ua_id and t.ua_id and o.ua_id != t.ua_id:
            return False
        if o.reg_no and t.reg_no and o.reg_no != t.reg_no:
            return False
        return True

    def _geo_score(self, o: Observation, t: GlobalTrack,
                   now: float) -> Tuple[float, float, float]:
        """返回 (0~1 得分, 门限, 水平距离)。得分 0 表示不合格。"""
        dt = max(0.0, now - t.last_seen)
        gate = self.v_max * dt + self.gate_sigma * self.sigma_m
        d = distance_m(o.lat, o.lon, t.lat, t.lon)
        if d > gate:
            return 0.0, gate, d
        if abs(o.alt_msl - t.alt_msl) > self.alt_gate_m:
            return 0.0, gate, d
        # 高速目标才用航向判定，低速/悬停时航向噪声大
        if o.speed > 2.0 and t.speed > 2.0:
            if _angle_diff(o.heading, t.heading) > self.heading_gate_deg:
                return 0.0, gate, d
        return max(0.0, 1.0 - d / max(gate, 1e-6)), gate, d

    # ---------------------------------------------------------- 融合
    def _create(self, o: Observation, now: float) -> GlobalTrack:
        self._seq += 1
        if o.ua_id:
            gid = "G-%s" % o.ua_id
        elif o.reg_no:
            gid = "G-R%s" % o.reg_no
        else:
            gid = "G-%s-%04d" % (self.node_id, self._seq)

        # 极少数情况：ua_id 生成的 gid 已存在（并发/历史残留），加后缀
        base = gid
        n = 1
        while gid in self.tracks:
            n += 1
            gid = "%s-%d" % (base, n)

        t = GlobalTrack(
            global_id=gid, ua_id=o.ua_id, reg_no=o.reg_no,
            lat=o.lat, lon=o.lon, alt_msl=o.alt_msl,
            speed=o.speed, heading=o.heading,
            confidence=o.quality,
            # 带 ID 的观测可以直接确认；无名的先观察一帧，避免异常报文造出幽灵航迹
            status="CONFIRMED" if (o.ua_id or o.reg_no) else "TENTATIVE",
            hits=1, first_seen=o.ts, last_seen=o.ts,
        )
        t.sources[o.source] = _SourceObs(o.track_id, o.lat, o.lon, o.alt_msl,
                                         o.speed, o.heading, o.ts, o.quality, o.payload)
        self.tracks[gid] = t
        if o.ua_id:
            self.by_ua[o.ua_id] = gid
        if o.reg_no:
            self.by_reg[o.reg_no] = gid
        return t

    def _apply(self, t: GlobalTrack, o: Observation, now: float) -> None:
        """把一条观测并入已有航迹。"""
        t.sources[o.source] = _SourceObs(o.track_id, o.lat, o.lon, o.alt_msl,
                                         o.speed, o.heading, o.ts, o.quality, o.payload)
        t.hits += 1
        t.miss = 0
        t.last_seen = max(t.last_seen, o.ts)
        # 身份继承：无 ID 的一方不覆盖有 ID 的一方
        if o.ua_id and not t.ua_id:
            t.ua_id = o.ua_id
            self.by_ua[o.ua_id] = t.global_id
        if o.reg_no and not t.reg_no:
            t.reg_no = o.reg_no
            self.by_reg[o.reg_no] = t.global_id
        # 立即刷新融合位置：同一帧里后续观测要基于最新位置做门限判断
        self._refresh(t, now)

    def _refresh(self, t: GlobalTrack, now: float) -> None:
        """用各源最新观测重新计算融合位置与置信度。"""
        live = [s for s in t.sources.values() if now - s.ts <= self.ttl]
        if not live:
            return
        # 只取最新时刻窗口内的观测做融合（异步旧数据不参与位置计算）
        newest = max(s.ts for s in live)

        def _w(s):
            # 时间衰减 * 源质量
            return max(s.quality, 1e-3) * (0.5 ** (max(0.0, newest - s.ts) / self.half_life))

        wsum = sum(_w(s) for s in live)
        if wsum <= 0:
            return
        t.lat = sum(s.lat * _w(s) for s in live) / wsum
        t.lon = sum(s.lon * _w(s) for s in live) / wsum
        t.alt_msl = sum(s.alt_msl * _w(s) for s in live) / wsum
        t.speed = sum(s.speed * _w(s) for s in live) / wsum
        t.heading = _circular_mean([(s.heading, _w(s)) for s in live])

        # 置信度：同一时刻窗内的源越多、越一致 -> 越高
        winners = [s for s in live if newest - s.ts <= self.sync_window]
        agree = 1.0
        if len(winners) <= 1:
            t.confidence = 0.6 * live[0].quality + 0.2
        else:
            spread = max(
                distance_m(a.lat, a.lon, b.lat, b.lon)
                for i, a in enumerate(winners) for b in winners[i + 1:]
            )
            agree = max(0.0, 1.0 - spread / (3.0 * self.sigma_m))
            t.confidence = min(1.0, 0.55 + 0.15 * (len(winners) - 1) + 0.25 * agree)

        # 同帧多源明显分歧（间距 > 2.25σ ≈ 34 m）-> 标歧义，供下游告警
        # 注意：不能只靠 confidence<0.6 判断——两源时 confidence 最低也有 0.70，那条分支永远不会触发
        if len(winners) >= 2 and agree < 0.25:
            t.status = "AMBIGUOUS"
        elif t.status == "AMBIGUOUS" and (len(winners) <= 1 or agree >= 0.25):
            t.status = "CONFIRMED"      # 分歧消失后自动恢复

    # ---------------------------------------------------------- 拆分
    def _check_split(self, t: GlobalTrack, now: float, res: DedupResult) -> bool:
        """同一航迹里两个源长期分歧 -> 拆成两条（防止「粘住」）。"""
        live_all = [(name, s) for name, s in t.sources.items() if now - s.ts <= self.ttl]
        if len(live_all) < 2:
            t._divergent = 0
            return False
        newest = max(s.ts for _, s in live_all)
        live = [(n, s) for n, s in live_all if newest - s.ts <= self.sync_window]
        if len(live) < 2:
            t._divergent = 0
            return False

        split_gate = max(3.0 * self.sigma_m, self.gate_sigma * self.sigma_m * 1.5)
        far = None
        for i, (na, a) in enumerate(live):
            for nb, b in live[i + 1:]:
                if distance_m(a.lat, a.lon, b.lat, b.lon) > split_gate:
                    far = (na, nb)
                    break
            if far:
                break

        if not far:
            t._divergent = 0
            return False

        t._divergent += 1
        if t._divergent < self.split_frames:
            return False

        # 拆：质量低的一方独立成新航迹
        na, nb = far
        sa, sb = t.sources[na], t.sources[nb]
        drop = na if sa.quality <= sb.quality else nb
        s = t.sources.pop(drop)
        if not t.sources:
            return False
        self._refresh(t, now)
        t._divergent = 0

        # 优先挂到附近已存在的航迹，避免拆分后与既有航迹重复
        target_gid = self._nearest_track(s.lat, s.lon, s.ts, exclude=t.global_id)
        if target_gid:
            nt = self.tracks[target_gid]
            nt.sources[drop] = s
            nt.hits += 1
            nt.last_seen = max(nt.last_seen, s.ts)
            self._refresh(nt, now)
            gid = target_gid
        else:
            self._seq += 1
            gid = "G-%s-%04d" % (self.node_id, self._seq)
            nt = GlobalTrack(
                global_id=gid, ua_id=None, reg_no=None,
                lat=s.lat, lon=s.lon, alt_msl=s.alt_msl,
                speed=s.speed, heading=s.heading,
                confidence=s.quality, status="CONFIRMED",
                hits=t.hits, first_seen=s.ts, last_seen=s.ts,
            )
            nt.sources[drop] = s
            self.tracks[gid] = nt

        res.conflicts.append({
            "global_id": t.global_id, "split_out": gid,
            "kept": t.source_names, "moved": drop,
            "distance": round(distance_m(sa.lat, sa.lon, sb.lat, sb.lon), 1),
        })
        return True

    def _nearest_track(self, lat: float, lon: float, ts: float,
                       exclude: Optional[str] = None) -> Optional[str]:
        """找一个能容纳该点的既有航迹（用于拆分归位）。"""
        best, best_d = None, None
        gate = self.gate_sigma * self.sigma_m
        for gid, t in self.tracks.items():
            if gid == exclude:
                continue
            d = distance_m(lat, lon, t.lat, t.lon)
            if d <= gate and (best_d is None or d < best_d):
                best, best_d = gid, d
        return best

    # ---------------------------------------------------------- 维护
    def _remove(self, gid: str) -> None:
        t = self.tracks.pop(gid, None)
        if not t:
            return
        if t.ua_id and self.by_ua.get(t.ua_id) == gid:
            self.by_ua.pop(t.ua_id, None)
        if t.reg_no and self.by_reg.get(t.reg_no) == gid:
            self.by_reg.pop(t.reg_no, None)

    def _purge_seen(self, now: float) -> None:
        if len(self._seen_keys) < 4096:
            return
        cut = now - self.idempotent_window
        self._seen_keys = {k: v for k, v in self._seen_keys.items() if v >= cut}
