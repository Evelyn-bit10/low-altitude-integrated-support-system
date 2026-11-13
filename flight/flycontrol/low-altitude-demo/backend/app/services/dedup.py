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

from app.services.assignment import max_weight_matching
from app.services.kalman import KalmanCV

__all__ = ["Observation", "GlobalTrack", "DedupResult", "DedupEngine", "distance_m"]

M_PER_DEG_LAT = 111320.0

# ------------------------------------------------------------------ 小工具


_MPD_CACHE: Dict[int, float] = {}


def _m_per_deg_lon(lat: float) -> float:
    # 按 0.001° 量化后缓存：同一批目标几乎都落在同一格，省掉几十万次 cos()
    key = int(lat * 1000.0)
    v = _MPD_CACHE.get(key)
    if v is None:
        v = M_PER_DEG_LAT * math.cos(math.radians(key / 1000.0))
        _MPD_CACHE[key] = v
    return v


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
    quality: float = 0.6               # 该源可信度 0~1（仅用于展示/兜底）
    sigma: Optional[float] = None       # 该源位置误差 σ（米）；缺省按 source 查表
    raw_ts: Optional[float] = None      # 校正前的原始时间戳（幂等键用它）
    payload: Optional[dict] = None      # 原始 canonical 记录（下游用来保留业务字段）

    @property
    def dedup_key(self) -> str:
        """报文级幂等键：同一条广播被重复转发时用它拦掉。"""
        raw = "|".join((
            self.ua_id or self.track_id,
            "%.3f" % (self.raw_ts if self.raw_ts is not None else self.ts),
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
    sigma: float
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
    err_sigma: float = 0.0             # 融合不确定度缓存（_refresh 时更新）
    kf: object = None                  # 匀速模型卡尔曼滤波器（水平面）
    kf_applied: dict = field(default_factory=dict)   # src -> 已喂给滤波器的观测 ts
    _refresh_key: tuple = None         # 同帧重复调用短路
    _calib_key: tuple = None           # 标定采样去重（每帧只采一次）
    density_scale: float = 1.0         # 按场景密度缩放门限（1.0=稀疏）
    lat0: float = 0.0                  # 该航迹局部坐标原点（建轨时的纬度）
    lon0: float = 0.0                  # 同上，经度

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
                 half_life: float = 0.7,
                 gate_k: float = 3.44,
                 source_sigmas: Optional[Dict[str, float]] = None,
                 default_sigma: float = 20.0,
                 sigma_floor: float = 8.0,
                 grid_threshold: int = 50,
                 predict_horizon: float = 3.0,
                 sigma_speed: float = 1.5,
                 sigma_heading_deg: float = 8.0,
                 accel_max: float = 2.0,
                 sigma_autocalib: bool = True,
                 sigma_calib_samples: int = 200,
                 assign_mode: str = "greedy",
                 post_merge: bool = False,
                 use_kalman: bool = True,
                 kf_sigma_a: float = 2.0,
                 density_gate: bool = False):
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
        # 门限 = gate_k × sqrt(σ_obs² + σ_track² + (v_max·Δt)²/3)
        # gate_k = 3.44 对应 χ²(2, 99.7%)，比"线性 3σ"更符合统计意义
        self.gate_k = float(gate_k)
        self.source_sigmas = dict(source_sigmas or {})
        self.default_sigma = float(default_sigma)
        self.sigma_floor = float(sigma_floor)

        # 每源的时钟偏移（收到时刻 - 报文时刻），EWMA 估计后用于时间对齐
        # 空间索引：目标数超过阈值时启用，避免 O(N²)
        self.grid_threshold = int(grid_threshold)
        # 运动预测：短时（≤ horizon）用速度/航向外推，长时退回静态 + 扩大门限
        self.predict_horizon = float(predict_horizon)
        self.sigma_speed = float(sigma_speed)
        self.sigma_heading = math.radians(float(sigma_heading_deg))
        self.accel_max = float(accel_max)
        # σ 在线自标定：用"同一时刻两个源的位置差"反推整体尺度
        self.sigma_autocalib = bool(sigma_autocalib)
        self.assign_mode = (assign_mode or "greedy").lower()
        self.post_merge = bool(post_merge)
        self.use_kalman = bool(use_kalman)
        self.kf_sigma_a = float(kf_sigma_a)
        self.density_gate = bool(density_gate)
        self.sigma_calib_samples = int(sigma_calib_samples)
        self.sigma_scale = 1.0
        self._pair_stats: Dict[Tuple[str, str], List[float]] = {}
        self._sigma_n = 0
        self.cell_deg = 0.001          # ≈ 111 m
        self._now = 0.0
        self._stale: List[str] = []
        self._grid: Dict[Tuple[int, int], List[str]] = {}

        self.clock_offset: Dict[str, float] = {}
        self.clock_samples: Dict[str, int] = {}

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
        obs_list = [self.sync_time(o, now) for o in observations]
        res = DedupResult()
        res.stats = {"input": len(obs_list), "duplicate": 0, "matched": 0,
                     "created": 0, "expired": 0, "split": 0}

        self._purge_seen(now)

        # 卡尔曼：每帧对每条航迹做**一次**预测，供本帧所有候选边共用
        if self.use_kalman:
            for t in self.tracks.values():
                if t.kf is not None:
                    t.kf.predict(max(0.0, now - t.last_seen), self.kf_sigma_a)
        if self.density_gate:
            self._update_density()

        # ① 报文幂等
        fresh: List[Observation] = []
        for o in obs_list:
            k = o.dedup_key
            if k in self._seen_keys:
                res.stats["duplicate"] += 1
                continue
            self._seen_keys[k] = now
            fresh.append(o)

        # 强标识优先：新建航迹时先给有身份的用上 ID
        fresh.sort(key=lambda o: (0 if o.ua_id else (1 if o.reg_no else 2), -o.quality))

        self._now = now
        self._rebuild_grid()

        used_obs: Set[int] = set()
        claimed_geo: Set[Tuple[str, str]] = set()
        touched: Set[str] = set()
        pending: List[int] = list(range(len(fresh)))

        def _hash_hit(o: Observation) -> Optional[str]:
            gid = self.by_ua.get(o.ua_id) if o.ua_id else None
            if not gid and o.reg_no:
                gid = self.by_reg.get(o.reg_no)
            return gid if (gid and gid in self.tracks) else None

        # ② 强标识命中（哈希，无竞争）
        for i in list(pending):
            gid = _hash_hit(fresh[i])
            if gid:
                o = fresh[i]
                self._assign(fresh, i, gid, 1.0 if o.ua_id else 0.95,
                             "ua_id" if o.ua_id else "reg_no",
                             res, used_obs, touched, now)
                pending.remove(i)

        def _geo_pass(indices: List[int]) -> None:
            """对所有给定观测收集候选边，按分数全局分配。"""
            edges: List[Tuple[float, int, str]] = []
            for i in indices:
                o = fresh[i]
                for score, gid in self._geo_candidates(o, now):
                    edges.append((score, i, gid))
            if self.assign_mode == "hungarian":
                # 同一来源内做最大权指派：一条航迹对同一来源只能收一条观测，
                # 所以按来源拆开分别求解，正好是标准二分匹配
                by_src = {}
                for i in indices:
                    if i in used_obs:
                        continue
                    o = fresh[i]
                    cand = {}
                    for score, gid in self._geo_candidates(o, now):
                        if (gid, o.source) in claimed_geo:
                            continue
                        if score > cand.get(gid, 0.0):
                            cand[gid] = score
                    if cand:
                        by_src.setdefault(o.source, []).append((i, cand))
                for src, rows in by_src.items():
                    gids = sorted({g for _, c in rows for g in c})
                    if not gids:
                        continue
                    W = [[c.get(g, 0.0) for g in gids] for _, c in rows]
                    for (i, c), j in zip(rows, max_weight_matching(W, 0.01)):
                        if j is None or i in used_obs:
                            continue
                        gid = gids[j]
                        if (gid, src) in claimed_geo:
                            continue
                        self._assign(fresh, i, gid, c[gid], "geo", res,
                                     used_obs, touched, now)
                        claimed_geo.add((gid, src))
                        if i in pending:
                            pending.remove(i)
                return

            edges.sort(reverse=True)
            for score, i, gid in edges:
                if i in used_obs or (gid, fresh[i].source) in claimed_geo:
                    continue
                self._assign(fresh, i, gid, score, "geo", res, used_obs, touched, now)
                claimed_geo.add((gid, fresh[i].source))
                if i in pending:
                    pending.remove(i)

        # ③ 几何匹配（对已有航迹）
        if self.tracks:
            _geo_pass(list(pending))

        # ④ 先把「有身份但还没找到家」的建出来，这样同帧的无名观测可以并进它们
        created_new = 0
        for i in list(pending):
            o = fresh[i]
            if not (o.ua_id or o.reg_no):
                continue
            gid = _hash_hit(o)          # 同帧前面可能刚建好同 ID 的航迹
            if gid:
                self._assign(fresh, i, gid, 1.0 if o.ua_id else 0.95,
                             "ua_id" if o.ua_id else "reg_no",
                             res, used_obs, touched, now)
                pending.remove(i)
                continue
            track = self._create(o, now)
            res.stats["created"] += 1
            created_new += 1
            touched.add(track.global_id)
            used_obs.add(i)
            pending.remove(i)

        # ⑤ 再给无名观测一次几何匹配（只有本帧新建过航迹才有意义）
        if created_new and pending:
            _geo_pass(list(pending))

        # ⑥ 连续性接管 / 与「本帧刚建的航迹」匹配 / 新建
        for i in list(pending):
            o = fresh[i]
            gid = self._reacquire(o, now, claimed_geo)
            score, reason = 0.5, "reacquire"
            if gid is None:
                # 首帧没有历史航迹时，后面的观测应该能并进前面刚建的航迹
                cands = sorted(self._geo_candidates(o, now), reverse=True)
                for sc, cand in cands:
                    if (cand, o.source) in claimed_geo:
                        continue
                    gid, score, reason = cand, sc, "geo"
                    break
            if gid is not None:
                self._assign(fresh, i, gid, score, reason, res, used_obs, touched, now)
                claimed_geo.add((gid, o.source))
            else:
                track = self._create(o, now)
                res.stats["created"] += 1
                touched.add(track.global_id)
                used_obs.add(i)
            pending.remove(i)

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

        self._maybe_calibrate_sigma()

        if self.post_merge:
            res.stats["post_merged"] = self._post_merge(now, res)

        res.tracks = self.visible_tracks()
        res.stats["unique"] = len(res.tracks)
        res.stats["tentative"] = len(self.tracks) - len(res.tracks)
        return res

    # ---------------------------------------------------------- 事后回并
    def _post_merge(self, now: float, res: "DedupResult") -> int:
        """把"同一架飞机被拆成多条航迹"的情况合回去。

        为什么需要：
            在线分配是"一帧一帧决策"，早先某帧因为门限/时钟抖动没配上，
            就会新建一条碎片航迹，之后两边各自延续，再也不会合到一起。

        约束（宁可不合，不可错合）：
            * 两条航迹的**来源不重叠**（A 只看到一条、B 只看到另一条）；
            * 身份不冲突：ua_id 相同，或双方都没有 ua_id/reg_no；
            * 都足够成熟（hits >= merge_frames）；
            * 位置很近（< 1.5 倍联合 σ）且方向一致（< 45° 或低速）；
            * 时间上都在最近一帧更新过。
        """
        n = 0
        gids = sorted(self.tracks.keys())
        if len(gids) > 200:            # 性能保护：大规模场景不做 O(n²) 回并
            return 0
        dead = set()

        # 每条的最近两个邻居：只有"互为最近邻、且明显比第三名近"才允许合并，
        # 否则蜂群场景会把两架真实飞机合并成一条
        near = {}
        for i, ga in enumerate(gids):
            ta = self.tracks[ga]
            ds = []
            for gb in gids:
                if gb == ga:
                    continue
                tb = self.tracks[gb]
                ds.append((distance_m(ta.lat, ta.lon, tb.lat, tb.lon), gb))
            ds.sort()
            near[ga] = ds[:2]
        for ai in range(len(gids)):
            ga = gids[ai]
            if ga in dead or ga not in self.tracks:
                continue
            a = self.tracks[ga]
            for bi in range(ai + 1, len(gids)):
                gb = gids[bi]
                if gb in dead or gb not in self.tracks:
                    continue
                b = self.tracks[gb]
                if not self._identity_same(a, b):
                    continue
                if min(a.hits, b.hits) < max(2, self.merge_frames):
                    continue
                na, nb = near[ga], near[gb]
                if not na or not nb or na[0][1] != gb or nb[0][1] != ga:
                    continue            # 必须互为最近邻
                third = na[1][0] if len(na) > 1 else 1e9
                # 密度保护：附近还有别的航迹在 3σ 以内，说明空间分辨不了，宁可不错合
                if third < 3.0 * max(a.err_sigma or 15.0, b.err_sigma or 15.0, 8.0):
                    continue
                if na[0][0] > 0.7 * third:
                    continue
                if now - max(a.last_seen, b.last_seen) > 1.0:
                    continue
                # 有滤波器的航迹用**滤波后位置**比较（比原始融合点更稳）
                if a.kf is not None and b.kf is not None:
                    bx, by = self._to_local(a, *self._to_wgs(b, *b.kf.pos()))
                    ax, ay = a.kf.pos()
                    d = math.hypot(bx - ax, by - ay)
                    lim = 1.2 * max(a.err_sigma or a.kf.sigma(), b.err_sigma or b.kf.sigma(), 8.0)
                else:
                    d = distance_m(a.lat, a.lon, b.lat, b.lon)
                    lim = 1.2 * max(a.err_sigma or 15.0, b.err_sigma or 15.0, 8.0)
                if d > lim:
                    continue
                dh = abs(((a.heading - b.heading + 180.0) % 360.0) - 180.0)
                if dh > 30.0 and min(a.speed, b.speed) > 3.0:
                    continue
                if self._absorb_track(a, b, now):
                    dead.add(gb)
                    n += 1
                    continue
                if self._absorb_track(b, a, now):
                    dead.add(ga)
                    n += 1
                    break
        return n

    @staticmethod
    def _sources_disjoint(a: "GlobalTrack", b: "GlobalTrack") -> bool:
        return not (set(a.sources) & set(b.sources))

    @staticmethod
    def _identity_same(a: "GlobalTrack", b: "GlobalTrack") -> bool:
        if a.ua_id and b.ua_id:
            return a.ua_id == b.ua_id
        if a.reg_no and b.reg_no:
            return a.reg_no == b.reg_no
        # 一方有 ID 一方没有：只有在都没有 reg 冲突时才允许
        if (a.ua_id and b.ua_id and a.ua_id != b.ua_id):
            return False
        if (a.reg_no and b.reg_no and a.reg_no != b.reg_no):
            return False
        return True

    def _absorb_track(self, keep: "GlobalTrack", drop: "GlobalTrack", now: float) -> bool:
        """把 drop 的来源并入 keep，然后删掉 drop。

        来源可能重叠（同一条被拆成两条各自双源），此时保留**更新的**那条观测。
        """
        for src, so in drop.sources.items():
            cur = keep.sources.get(src)
            if cur is None or so.ts >= cur.ts:
                keep.sources[src] = so
        keep.ua_id = keep.ua_id or drop.ua_id
        keep.reg_no = keep.reg_no or drop.reg_no
        keep.hits = max(keep.hits, drop.hits)
        keep.miss = min(keep.miss, drop.miss)
        keep.last_seen = max(keep.last_seen, drop.last_seen)
        keep.first_seen = min(keep.first_seen, drop.first_seen)
        keep.global_id = keep.global_id or drop.global_id
        self._refresh(keep, now)
        self.tracks.pop(drop.global_id, None)
        return True

    def _assign(self, fresh: List[Observation], i: int, gid: str, score: float,
                reason: str, res: "DedupResult", used_obs: Set[int],
                touched: Set[str], now: float) -> None:
        o = fresh[i]
        track = self.tracks[gid]
        self._apply(track, o, now)
        used_obs.add(i)
        touched.add(gid)
        res.stats["matched"] += 1
        res.matches.append({"source": o.source, "local_id": o.track_id,
                            "global_id": gid, "score": round(score, 3),
                            "reason": reason})

    def _update_density(self) -> None:
        """按"最近邻航迹距离"给每条航迹算一个门限缩放系数。

        稀疏空域（最近邻 >250 m）：1.0，门限不变
        蜂群场景（最近邻 ≈ 0）：0.6，门限收紧 40%

        这也是强化学习策略一直在用的上下文信息——把它反馈给规则引擎，
        规则本身就能"看密度下菜"，不必等策略上线。
        """
        tracks = self.tracks
        n = len(tracks)
        if n <= 1:
            for t in tracks.values():
                t.density_scale = 1.0
            return

        if not self._grid:                       # 小规模：直接两两算
            items = list(tracks.values())
            for i, a in enumerate(items):
                best = 1e9
                for j, b in enumerate(items):
                    if i == j:
                        continue
                    d = distance_m(a.lat, a.lon, b.lat, b.lon)
                    if d < best:
                        best = d
                    if best < 20.0:
                        break
                a.density_scale = 0.6 + 0.4 * min(1.0, best / 250.0)
            return

        d = self.cell_deg
        for gid, t in tracks.items():
            ci = int(math.floor(t.lat / d))
            cj = int(math.floor(t.lon / d))
            best = 1e9
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for gid2 in self._grid.get((ci + di, cj + dj), ()):
                        if gid2 == gid:
                            continue
                        t2 = tracks.get(gid2)
                        if t2 is None:
                            continue
                        dd = distance_m(t.lat, t.lon, t2.lat, t2.lon)
                        if dd < best:
                            best = dd
            for gid2 in self._stale:             # 失联航迹也算密度
                if gid2 == gid:
                    continue
                t2 = tracks.get(gid2)
                if t2 is None:
                    continue
                dd = distance_m(t.lat, t.lon, t2.lat, t2.lon)
                if dd < best:
                    best = dd
            t.density_scale = 0.6 + 0.4 * min(1.0, best / 250.0)

    def _rebuild_grid(self) -> None:
        if len(self.tracks) <= self.grid_threshold:
            self._grid = {}
            self._stale = []
            return
        grid: Dict[Tuple[int, int], List[str]] = {}
        stale: List[str] = []
        d = self.cell_deg
        for gid, t in self.tracks.items():
            # 超过 3 秒没更新的航迹单独放，查询时线性补上（保证大 Δt 也能匹配）
            if self._now - t.last_seen > 3.0:
                stale.append(gid)
                continue
            key = (int(math.floor(t.lat / d)), int(math.floor(t.lon / d)))
            grid.setdefault(key, []).append(gid)
        self._grid = grid
        self._stale = stale

    def _nearby(self, lat: float, lon: float, radius_m: float):
        """网格查询：返回半径内的候选航迹（未启用网格时返回全部）。"""
        if not self._grid:
            return self.tracks.values()
        d = self.cell_deg
        cells = max(1, int(math.ceil(radius_m / (d * 111000.0))))
        ci, cj = int(math.floor(lat / d)), int(math.floor(lon / d))
        out = []
        for di in range(-cells, cells + 1):
            for dj in range(-cells, cells + 1):
                for gid in self._grid.get((ci + di, cj + dj), ()):
                    t = self.tracks.get(gid)
                    if t is not None:
                        out.append(t)
        for gid in self._stale:            # 失联稍久的航迹
            t = self.tracks.get(gid)
            if t is not None:
                out.append(t)
        return out

    def _geo_candidates(self, o: Observation, now: float) -> List[Tuple[float, str]]:
        """返回该观测的所有可行候选 (score, gid)，供全局分配使用。"""
        s_obs = o.sigma or self.sigma_of(o.source)
        # 查询半径按「典型 3 秒」估，更久未更新的航迹由 _stale 线性补上
        radius = self.gate_k * math.sqrt(s_obs ** 2 + s_obs ** 2 +
                                         (self.v_max * 3.0) ** 2 / 3.0)
        out: List[Tuple[float, str]] = []
        for t in self._nearby(o.lat, o.lon, radius):
            # 网格只能粗筛（返回整格），这里先按真实距离砍掉大部分，再做完整打分
            if distance_m(o.lat, o.lon, t.lat, t.lon) > radius:
                continue
            gid = t.global_id
            if not self._identity_compatible(o, t):
                continue
            score, _, d = self._geo_score(o, t, now)
            if score <= 0.0:
                continue
            if not self._absorbable(o, t, d):
                continue
            out.append((score, gid))
        return out

    def visible_tracks(self) -> List[GlobalTrack]:
        """对外输出的航迹：TENTATIVE（未确认）不输出，避免抖动瞬间多出一条。"""
        vis = [t for t in self.tracks.values() if t.status != "TENTATIVE"]
        return sorted(vis, key=lambda t: (-t.confidence, t.global_id))

    # ---------------------------------------------------------- 时间对齐
    def sync_time(self, o: Observation, now: float) -> Observation:
        """把报文时间戳校正到本机时间基准。

        不同设备的时钟可能慢/快几秒，直接拿它们的 ts 算 Δt 会把门限放大或缩小
        （实测：Δt 偏差 1 秒 ≈ 漏配率翻 5 倍）。这里用「收到时刻 - 报文时刻」
        的滑动均值估计偏移，并把 ts 校正过来。
        """
        if o.raw_ts is None:
            o.raw_ts = o.ts
        raw = now - o.raw_ts
        if abs(raw) > 120.0:            # 明显异常（时区错误/坏时间戳）→ 不校正
            return o

        prev = self.clock_offset.get(o.source)
        n = self.clock_samples.get(o.source, 0)
        if prev is None:
            off = raw                    # 第一个样本直接采用
        elif n < 5:
            off = (prev * n + raw) / (n + 1)   # 前几个样本用平均，快速收敛
        else:
            off = prev + 0.05 * (raw - prev)   # 之后用 EWMA 跟踪漂移

        self.clock_offset[o.source] = off
        self.clock_samples[o.source] = n + 1
        o.ts = o.raw_ts + off
        return o

    # ---------------------------------------------------------- σ / 门限
    def _base_sigma(self, source: str) -> float:
        return float(self.source_sigmas.get(source, self.default_sigma))

    def sigma_of(self, source: str) -> float:
        """按源取位置误差：配置值 × 在线标定尺度，并做下限保护。"""
        return max(self.sigma_floor, self._base_sigma(source) * self.sigma_scale)

    def _maybe_calibrate_sigma(self) -> None:
        """用双源残差在线校正 σ 的整体尺度。

        两源误差独立时 E|d|² = 2(σa² + σb²)，因此实测/理论之比的平方根就是尺度。
        只调整体尺度、不改各源比例，并且限制在 [0.5, 3]，避免正反馈失控。
        """
        if not self.sigma_autocalib:
            return
        total = sum(st[3] for st in self._pair_stats.values())
        if total < self.sigma_calib_samples:
            return
        ratios: List[Tuple[float, float]] = []
        for (a, b), (sx, sy, s2, n) in self._pair_stats.items():
            if n < 20:
                continue
            # 方差 = E|d|² − |E[d]|²，剔除两源之间的固定偏差（标定误差）
            mean_x, mean_y = sx / n, sy / n
            var = max(0.0, s2 / n - (mean_x ** 2 + mean_y ** 2))
            expected = 2.0 * (self._base_sigma(a) ** 2 + self._base_sigma(b) ** 2)
            if expected <= 0:
                continue
            ratios.append((var / expected, n))
        if not ratios:
            return
        wsum = sum(n for _, n in ratios)
        new_scale = math.sqrt(sum(r * n for r, n in ratios) / wsum)
        new_scale = max(0.5, min(3.0, new_scale))
        self.sigma_scale = 0.7 * self.sigma_scale + 0.3 * new_scale
        self._pair_stats.clear()

    # ---- 局部 ENU（以航迹建轨点为原点，几十公里内误差可忽略）----
    @staticmethod
    def _to_local(t: "GlobalTrack", lat: float, lon: float) -> Tuple[float, float]:
        return ((lon - t.lon0) * _m_per_deg_lon(t.lat0),
                (lat - t.lat0) * M_PER_DEG_LAT)

    @staticmethod
    def _to_wgs(t: "GlobalTrack", x: float, y: float) -> Tuple[float, float]:
        return (t.lat0 + y / M_PER_DEG_LAT,
                t.lon0 + x / _m_per_deg_lon(t.lat0))

    def _track_sigma(self, t: "GlobalTrack") -> float:
        """航迹自身的融合不确定度：1/σ² 加权合成（_refresh 已缓存）。"""
        if t.err_sigma > 0:
            return t.err_sigma
        live = [s for s in t.sources.values() if s.sigma > 0]
        if not live:
            return self.default_sigma
        inv = sum(1.0 / (s.sigma ** 2) for s in live)
        return math.sqrt(1.0 / inv) if inv > 0 else self.default_sigma

    def _predict(self, t: "GlobalTrack", dt: float) -> Tuple[float, float]:
        """返回外推后的位置。

        有卡尔曼滤波器时：**帧首已经统一做了一次 predict**（见 ingest），
        这里只读状态，不再重复外推（否则同一帧里多条观测会把状态推进多次）。
        没有滤波器时退回原来的"速度/航向匀速外推"。
        """
        if t.kf is not None:
            x, y = t.kf.pos()
            return self._to_wgs(t, x, y)
        if dt <= 0.0 or dt > self.predict_horizon or t.speed < 1.0:
            return t.lat, t.lon
        rad = math.radians(t.heading)
        dx = math.sin(rad) * t.speed * dt
        dy = math.cos(rad) * t.speed * dt
        lat = t.lat + dy / M_PER_DEG_LAT
        lon = t.lon + dx / max(1.0, M_PER_DEG_LAT * math.cos(math.radians(t.lat)))
        return lat, lon

    def _motion_sigma(self, t: "GlobalTrack", dt: float) -> float:
        """外推误差：速度误差 + 航向误差 + 机动加速度。"""
        if dt <= 0.0:
            return 0.0
        if dt > self.predict_horizon:
            return self.v_max * dt / math.sqrt(3.0)
        v = max(t.speed, 1.0)
        return dt * math.hypot(self.sigma_speed, v * self.sigma_heading)             + 0.5 * self.accel_max * dt * dt

    def _gate_parts(self, o: Observation, t: "GlobalTrack", now: float):
        """返回 (卡尔曼门限, 经典门限)；没有滤波器时前者为 None。"""
        dt = max(0.0, now - t.last_seen)
        s_obs = o.sigma or self.sigma_of(o.source)
        s_trk = self._track_sigma(t)
        classic = self.gate_k * math.sqrt(s_obs ** 2 + s_trk ** 2
                                          + self._motion_sigma(t, dt) ** 2)
        kf_gate = None
        if t.kf is not None:
            zx, zy = self._to_local(t, o.lat, o.lon)
            _, s_eff = t.kf.innovation(zx, zy, s_obs)
            kf_gate = max(self.gate_k * s_eff, 1.0)
        scale = t.density_scale if self.density_gate else 1.0
        if scale != 1.0:
            classic *= scale
            if kf_gate is not None:
                kf_gate *= scale
        return kf_gate, classic

    def gate_and_distance(self, o: Observation, t: "GlobalTrack", now: float):
        """供影子模式构造特征用：返回 (距离, 实际门限, 卡尔曼门限, 经典门限)。"""
        kf_gate, classic = self._gate_parts(o, t, now)
        gate = classic if kf_gate is None else min(kf_gate, classic)
        dt = max(0.0, now - t.last_seen)
        plat, plon = self._predict(t, dt)
        d = distance_m(o.lat, o.lon, plat, plon)
        return d, gate, (kf_gate if kf_gate is not None else classic), classic

    def _gate(self, o: Observation, t: "GlobalTrack", now: float) -> float:
        """统计门限。

        有卡尔曼滤波器时用**马氏距离的等效 σ**：
            σ_eff = sqrt(νᵀ S ν / νᵀν)   —— 沿新息方向的方差（椭圆门限折算成标量）
            gate  = gate_k * σ_eff
        gate_k = 3.44 ≈ sqrt(χ²(2, 99.7%))，与原来的统计含义一致。
        没有滤波器时退回原来的"三个 σ 平方和"。
        """
        kf_gate, classic = self._gate_parts(o, t, now)
        if kf_gate is None:
            return classic
        # 取两者较小值：滤波协方差在"长时间无观测"时会按 σ_a²Δt⁴ 膨胀，
        # 单用它会放出一两百米的大跳变（实测把影子一致率从 100% 拉到 62%）
        return min(kf_gate, classic)

    # ---------------------------------------------------------- 匹配
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
            s_obs = o.sigma or self.sigma_of(o.source)
            gate = 1.5 * self.gate_k * math.sqrt(
                s_obs ** 2 + src.sigma ** 2 + (self.v_max * dt) ** 2 / 3.0)
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
        gate = self._gate(o, t, now)
        dt = max(0.0, now - t.last_seen)
        plat, plon = self._predict(t, dt)
        d = distance_m(o.lat, o.lon, plat, plon)
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
            lat0=o.lat, lon0=o.lon,
        )
        if self.use_kalman:
            s_obs = o.sigma or self.sigma_of(o.source)
            # 速度未知：给 15 m/s 的初始不确定度，让滤波器自己收敛
            t.kf = KalmanCV(0.0, 0.0, sigma_pos=s_obs, sigma_vel=15.0, sigma_a=self.kf_sigma_a)
        t.sources[o.source] = _SourceObs(o.track_id, o.lat, o.lon, o.alt_msl,
                                         o.speed, o.heading, o.ts, o.quality,
                                         o.sigma or self.sigma_of(o.source), o.payload)
        self.tracks[gid] = t
        if self._grid:
            key = (int(math.floor(t.lat / self.cell_deg)),
                   int(math.floor(t.lon / self.cell_deg)))
            self._grid.setdefault(key, []).append(gid)
        if o.ua_id:
            self.by_ua[o.ua_id] = gid
        if o.reg_no:
            self.by_reg[o.reg_no] = gid
        return t

    def _apply(self, t: GlobalTrack, o: Observation, now: float) -> None:
        """把一条观测并入已有航迹。"""
        t.sources[o.source] = _SourceObs(o.track_id, o.lat, o.lon, o.alt_msl,
                                         o.speed, o.heading, o.ts, o.quality,
                                         o.sigma or self.sigma_of(o.source), o.payload)
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
        """用各源最新观测重新计算融合位置与置信度。

        注意：这里**不能**做"同帧短路"——σ 自标定要依赖每次调用时的残差样本，
        短路会把标定饿死（实测 sigma_scale 一直停在 1.0）。
        """
        live_items = [(n, s) for n, s in t.sources.items() if now - s.ts <= self.ttl]
        if not live_items:
            return
        live = [s for _, s in live_items]
        # 只取最新时刻窗内的观测做融合（异步旧数据不参与位置计算）
        newest = max(s.ts for s in live)

        winners_items = [(n, s) for n, s in live_items
                         if newest - s.ts <= self.sync_window]
        winners = [s for _, s in winners_items]

        # σ 自标定：累计同一时刻两源的位置差平方（E|d|² = 2(σa²+σb²)）
        # 每个 (帧, 最新时刻) 只采一次：_refresh 一帧内会被调多次，
        # 重复采样会让 sigma_scale 被拉偏（实测影子一致率从 96% 掉到 81%）
        calib_key = (now, newest)
        if self.sigma_autocalib and len(winners_items) >= 2 and t._calib_key != calib_key:
            t._calib_key = calib_key
            for i, (na, a) in enumerate(winners_items):
                for nb, b in winners_items[i + 1:]:
                    k = (na, nb) if na <= nb else (nb, na)
                    dx = (b.lon - a.lon) * M_PER_DEG_LAT * math.cos(math.radians(a.lat))
                    dy = (b.lat - a.lat) * M_PER_DEG_LAT
                    st = self._pair_stats.get(k)
                    if st is None:
                        self._pair_stats[k] = [dx, dy, dx * dx + dy * dy, 1.0]
                    else:
                        st[0] += dx; st[1] += dy
                        st[2] += dx * dx + dy * dy; st[3] += 1.0

        # 一帧内可能被调用多次（分配后 / 合并后 / 帧尾），观测集合没变就直接返回
        key = (now, len(t.sources), newest)
        if t._refresh_key == key:
            return
        t._refresh_key = key

        def _w(s):
            # 逆方差加权（统计最优）× 时间衰减；没有 σ 时退回 quality
            base = (1.0 / (s.sigma ** 2)) if (s.sigma and s.sigma > 0) else max(s.quality, 1e-3)
            return base * (0.5 ** (max(0.0, newest - s.ts) / self.half_life))

        wsum = sum(_w(s) for s in live)
        if wsum <= 0:
            return

        # ---- 高度/速度：滤波器只管水平面，这两项仍用加权平均 ----
        t.alt_msl = sum(s.alt_msl * _w(s) for s in live) / wsum

        if t.kf is not None:
            # ---- 水平位置/速度：逐源喂进卡尔曼滤波器 ----
            # 每个源用自己的 σ 作为观测噪声 R，等价于"信息量加权"，而且顺带估出速度。
            # 注意两点：
            #   ① 异步到达的**旧观测**（超出同步窗口）只保留身份，不参与状态更新，
            #      否则会把移动目标的位置拖回上一帧；
            #   ② _refresh 一帧内可能被调用多次（分配后、合并后、帧尾），
            #      用 kf_applied 记下已应用的 ts，保证同一观测只进一次。
            for src, so in sorted(live_items, key=lambda kv: kv[1].ts):
                if newest - so.ts > self.sync_window:
                    continue
                if t.kf_applied.get(src, -1e18) >= so.ts:
                    continue
                zx, zy = self._to_local(t, so.lat, so.lon)
                t.kf.update(zx, zy, max(so.sigma, 1.0))
                t.kf_applied[src] = so.ts
            t.lat, t.lon = self._to_wgs(t, *t.kf.pos())
            t.err_sigma = max(t.kf.sigma(), 1.0)
            # 速度/航向优先用滤波估计：报文里的 speed/heading 经常缺失或跳变
            if t.kf.steps >= 3 and t.kf.speed() >= 0.5:
                t.speed = t.kf.speed()
                t.heading = t.kf.heading_deg()
            else:
                t.speed = sum(s.speed * _w(s) for s in live) / wsum
                t.heading = _circular_mean([(s.heading, _w(s)) for s in live])
        else:
            t.lat = sum(s.lat * _w(s) for s in live) / wsum
            t.lon = sum(s.lon * _w(s) for s in live) / wsum
            t.speed = sum(s.speed * _w(s) for s in live) / wsum
            t.heading = _circular_mean([(s.heading, _w(s)) for s in live])
            inv = sum(1.0 / (s.sigma ** 2) for s in live if s.sigma > 0)
            t.err_sigma = math.sqrt(1.0 / inv) if inv > 0 else self.default_sigma

        # 置信度：同一时刻窗内的源越多、越一致 -> 越高
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

        far = None
        for i, (na, a) in enumerate(live):
            for nb, b in live[i + 1:]:
                # 两源噪声差异大时，固定阈值会把"同一架的正常偏差"误判成两个目标
                gate_ab = max(2.0 * self.sigma_m,
                              self.gate_k * math.sqrt(a.sigma ** 2 + b.sigma ** 2))
                if distance_m(a.lat, a.lon, b.lat, b.lon) > gate_ab:
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
        # 拆完必须重置滤波器：刚才融合进来的位置/速度里带着"另一架"的痕迹，
        # 不重置的话被保留的那条要花好几帧才能把速度和位置拉回来
        if t.kf is not None:
            keep_src = next(iter(t.sources))
            so = t.sources[keep_src]
            kx, ky = self._to_local(t, so.lat, so.lon)
            t.kf = KalmanCV(kx, ky, sigma_pos=max(so.sigma, 1.0), sigma_vel=15.0, sigma_a=self.kf_sigma_a)
            t.kf_applied = {keep_src: so.ts}
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
