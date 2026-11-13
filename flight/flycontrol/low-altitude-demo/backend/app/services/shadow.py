# -*- coding: utf-8 -*-
"""影子模式（Shadow Mode）：让 RL 策略跟着线上规则一起跑，但**只记录不生效**。

为什么要有它
------------
策略是在仿真数据上训的，离线指标好不代表线上好（真实噪声、丢包、时钟漂移）。
直接切换风险太大：一次误配就把两架飞机并成一条，空管看到的态势是错的。
影子模式让策略先"当副驾驶"：每一帧都给出它的判断，写进日志，与规则的判断对比，
跑够一段时间、指标不劣于规则，再考虑灰度/全量。

数据流::

    实时观测 ──► DedupEngine（规则，生效）──► 对外输出
                    │
                    └──► ShadowMatcher（策略，不生效）──► logs/shadow.jsonl

用法::

    DEDUP_SHADOW=1            # 打开影子模式（默认关闭，零影响）
    DEDUP_SHADOW_LOG=...      # 可选，日志路径

设计约束
--------
* 纯 numpy 推理，不依赖 Paddle（1.5 µs/边，对线上无感）；
* 任何异常都被吞掉并降级为"停用"，绝不影响主流程；
* 特征顺序必须与训练时一致（见 ``FEATURE_NAMES``）。
"""
from __future__ import annotations

import collections
import json
import logging
import math
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

# 与 experiments/dedup_ml/sim.py 保持一致（策略就是在这个分布上训出来的）
V_MAX = 30.0
GATE_SIGMA = 3.0
ALT_GATE = 30.0
HEADING_GATE = 30.0
M_PER_DEG_LAT = 111320.0
DEFAULT_SIGMA = 20.0

FEATURE_NAMES = [
    "距离/门限", "绝对距离", "高差/30m", "航向差/30°", "Δt",
    "ua相同", "ua冲突", "ua缺失",
    "reg相同", "reg冲突",
    "速度相对差", "候选排名", "航迹存活时长/60",
    "源质量", "源σ/20", "低速标志",
    "最近邻航迹距离/100", "航迹总数/100", "门限膨胀比",
]

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_WEIGHTS = os.path.join(_BACKEND_ROOT, "experiments", "rl_dedup", "policy_weights.json")
DEFAULT_PARAMS = os.path.join(_BACKEND_ROOT, "experiments", "rl_dedup", "rl_params.json")


# ------------------------------------------------------------------ 策略推理


class ShadowPolicy:
    """纯 Python 的前向推理（不依赖 numpy/paddle，与训练时的网络逐位等价）。

    网络：18 → 64 → 64 → 1，约 5441 个参数；一层矩阵乘约 1.2k 次乘法，
    30 条边一帧不到 1 毫秒，对线上无感。
    """

    def __init__(self, weights_path: str, params_path: str):
        cfg = json.load(open(weights_path, encoding="utf-8"))
        self.features = list(cfg["features"])
        if len(self.features) != len(FEATURE_NAMES):
            raise ValueError("特征维度不一致: %d vs %d" % (len(self.features), len(FEATURE_NAMES)))
        self.mean = [float(v) for v in cfg["mean"]]
        self.std = [max(float(v), 1e-6) for v in cfg["std"]]
        w = cfg["weights"]
        # 权重在文件里是 [in, out]，转置成 [out][in] 便于逐行点积
        self.W0 = _transpose(w["enc0_w"])
        self.b0 = [float(v) for v in w["enc0_b"]]
        self.W2 = _transpose(w["enc2_w"])
        self.b2 = [float(v) for v in w["enc2_b"]]
        self.Wa = _transpose(w["actor_w"])
        self.ba = [float(v) for v in w["actor_b"]]

        self.threshold = 0.5
        self.params: dict = {}
        if os.path.exists(params_path):
            self.params = json.load(open(params_path, encoding="utf-8"))
            self.threshold = float(self.params.get("threshold", 0.5))

    def logits(self, feats: Sequence[Sequence[float]]) -> List[float]:
        out = []
        for f in feats:
            x = [(float(v) - m) / s for v, m, s in zip(f, self.mean, self.std)]
            h = [math.tanh(v) for v in _matvec(self.W0, x, self.b0)]
            h = [math.tanh(v) for v in _matvec(self.W2, h, self.b2)]
            out.append(_matvec(self.Wa, h, self.ba)[0])
        return out

    def score(self, feats: Sequence[Sequence[float]]) -> List[float]:
        res = []
        for z in self.logits(feats):
            z = max(-30.0, min(30.0, z))
            res.append(1.0 / (1.0 + math.exp(-z)))
        return res


