# -*- coding: utf-8 -*-
"""把「多设备航迹关联」建成强化学习环境（MDP）。

为什么是 MDP 而不是一次性分类：
    这一帧把观测 A 并进航迹 T，会改变下一帧的候选集合（航迹位置/速度/ID 都会变），
    所以是**序贯决策**；而"并错"的代价在后续帧才完全体现（错误航迹会继续吸观测）。

状态（每一步）：
    edges = 本帧所有候选 (观测 i, 航迹 j) 的 16 维特征（与监督学习实验完全一致）
动作：
    对每条边给一个 [0,1] 的"同一架"概率；用阈值 + 贪心一对一解码成关联结果
奖励（非对称，安全优先）：
    正确配对 +1    错配 −10    漏配（本该能配上却没配） −1
    新目标（本来就没有航迹） 0
"""

from __future__ import annotations

import math
import os
import sys
from typing import List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "dedup_ml"))   # sim.py
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))            # backend/（app.services.kalman）

import sim  # noqa: E402

from app.services.kalman import KalmanCV  # noqa: E402

# 非对称但不过度：错配 6 倍于漏配（原来 10:1 会让策略学成"一律不合并"）
W_FALSE_MERGE = -6.0
W_FALSE_MISS = -2.0
W_TRUE_MATCH = 1.0

# 上下文特征：让策略能区分"稀疏空域"和"密集蜂群"
CONTEXT_NAMES = ["最近邻航迹距离/100", "航迹总数/100", "门限膨胀比"]
GATE_K = 3.44          # 与生产引擎的 gate_k 一致（≈√χ²(2, 99.7%)）
SIGMA_SPEED = 1.5      # 与生产引擎 dedup.sigma_speed 一致
SIGMA_HEADING = 8.0    # 度，与 dedup.sigma_heading_deg 一致
ACCEL_MAX = 2.0        # m/s²，与 dedup.accel_max 一致
KF_SIGMA_A = 2.0       # 机动噪声：盘旋时向心加速度 ~7 m/s²，2.0 太小


class Track:
    __slots__ = ("truth", "x", "y", "z", "heading", "speed", "ua_id", "reg_no",
                 "last_t", "seen", "sources", "frag_of", "kf", "first_t")

    def __init__(self, o: sim.Observation, t: float):
        self.truth = o.truth
        self.x, self.y, self.z = o.x, o.y, o.z
        self.heading, self.speed = o.heading, o.speed
        self.ua_id, self.reg_no = o.ua_id, o.reg_no
        self.last_t = t
        self.first_t = t
        self.seen = 1
        self.sources = {o.src: o}
        self.frag_of = o.truth
        # 与生产引擎一致的匀速模型滤波器（特征里的"门限"要来自它）
        self.kf = KalmanCV(o.x, o.y, sigma_pos=o.sigma or 20.0, sigma_vel=15.0, sigma_a=KF_SIGMA_A)

    def as_state(self) -> sim.TrackState:
        return sim.TrackState(truth=self.truth, x=self.x, y=self.y, z=self.z,
                              heading=self.heading, speed=self.speed,
                              ua_id=self.ua_id, reg_no=self.reg_no,
                              last_t=self.last_t, seen=self.seen)

    def update(self, o: sim.Observation, t: float):
        # 逆方差加权融合
        w_old = 1.0 / (0.5 * (self.sources[list(self.sources)[0]].sigma ** 2))
        items = list(self.sources.values()) + [o]
        wsum = sum(1.0 / (s.sigma ** 2) for s in items)
        self.x = sum(s.x / (s.sigma ** 2) for s in items) / wsum
        self.y = sum(s.y / (s.sigma ** 2) for s in items) / wsum
        self.z = sum(s.z / (s.sigma ** 2) for s in items) / wsum
        self.heading = sum(s.heading / (s.sigma ** 2) for s in items) / wsum
        self.speed = sum(s.speed / (s.sigma ** 2) for s in items) / wsum
        if o.ua_id and not self.ua_id:
            self.ua_id = o.ua_id
        if o.reg_no and not self.reg_no:
            self.reg_no = o.reg_no
        self.sources[o.src] = o
        self.last_t = t
        self.seen += 1
        self.kf.update(o.x, o.y, max(o.sigma or 20.0, 1.0))


