# -*- coding: utf-8 -*-
"""卡尔曼滤波 · 航迹跟踪与预测（对应需求 4.2「航迹跟踪与预测（卡尔曼滤波）」）

用途
----
把 ADS-B / RID 的带噪、低更新率、可能丢包的观测，变成平滑的位置/速度估计，
并在丢包期间用运动模型外推，供态势图与冲突探测使用。

模型
----
匀速直线模型（Constant Velocity, CV），状态量::

    x = [px, py, vx, vy]^T          单位: 米, 米/秒

    F(dt) = [[1, 0, dt, 0],
             [0, 1, 0, dt],
             [0, 0, 1,  0],
             [0, 0, 0,  1]]

    H = [[1, 0, 0, 0],               # 只观测位置
         [0, 1, 0, 0]]

    Q(dt) = sigma_a^2 * [[dt^4/4, 0,      dt^3/2, 0     ],
                         [0,      dt^4/4, 0,      dt^3/2],
                         [dt^3/2, 0,      dt^2,   0     ],
                         [0,      dt^3/2, 0,      dt^2  ]]

    R = diag(sigma_xy^2, sigma_xy^2)   # 观测噪声（RID 比 ADS-B 精度高，可分开设）

用法
----
单个目标::

    kf = KalmanTrack("UAS-0001", sigma_xy=8.0, sigma_a=1.5)
    for t, (x, y) in observations:
        kf.predict(t)            # 先预测到当前时刻
        if (x, y) is not None:
            kf.update((x, y))    # 有观测就校正
        print(kf.position, kf.speed)

多个目标::

    tm = TrackManager()
    tracks = tm.step(t, [("UAS-0001", 120.0, -30.0), ("UAS-0002", 200.0, 10.0)])
    # 返回 {track_id: (px, py)}

依赖：numpy（工程 requirements.txt 已包含）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

__all__ = ["KalmanTrack", "TrackManager", "TrackState"]


@dataclass
class TrackState:
    """对外输出的航迹状态（已滤波）。"""

    track_id: str
    px: float
    py: float
    vx: float
    vy: float
    updated: bool = True      # 本帧是否有观测（False 表示纯预测）
    age: float = 0.0          # 距上一次观测的秒数


class KalmanTrack:
    """单目标匀速模型卡尔曼滤波器。

    参数
    ----
    track_id : 目标标识（呼号 / RID 编号）
    dt       : 初始采样周期，秒。之后每次 predict(t) 会按真实时间差计算
    sigma_xy : 观测噪声标准差，米（RID 可取 5~10，ADS-B 可取 20~50）
    sigma_a  : 过程噪声（机动加速度标准差），m/s²。越大越"跟得快"，越小越平滑
    gate_chi2: 新息门限（NIS，2 自由度卡方）。None 表示不做门限
    """

    def __init__(self, track_id: str, dt: float = 1.0,
                 sigma_xy: float = 8.0, sigma_a: float = 1.5,
                 gate_chi2: Optional[float] = None):
        self.track_id = track_id
        self.sigma_xy = float(sigma_xy)
        self.sigma_a = float(sigma_a)
        self.gate_chi2 = gate_chi2

        self.x = np.zeros(4, dtype=float)        # [px, py, vx, vy]
        self.P = np.diag([1e4, 1e4, 1e3, 1e3])   # 初始协方差（"什么都不知道"）
        self.last_t: Optional[float] = None
        self.t: float = 0.0

        self._initialized = False
        self._init_count = 0
        self._first_t: Optional[float] = None
        self._dt_default = float(dt)
        self.last_nis: Optional[float] = None

    # ------------------------------------------------------------------ 内部
    @staticmethod
    def _F(dt: float) -> np.ndarray:
        return np.array([[1, 0, dt, 0],
                         [0, 1, 0, dt],
                         [0, 0, 1, 0],
                         [0, 0, 0, 1]], dtype=float)

    @staticmethod
    def _H() -> np.ndarray:
        return np.array([[1, 0, 0, 0],
                         [0, 1, 0, 0]], dtype=float)

    def _Q(self, dt: float) -> np.ndarray:
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        q = np.array([[dt4 / 4, 0, dt3 / 2, 0],
                      [0, dt4 / 4, 0, dt3 / 2],
                      [dt3 / 2, 0, dt2, 0],
                      [0, dt3 / 2, 0, dt2]], dtype=float)
        return q * (self.sigma_a ** 2)

    def _R(self) -> np.ndarray:
        return np.eye(2) * (self.sigma_xy ** 2)

    # ------------------------------------------------------------------ 对外
    @property
    def position(self) -> Tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self) -> Tuple[float, float]:
        return float(self.x[2]), float(self.x[3])

    @property
    def speed(self) -> float:
        return float(np.hypot(self.x[2], self.x[3]))

    @property
    def covariance(self) -> np.ndarray:
        """位置协方差 2x2，可用来画不确定度椭圆。"""
        return self.P[:2, :2].copy()

    def predict(self, t: Optional[float] = None) -> Tuple[float, float]:
        """时间推进到 t（秒）。无观测时也可单独调用，用于丢包外推。"""
        if t is None:
            t = (self.last_t if self.last_t is not None else 0.0) + self._dt_default
        dt = self._dt_default if self.last_t is None else max(0.0, t - self.last_t)
        self.last_t = t
        self.t = t
        self.x = self._F(dt) @ self.x
        self.P = self._F(dt) @ self.P @ self._F(dt).T + self._Q(dt)
        return self.position

    def update(self, z: Sequence[float]) -> Tuple[float, float]:
        """用一次位置观测 (x, y) 校正。首次调用时直接以观测初始化位置。"""
        z = np.asarray(z, dtype=float).reshape(2)

        if not self._initialized:
            # 第一次观测：只知道位置，速度未知（给大方差）
            self.x[:2] = z
            self.x[2:] = 0.0
            self.P = np.diag([self.sigma_xy ** 2, self.sigma_xy ** 2, 100.0, 100.0])
            self._initialized = True
            self._init_count = 1
            self._first_t = self.t
            return self.position

        H = self._H()
        R = self._R()
        y = z - H @ self.x                       # 新息
        S = H @ self.P @ H.T + R                 # 新息协方差
        S_inv = np.linalg.inv(S)
        self.last_nis = float(y @ S_inv @ y)

        # 新息门限：明显离群（如目标身份串号）则丢弃本次观测
        if self.gate_chi2 is not None and self.last_nis > self.gate_chi2:
            return self.position

        K = self.P @ H.T @ S_inv                 # 卡尔曼增益
        self.x = self.x + K @ y

        I = np.eye(4)
        IKH = I - K @ H
        # Joseph 形式，数值更稳定
        self.P = IKH @ self.P @ IKH.T + K @ R @ K.T
        return self.position

    def predict_ahead(self, seconds: float) -> Tuple[float, float]:
        """从现在起向未来外推 seconds 秒（不改变滤波器状态）。"""
        px, py = self.position
        vx, vy = self.velocity
        return px + vx * seconds, py + vy * seconds

    def matrix_snapshot(self) -> dict:
        """便于教学/调试：导出当前矩阵。"""
        return {"x": self.x.copy(), "P": self.P.copy(),
                "position_sigma_m": float(np.sqrt(max(self.P[0, 0], 0.0)))}


@dataclass
class TrackManager:
    """多目标管理：按目标 ID 维护滤波器，自动新建 / 老化删除。"""

    sigma_xy: float = 8.0
    sigma_a: float = 1.5
    max_age: float = 10.0                     # 超过该秒数无观测则删除航迹
    gate_chi2: Optional[float] = None
    tracks: Dict[str, KalmanTrack] = field(default_factory=dict)
    _last_seen: Dict[str, float] = field(default_factory=dict)

    def get(self, track_id: str) -> Optional[KalmanTrack]:
        return self.tracks.get(track_id)

    def step(self, t: float,
             observations: Iterable[Tuple[str, float, float]]) -> Dict[str, TrackState]:
        """推进一帧。

        参数
        ----
        t            : 当前时刻，秒
        observations : [(track_id, x, y), ...]，本帧收到的观测（可为空）

        返回
        ----
        {track_id: TrackState}
        """
        obs = list(observations)
        seen = set()

        # 1) 所有航迹先做时间推进（覆盖丢包场景）
        for track in self.tracks.values():
            track.predict(t)

        # 2) 有观测的做校正；新目标则新建滤波器
        for tid, x, y in obs:
            track = self.tracks.get(tid)
            if track is None:
                track = KalmanTrack(tid, dt=1.0, sigma_xy=self.sigma_xy,
                                    sigma_a=self.sigma_a, gate_chi2=self.gate_chi2)
                track.predict(t)
                self.tracks[tid] = track
            track.update((x, y))
            seen.add(tid)
            self._last_seen[tid] = t

        # 3) 老化删除
        for tid in list(self.tracks.keys()):
            if t - self._last_seen.get(tid, t) > self.max_age:
                del self.tracks[tid]
                self._last_seen.pop(tid, None)

        # 4) 输出
        out: Dict[str, TrackState] = {}
        for tid, track in self.tracks.items():
            px, py = track.position
            vx, vy = track.velocity
            out[tid] = TrackState(tid, px, py, vx, vy,
                                  updated=tid in seen,
                                  age=t - self._last_seen.get(tid, t))
        return out


# ---------------------------------------------------------------------- 自测
if __name__ == "__main__":
    # 直线匀速目标：每秒观测一次，加 10 m 噪声，第 6~8 秒丢包
    rng = np.random.default_rng(7)
    kf = KalmanTrack("TEST-1", sigma_xy=10.0, sigma_a=1.0)
    px, py, vx, vy = 0.0, 0.0, 12.0, 5.0
    err_raw, err_kf = [], []

    for k in range(1, 16):
        t = float(k)
        px, py = px + vx, py + vy                 # 真值
        drop = 6 <= k <= 8                        # 这三秒没有观测
        z = None if drop else (px + rng.normal(0, 10), py + rng.normal(0, 10))

        kf.predict(t)
        if z is not None:
            kf.update(z)
            err_raw.append(float(np.hypot(z[0] - px, z[1] - py)))
        fx, fy = kf.position
        err_kf.append(float(np.hypot(fx - px, fy - py)))

        print("t=%2d  %s  真值(%7.1f,%6.1f)  滤波(%7.1f,%6.1f)  误差 %5.1f m"
              % (k, "丢包" if drop else "观测", px, py, fx, fy, err_kf[-1]))

    rmse_raw = float(np.sqrt(np.mean(np.square(err_raw))))
    rmse_kf = float(np.sqrt(np.mean(np.square(err_kf))))
    print("\n原始观测 RMSE = %.2f m" % rmse_raw)
    print("滤波后   RMSE = %.2f m" % rmse_kf)
    assert rmse_kf < rmse_raw, "滤波后误差应小于原始观测"
    assert max(err_kf) < 25, "丢包期间外推误差应保持在合理范围"
    print("自测通过 ✅")