# ------------------------------------------------------------------ 特征构造


def _transpose(w: Sequence[Sequence[float]]) -> List[List[float]]:
    """[in][out] → [out][in]。"""
    return [[float(row[j]) for row in w] for j in range(len(w[0]))] if w else []


def _matvec(W: Sequence[Sequence[float]], x: Sequence[float], b: Sequence[float]) -> List[float]:
    """(m×n) · (n) + (m)，纯 Python 实现。"""
    return [sum(wi * xi for wi, xi in zip(row, x)) + bi for row, bi in zip(W, b)]


def _angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def project(lat: float, lon: float, origin: Tuple[float, float]) -> Tuple[float, float]:
    """经纬度 → 局部平面米（等距圆柱近似，几十公里内误差 < 0.1%）。"""
    lat0, lon0 = origin
    y = (lat - lat0) * M_PER_DEG_LAT
    x = (lon - lon0) * M_PER_DEG_LAT * math.cos(math.radians(lat0))
    return x, y


def snapshot_tracks(tracks: Sequence[Any], origin: Tuple[float, float]) -> List[dict]:
    """把引擎的航迹拍成快照（策略需要"更新前"的候选集合）。"""
    snap = []
    for t in tracks:
        x, y = project(t.lat, t.lon, origin)
        snap.append({
            "gid": t.global_id, "x": x, "y": y, "z": t.alt_msl,
            "heading": t.heading, "speed": t.speed,
            "ua_id": t.ua_id, "reg_no": t.reg_no,
            "last_t": t.last_seen, "seen": max(1, int(t.hits)),
            "first_t": t.first_seen,
            "ref": t,                        # 引擎航迹对象，用来问门限
        })
    return snap


def build_edges(observations: Sequence[Any], snap: Sequence[dict],
                t: float, origin: Tuple[float, float], gate_fn=None):
    """构造 (特征, 元信息, 硬约束掩码)，与训练时的 env.py 完全对齐。"""
    # 航迹间最近邻距离（场景密度）
    n = len(snap)
    nn = []
    for i, a in enumerate(snap):
        best = 999.0
        for j, b in enumerate(snap):
            if i == j:
                continue
            d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            if d < best:
                best = d
        nn.append(best)

    feats: List[List[float]] = []
    meta: List[Tuple[int, int]] = []
    hard: List[float] = []

    for oi, o in enumerate(observations):
        ox, oy = project(o.lat, o.lon, origin)
        sigma = float(o.sigma) if o.sigma is not None else DEFAULT_SIGMA
        order = sorted(range(n), key=lambda ti: (ox - snap[ti]["x"]) ** 2 + (oy - snap[ti]["y"]) ** 2)
        for rank, ti in enumerate(order):
            tr = snap[ti]
            dt = max(0.0, t - float(tr["last_t"]))
            d = math.hypot(ox - tr["x"], oy - tr["y"])
            gate = V_MAX * dt + GATE_SIGMA * sigma
            d_over_gate = d / gate if gate > 0 else 99.0
            d_alt = abs(float(o.alt_msl) - tr["z"])
            d_hdg = _angle_diff(float(o.heading), tr["heading"])

            ua_same = 1.0 if (o.ua_id and tr["ua_id"] and o.ua_id == tr["ua_id"]) else 0.0
            ua_conflict = 1.0 if (o.ua_id and tr["ua_id"] and o.ua_id != tr["ua_id"]) else 0.0
            ua_missing = 1.0 if (o.ua_id is None or tr["ua_id"] is None) else 0.0
            reg_same = 1.0 if (o.reg_no and tr["reg_no"] and o.reg_no == tr["reg_no"]) else 0.0
            reg_conflict = 1.0 if (o.reg_no and tr["reg_no"] and o.reg_no != tr["reg_no"]) else 0.0

            speed_rel = abs(float(o.speed) - tr["speed"]) / max(1.0, tr["speed"])
            slow = 1.0 if min(float(o.speed), tr["speed"]) < 2.0 else 0.0

            # 门限：优先问生产引擎（卡尔曼自适应门限），拿不到就用训练时的老公式
            ratio = 1.0
            if gate_fn is not None and tr.get("ref") is not None:
                try:
                    d_kf, gate_used, gate_kf, gate_classic = gate_fn(o, tr["ref"])
                    d_over_gate = d_kf / max(gate_used, 1e-6)
                    ratio = min(gate_kf / max(gate_classic, 1e-6), 3.0)
                except Exception:
                    d_over_gate = d_over_gate if gate > 0 else 99.0
            feats.append([
                min(d_over_gate, 5.0),
                d / 100.0,
                d_alt / 30.0,
                d_hdg / 30.0,
                dt,
                ua_same, ua_conflict, ua_missing,
                reg_same, reg_conflict,
                speed_rel,
                float(rank),
                min(max(0.0, t - float(tr.get("first_t", t))), 60.0) / 60.0,
                float(o.quality),
                sigma / 20.0,
                slow,
                min(nn[ti], 999.0) / 100.0,
                n / 100.0,
                ratio,
            ])
            meta.append((oi, ti))
            hard.append(ua_conflict)
    return feats, meta, hard