class AssociationEnv:
    """一局 = 一个场景的完整回放。"""

    def __init__(self, scenario: str, level: str = "hard", frames: int = 40,
                 seed: int = 0, n_planes: int = 12, ttl: float = 15.0,
                 v_max: float = 30.0):
        self.data = sim.generate(scenario, n_planes=n_planes, frames=frames,
                                 seed=seed, level=level)
        self.ttl = ttl
        self.v_max = v_max
        self.tracks: List[Track] = []
        self.k = 0
        self.ep_return = 0.0
        self.truth_tracks = {}
        self.reset()

    # ------------------------------------------------------------------
    def reset(self):
        self.tracks = []
        self.k = 0
        self.ep_return = 0.0
        self.truth_tracks = {}
        return self._edges()

    def feature_names(self):
        return list(sim.FEATURE_NAMES) + CONTEXT_NAMES

    @property
    def feature_dim(self):
        return len(sim.FEATURE_NAMES) + len(CONTEXT_NAMES)

    def _edges(self) -> dict:
        """构造当前帧的候选边（特征、元信息、掩码）。"""
        if self.k >= len(self.data):
            return {"done": True}
        fr = self.data[self.k]
        t, obs = fr["t"], fr["obs"]
        # 每条航迹到其它航迹的最近距离（判断场景密度）
        nn = []
        for i, tr in enumerate(self.tracks):
            best = 999.0
            for j, other in enumerate(self.tracks):
                if i == j:
                    continue
                d = math.hypot(tr.x - other.x, tr.y - other.y)
                if d < best:
                    best = d
            nn.append(best)
        n_tracks = len(self.tracks)

        # 卡尔曼：每帧预测一次（与本帧所有候选边共用）
        for tr in self.tracks:
            tr.kf.predict(max(0.0, t - tr.last_t), KF_SIGMA_A)

        feats, meta, masked, rules = [], [], [], []
        for oi, o in enumerate(obs):
            order = sorted(range(len(self.tracks)),
                           key=lambda ti: (o.x - self.tracks[ti].x) ** 2 +
                                          (o.y - self.tracks[ti].y) ** 2)
            for rank, ti in enumerate(order):
                tr = self.tracks[ti]
                f, _, rule = sim.pair_features(o, tr.as_state(), t, rank)

                # ---- 门限改用卡尔曼（与生产引擎一致，且取经典式封顶）----
                d = math.hypot(o.x - tr.kf.px, o.y - tr.kf.py)
                # 与生产引擎 dedup._gate_parts 完全对齐：
                #   classic = gate_k * sqrt(σ_obs² + σ_trk² + σ_motion²)
                #   kf      = gate_k * σ_eff（马氏距离沿新息方向的等效 σ）
                sigma = max(o.sigma or 20.0, 1.0)
                _, s_eff = tr.kf.innovation(o.x, o.y, sigma)
                gate_kf = max(GATE_K * s_eff, 1.0)
                dt = max(0.0, t - tr.last_t)
                s_trk = sigma                      # 单源航迹的融合不确定度 ≈ 观测 σ
                motion = (dt * math.hypot(SIGMA_SPEED,
                                          (o.speed or 0.0) * math.radians(SIGMA_HEADING))
                          + 0.5 * ACCEL_MAX * dt * dt)
                gate_classic = GATE_K * math.sqrt(sigma ** 2 + s_trk ** 2 + motion ** 2)
                gate = min(gate_kf, gate_classic)
                ratio = min(gate_kf / max(gate_classic, 1e-6), 3.0)
                f[0] = min(d / max(gate, 1e-6), 5.0)          # 距离/门限（自适应门限）
                f[1] = d / 100.0
                # 第 13 维原来是"命中次数"，会随上报频率线性放大（10 Hz 时严重出分布）；
                # 改成"存活时长"（秒/60），对上报频率不变
                f[12] = min(max(0.0, t - tr.first_t), 60.0) / 60.0
                f = f + [min(nn[ti], 999.0) / 100.0, n_tracks / 100.0, ratio]
                # 身份冲突是硬约束：直接屏蔽
                hard = 1.0 if (o.ua_id and tr.ua_id and o.ua_id != tr.ua_id) else 0.0
                feats.append(f)
                meta.append((oi, ti))
                masked.append(hard)
                rules.append(rule)
        return {"done": False, "t": t, "obs": obs, "feats": feats,
                "meta": meta, "masked": masked, "rules": rules}

    # ------------------------------------------------------------------
    def step_actions(self, probs: List[float], actions: List[int]):
        """按二值动作推进；用概率给已接受的边排序（同源冲突时概率高的优先）。"""
        scores = [1.0 + probs[k] if actions[k] > 0.5 else 0.0
                  for k in range(len(actions))]
        return self.step(scores)

    def step(self, scores: List[float]) -> Tuple[dict, float, bool, dict]:
        """按给定分数解码关联、推进环境，返回 (下一状态, 奖励, 结束, 信息)。"""
        st = self._edges()
        if st["done"]:
            return st, 0.0, True, {}
        feats, meta, masked = st["feats"], st["meta"], st["masked"]
        obs, t = st["obs"], st["t"]

        # ---- 解码：阈值 + 贪心一对一（同源对同一条航迹只能一次）----
        order = sorted((k for k in range(len(scores)) if masked[k] < 0.5),
                       key=lambda k: -scores[k])
        used_o, used_ts, matched = set(), set(), {}
        for k in order:
            if scores[k] < 0.5:
                break
            oi, ti = meta[k]
            key = (obs[oi].src, ti)
            if oi in used_o or key in used_ts:
                continue
            used_o.add(oi); used_ts.add(key); matched[oi] = ti

        # ---- 结算奖励（逐边，便于策略学习） ----
        reward = 0.0
        n_wrong = n_miss = n_true = 0
        truth_has_track = {tr.truth for tr in self.tracks}
        accepted_set = {(oi, ti) for oi, ti in matched.items()}

        # 每架观测只认「最近的那条同真值航迹」为漏配责任边，
        # 否则一条真值对应多条重复航迹时，惩罚会随碎片数放大（正反馈）
        best_true = {}
        best_d = {}
        for k, (oi, ti) in enumerate(meta):
            if self.tracks[ti].truth != obs[oi].truth:
                continue
            d = (obs[oi].x - self.tracks[ti].x) ** 2 + (obs[oi].y - self.tracks[ti].y) ** 2
            if oi not in best_d or d < best_d[oi]:
                best_d[oi] = d
                best_true[oi] = (oi, ti)

        edge_rewards = []
        for k, (oi, ti) in enumerate(meta):
            same = (self.tracks[ti].truth == obs[oi].truth)
            taken = (oi, ti) in accepted_set
            if taken and same:
                er = W_TRUE_MATCH
            elif taken and not same:
                er = W_FALSE_MERGE
            elif (not taken) and same and best_true.get(oi) == (oi, ti):
                er = W_FALSE_MISS
            else:
                er = 0.0
            edge_rewards.append(er)

        for oi, o in enumerate(obs):
            if oi in matched:
                if self.tracks[matched[oi]].truth == o.truth:
                    n_true += 1
                else:
                    n_wrong += 1
            elif o.truth in truth_has_track:
                n_miss += 1
        reward = sum(edge_rewards)

        # ---- 状态转移 ----
        new_tracks = []
        created = 0
        for oi, o in enumerate(obs):
            if oi in matched:
                tr = self.tracks[matched[oi]]
                tr.update(o, t)
                if tr not in new_tracks:
                    new_tracks.append(tr)
            else:
                tr = Track(o, t)
                new_tracks.append(tr)
                self.truth_tracks.setdefault(o.truth, set()).add(id(tr))
                created += 1
        # 保留未更新的旧航迹（TTL 内）
        for tr in self.tracks:
            if tr not in new_tracks and (t - tr.last_t) <= self.ttl:
                new_tracks.append(tr)
        self.tracks = new_tracks
        self.k += 1
        self.ep_return += reward
        info = {"true": n_true, "wrong": n_wrong, "miss": n_miss,
                "created": created, "edge_rewards": edge_rewards}
        return self._edges(), reward, self.k >= len(self.data), info

    # ------------------------------------------------------------------
    def run_policy(self, score_fn) -> dict:
        """用给定的打分函数（特征, 规则分）跑完一局，返回累计统计。"""
        st = self.reset()
        tot = {"reward": 0.0, "true": 0, "wrong": 0, "miss": 0, "created": 0, "steps": 0}
        while not st.get("done"):
            sc = [score_fn(f, ru) for f, ru in zip(st["feats"], st["rules"])]
            st, r, done, info = self.step(sc)
            tot["reward"] += r
            for k in ("true", "wrong", "miss", "created"):
                tot[k] += info.get(k, 0)
            tot["steps"] += 1
        # 碎片：每架真值在整局里落到过几条航迹
        frag = self.truth_tracks
        tot["avg_frags"] = (sum(len(v) for v in frag.values()) / max(1, len(frag)))
        tot["split_ratio"] = (sum(1 for v in frag.values() if len(v) > 1)
                              / max(1, len(frag)))
        return tot