def decode(probs: Sequence[float], threshold: float, meta: Sequence[Tuple[int, int]],
           hard: Sequence[float], sources: Sequence[str],
           order_key: Optional[Sequence[float]] = None,
           tie_break: Optional[Sequence[float]] = None) -> Dict[int, int]:
    """阈值 + 贪心一对一（与 env.step 的解码规则一致）。

    order_key 用 logit 而不是概率来排序：sigmoid 会饱和（很多边都是 1.000），
    概率相同就变成随机排序，而同源对同一条航迹只能配一次，随机排序会误伤。
    """
    key = order_key if order_key is not None else probs
    tb = tie_break if tie_break is not None else [0.0] * len(probs)
    # 主键：logit；次键：距离（规则是连续打分，天然按距离，这里对齐它）
    order = sorted((k for k in range(len(probs)) if hard[k] < 0.5),
                   key=lambda k: (-key[k], tb[k]))
    used_obs, used_pair = set(), set()
    picked: Dict[int, int] = {}
    for k in order:
        if probs[k] < threshold:
            break
        oi, ti = meta[k]
        key = (sources[oi], ti)
        if oi in used_obs or key in used_pair:
            continue
        used_obs.add(oi)
        used_pair.add(key)
        picked[oi] = ti
    return picked


# ------------------------------------------------------------------ 影子主体


class ShadowMatcher:
    """把策略的判断记录下来，与线上规则比对。任何异常都不影响主流程。"""

    def __init__(self, weights_path: str = "", params_path: str = "", log_path: str = ""):
        self.enabled = False
        self.reason = ""
        self.frames = 0
        self.edges = 0
        self.observations = 0
        self.agree = 0
        self.policy_extra = 0      # 策略合并了、规则没合
        self.policy_missed = 0     # 规则合并了、策略没合
        self.both_new = 0          # 两边都判为新目标
        self.structural = 0        # 规则匹配到本帧新建的航迹（策略快照里没有）
        self.policy = None
        self.log_path = log_path or os.environ.get("DEDUP_SHADOW_LOG", "") or \
            os.path.join(_BACKEND_ROOT, "logs", "shadow.jsonl")
        self._lock = threading.Lock()
        self._fp = None
        self.recent = collections.deque(maxlen=400)   # 供 /api/rl/live 回放

        self._wp = weights_path or os.environ.get("DEDUP_POLICY_FILE", "") or DEFAULT_WEIGHTS
        self._pp = params_path or DEFAULT_PARAMS
        if self._load_policy():
            self.enabled = True
            log.info("影子模式已启用 | 阈值 %.2f | 日志 %s", self.policy.threshold, self.log_path)

    # -------------------------------------------------------------- 加载/开关
    def _load_policy(self) -> bool:
        try:
            if not os.path.exists(self._wp):
                self.reason = "策略文件不存在: %s" % self._wp
                return False
            if self.policy is None:
                self.policy = ShadowPolicy(self._wp, self._pp)
                os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
            return True
        except Exception as exc:                      # 绝不影响主流程
            self.reason = "初始化失败: %s" % exc
            log.warning("影子模式初始化失败: %s", exc)
            return False

    def set_enabled(self, on: bool, reset: bool = False) -> dict:
        """运行时开关（演示台用，不必改环境变量重启）。"""
        if on:
            if not self._load_policy():
                self.enabled = False
                return self.stats()
            self.enabled = True
            self.reason = "已开启"
            log.info("影子模式运行中开启 | 阈值 %.2f", self.policy.threshold)
        else:
            self.enabled = False
            self.reason = "已关闭"
        if reset:
            self.reset()
        return self.stats()

    def reset(self) -> None:
        """清零计数与缓冲（演示时重新开始）。"""
        with self._lock:
            self.frames = self.edges = self.observations = 0
            self.agree = self.policy_extra = self.policy_missed = 0
            self.both_new = self.structural = 0
            self.recent.clear()

    # -------------------------------------------------------------- 主入口
    def observe(self, observations: Sequence[Any], snap: Sequence[dict],
                origin: Tuple[float, float], t: float, rule_pick: Dict[int, str],
                gate_fn=None) -> None:
        """跟跑一帧：算策略判断 → 与规则比对 → 写日志。

        rule_pick: {观测下标: 规则给的 global_id}（新目标也在其中）
        """
        if not self.enabled or not observations:
            return
        try:
            feats, meta, hard = build_edges(observations, snap, t, origin, gate_fn)
            if not feats:
                return
            logits = self.policy.logits(feats)
            probs = [1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))) for z in logits]
            picked = decode(probs, self.policy.threshold, meta, hard,
                            [o.source for o in observations], order_key=logits,
                            tie_break=[f[1] for f in feats])
            gid_of = {i: s["gid"] for i, s in enumerate(snap)}

            # 规则的选择 → 快照下标（新目标不在快照里，记 -1）
            idx_of_gid = {s["gid"]: i for i, s in enumerate(snap)}
            rows = []
            with self._lock:
                self.frames += 1
                self.edges += len(feats)
                seen_batch = set()
                for oi, o in enumerate(observations):
                    batch_key = (o.source, o.track_id)
                    if batch_key in seen_batch:
                        continue          # 同一帧内重复转发（幂等），不重复计分
                    seen_batch.add(batch_key)
                    rule_gid = rule_pick.get(oi)
                    pol_gid = gid_of.get(picked[oi]) if oi in picked else None
                    if rule_gid is None:
                        continue
                    if rule_gid not in idx_of_gid:
                        self.structural += 1     # 同帧新建的航迹，快照里没有
                        continue
                    agree = (rule_gid == pol_gid)
                    if agree:
                        self.agree += 1
                    elif rule_gid not in idx_of_gid and pol_gid is not None:
                        self.policy_extra += 1
                    elif rule_gid in idx_of_gid and pol_gid is None:
                        self.policy_missed += 1
                    elif rule_gid in idx_of_gid and pol_gid is not None:
                        self.policy_extra += 1     # 并到了另一条航迹
                    else:
                        self.both_new += 1
                    ks = [k for k, (i, _) in enumerate(meta) if i == oi]
                    pk = max(ks, key=lambda k: probs[k]) if ks else None
                    p = probs[pk] if pk is not None else 0.0
                    rows.append({
                        "frame": self.frames, "src": o.source, "lid": o.track_id,
                        "ua_id": o.ua_id, "rule_gid": rule_gid, "policy_gid": pol_gid,
                        "p_max": round(float(p), 4), "agree": agree,
                        # 把这条观测最高分候选边的 18 维特征一并存下来：
                        # 页面可以"点一行 → 在神经网络里看这条边"
                        "feat": ([round(float(v), 3) for v in feats[pk]] if pk is not None else None),
                    })
                self.observations += len(seen_batch)   # 只算去重后的观测
                self._write(rows)
        except Exception as exc:                      # 影子出错不影响业务
            log.debug("影子模式单帧失败: %s", exc)

    def recent_rows(self, n: int = 60) -> List[dict]:
        """最近 n 条判定（供可视化页面回放）。"""
        with self._lock:
            items = list(self.recent)[-max(1, min(int(n), 400)):]
        return items[::-1]          # 最新的在前

    def _write(self, rows: List[dict]) -> None:
        if not rows:
            return
        self.recent.extend(rows)
        try:
            if self._fp is None:
                self._fp = open(self.log_path, "a", encoding="utf-8")
            ts = round(time.time(), 3)
            for r in rows:
                r["ts"] = ts
                self._fp.write(json.dumps(r, ensure_ascii=False) + "\n")
            self._fp.flush()
        except Exception as exc:
            log.debug("影子日志写入失败: %s", exc)

    # -------------------------------------------------------------- 对外
    def stats(self) -> dict:
        total = max(1, self.agree + self.policy_extra + self.policy_missed + self.both_new)
        return {
            "enabled": self.enabled,
            "reason": self.reason,
            "threshold": (self.policy.threshold if self.policy else None),
            "frames": self.frames, "edges": self.edges, "observations": self.observations,
            "agree": self.agree, "policy_extra": self.policy_extra,
            "policy_missed": self.policy_missed, "both_new": self.both_new,
            "structural": self.structural,
            "agree_rate": round(1.0 - (self.policy_extra + self.policy_missed) / total, 4),
            "log": self.log_path,
        }


def build_from_env() -> ShadowMatcher:
    """按环境变量构造；DEDUP_SHADOW 未开启时返回一个 enabled=False 的空壳。"""
    shadow = ShadowMatcher()
    if os.environ.get("DEDUP_SHADOW", "0") not in ("1", "true", "True", "yes"):
        shadow.enabled = False
        shadow.reason = "未开启（DEDUP_SHADOW=1 打开）"
    return shadow
