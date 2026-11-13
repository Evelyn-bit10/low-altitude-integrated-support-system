# -*- coding: utf-8 -*-
"""匀速（CV）模型的卡尔曼滤波，纯 Python 实现（不依赖 numpy）。

为什么自己写
------------
后端运行环境刻意保持轻量（连 numpy 都不装），所以这里手写 4×4 矩阵运算。
一次 predict+update 约 300 次浮点运算，50 条观测/帧 < 2 万次，可以忽略。

状态
----
    x = [px, py, vx, vy]^T        （局部 ENU 米）
    P = 4×4 协方差

预测
----
    x' = F x,  P' = F P Fᵀ + Q(σ_a, Δt)
    Q 用连续白噪声加速度模型：位置-位置 Δt⁴/4、位置-速度 Δt³/2、速度-速度 Δt²

更新
----
    ν = z - Hx              （新息）
    S = H P' Hᵀ + R         （2×2）
    K = P' Hᵀ S⁻¹
    x = x' + Kν,  P = (I-KH)P'(I-KH)ᵀ + K R Kᵀ   （Joseph 形式，保证正定）

门限
----
    马氏距离 d² = νᵀ S⁻¹ ν，二维 99.7% 对应 χ² = 11.8（等价于 3.44σ）。
    沿新息方向的等效 σ 为 sqrt(νᵀSν / νᵀν)，用它把椭圆门限折算成标量距离，
    这样打分函数（1 - d/gate）不用改。
"""
from __future__ import annotations

import math
from typing import List, Tuple

# 二维 99.7% 置信（χ²(2) 的分位数），与原来 gate_k 的物理含义一致
CHI2_2_997 = 11.8

Matrix4 = List[List[float]]


def _eye4() -> Matrix4:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def _matmul4(a: Matrix4, b: Matrix4) -> Matrix4:
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        ai = a[i]
        oi = out[i]
        for k in range(4):
            aik = ai[k]
            if aik == 0.0:
                continue
            bk = b[k]
            for j in range(4):
                oi[j] += aik * bk[j]
    return out


def _transpose4(a: Matrix4) -> Matrix4:
    return [[a[j][i] for j in range(4)] for i in range(4)]


def _symmetrize(p: Matrix4) -> None:
    for i in range(4):
        for j in range(i + 1, 4):
            v = 0.5 * (p[i][j] + p[j][i])
            p[i][j] = v
            p[j][i] = v


class KalmanCV:
    """单条航迹的匀速模型滤波器（水平面）。"""

    __slots__ = ("px", "py", "vx", "vy", "P", "sigma_a", "steps")

    def __init__(self, px: float, py: float,
                 sigma_pos: float = 20.0, sigma_vel: float = 15.0,
                 sigma_a: float = 2.0) -> None:
        self.px, self.py = float(px), float(py)
        self.vx = self.vy = 0.0
        # 初始不确定度：位置按观测 σ，速度未知 → 给大方差，让滤波器从头学
        self.P: Matrix4 = [[sigma_pos ** 2, 0.0, 0.0, 0.0],
                           [0.0, sigma_pos ** 2, 0.0, 0.0],
                           [0.0, 0.0, sigma_vel ** 2, 0.0],
                           [0.0, 0.0, 0.0, sigma_vel ** 2]]
        self.sigma_a = float(sigma_a)
        self.steps = 0

    # -------------------------------------------------------------- 预测
    def predict(self, dt: float, sigma_a: float | None = None) -> None:
        if dt <= 0.0:
            return
        dt = min(dt, 60.0)                       # 超过 TTL 的间隔按 60 s 处理，防止 P 爆炸
        sa = self.sigma_a if sigma_a is None else sigma_a

        # x = F x
        self.px += self.vx * dt
        self.py += self.vy * dt

        # P = F P Fᵀ ；F 的特殊结构可以展开算，比通用 4×4 乘快一倍
        p = self.P
        dt2 = dt * dt
        # 先把列 2/3 乘 dt 加到列 0/1 上：P·Fᵀ
        for i in range(4):
            p0 = p[i][0] + p[i][2] * dt
            p1 = p[i][1] + p[i][3] * dt
            p[i][0], p[i][1] = p0, p1
        # 再对行做同样操作：F·(P·Fᵀ)
        for j in range(4):
            r0 = p[0][j] + p[2][j] * dt
            r1 = p[1][j] + p[3][j] * dt
            p[0][j], p[1][j] = r0, r1

        # + Q（白噪声加速度）
        q = sa * sa
        q11 = q * dt2 * dt2 / 4.0
        q13 = q * dt2 * dt / 2.0
        q33 = q * dt2
        p[0][0] += q11; p[0][2] += q13
        p[2][0] += q13; p[2][2] += q33
        p[1][1] += q11; p[1][3] += q13
        p[3][1] += q13; p[3][3] += q33
        _symmetrize(p)

    # -------------------------------------------------------------- 更新
    def update(self, zx: float, zy: float, sigma_obs: float) -> None:
        r2 = max(sigma_obs, 1.0) ** 2
        p = self.P
        # S = H P Hᵀ + R  （2×2）
        s11 = p[0][0] + r2
        s12 = p[0][1]
        s21 = p[1][0]
        s22 = p[1][1] + r2
        det = s11 * s22 - s12 * s21
        if abs(det) < 1e-12:
            det = 1e-12
        inv11, inv12 = s22 / det, -s12 / det
        inv21, inv22 = -s21 / det, s11 / det

        # K = P Hᵀ S⁻¹   （4×2）
        k = [[p[i][0] * inv11 + p[i][1] * inv21,
              p[i][0] * inv12 + p[i][1] * inv22] for i in range(4)]

        # x += K ν
        nu_x = zx - self.px
        nu_y = zy - self.py
        self.px += k[0][0] * nu_x + k[0][1] * nu_y
        self.py += k[1][0] * nu_x + k[1][1] * nu_y
        self.vx += k[2][0] * nu_x + k[2][1] * nu_y
        self.vy += k[3][0] * nu_x + k[3][1] * nu_y

        # Joseph: P = (I-KH) P (I-KH)ᵀ + K R Kᵀ
        # I-KH 只有前两列被改：行 i 的 [0]=δi0-k[i][0], [1]=δi1-k[i][1]
        a = [[(1.0 if i == 0 else 0.0) - k[i][0],
              (1.0 if i == 1 else 0.0) - k[i][1],
              (1.0 if i == 2 else 0.0),
              (1.0 if i == 3 else 0.0)] for i in range(4)]
        tmp = _matmul4(a, p)
        newp = _matmul4(tmp, _transpose4(a))
        for i in range(4):
            for j in range(4):
                newp[i][j] += r2 * (k[i][0] * k[j][0] + k[i][1] * k[j][1])
        # 数值兜底：对角线不为负
        for i in range(4):
            if newp[i][i] < 1e-6:
                newp[i][i] = 1e-6
        _symmetrize(newp)
        self.P = newp
        self.steps += 1

    # -------------------------------------------------------------- 只看不算
    def innovation(self, zx: float, zy: float,
                   sigma_obs: float) -> Tuple[float, float]:
        """返回 (欧氏距离 d, 沿新息方向的等效 σ)。"""
        nu_x = zx - self.px
        nu_y = zy - self.py
        d = math.hypot(nu_x, nu_y)
        if d < 1e-9:
            s_eff2 = self.P[0][0] + self.P[1][1] + 2.0 * max(sigma_obs, 1.0) ** 2
            return 0.0, math.sqrt(max(s_eff2, 1e-6) / 2.0)
        p = self.P
        r2 = max(sigma_obs, 1.0) ** 2
        # S = H P Hᵀ + R
        s11, s12, s21, s22 = p[0][0] + r2, p[0][1], p[1][0], p[1][1] + r2
        # νᵀ S ν / (νᵀν)
        s_nu_x = s11 * nu_x + s12 * nu_y
        s_nu_y = s21 * nu_x + s22 * nu_y
        quad = nu_x * s_nu_x + nu_y * s_nu_y
        s_eff2 = quad / (d * d)
        return d, math.sqrt(max(s_eff2, 1e-6))

    def mahalanobis2(self, zx: float, zy: float, sigma_obs: float) -> float:
        nu_x = zx - self.px
        nu_y = zy - self.py
        p = self.P
        r2 = max(sigma_obs, 1.0) ** 2
        s11, s12, s21, s22 = p[0][0] + r2, p[0][1], p[1][0], p[1][1] + r2
        det = s11 * s22 - s12 * s21
        if abs(det) < 1e-12:
            det = 1e-12
        inv11, inv12, inv21, inv22 = s22 / det, -s12 / det, -s21 / det, s11 / det
        return nu_x * (inv11 * nu_x + inv12 * nu_y) + nu_y * (inv21 * nu_x + inv22 * nu_y)

    # -------------------------------------------------------------- 读
    def pos(self) -> Tuple[float, float]:
        return self.px, self.py

    def vel(self) -> Tuple[float, float]:
        return self.vx, self.vy

    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def sigma(self) -> float:
        """位置不确定度的各向同性近似（1σ，米）。"""
        return math.sqrt(max(0.5 * (self.P[0][0] + self.P[1][1]), 1e-6))

    def heading_deg(self) -> float:
        """速度方向（0=北, 90=东）；速度为 0 时返回 0。"""
        vx, vy = self.vx, self.vy
        if math.hypot(vx, vy) < 0.5:
            return 0.0
        return (math.degrees(math.atan2(vx, vy)) + 360.0) % 360.0


class KalmanIMM:
    """交互多模型（IMM）：两个匀速模型并存，按似然自动加权。

    为什么需要
    ----------
    单个匀速模型没法同时覆盖"直飞"和"7 m/s² 盘旋"：
        σ_a 小 → 直飞准，但盘旋时速度/航向严重滞后（实测航向偏 76°）
        σ_a 大 → 跟得上盘旋，但直飞时门限放松，误配上升

    IMM 同时跑两个模型，用各自的新息似然决定权重：
        直飞时自动倒向小 σ_a，盘旋时倒向大 σ_a。

    接口与 KalmanCV 完全一致（predict / update / pos / vel / sigma /
    innovation / heading_deg，以及 px py vx vy P steps 属性），
    所以 dedup.py 只需要换一个类名。
    """

    __slots__ = ("models", "mu", "T", "steps", "_px", "_py", "_vx", "_vy", "_P")

    # 两个模型的机动噪声与切换矩阵
    SIGMA_A = (2.0, 8.0)
    TRANS = [[0.94, 0.06],
             [0.10, 0.90]]

    def __init__(self, px: float, py: float, sigma_pos: float = 20.0,
                 sigma_vel: float = 15.0, sigma_a: float | None = None) -> None:
        self.models = [KalmanCV(px, py, sigma_pos, sigma_vel, sa) for sa in self.SIGMA_A]
        self.mu = [0.85, 0.15]          # 先验：多数场景是直飞
        self.T = self.TRANS
        self.steps = 0
        # 组合后的状态（对外暴露）
        self._px, self._py = float(px), float(py)
        self._vx, self._vy = 0.0, 0.0
        self._P = [row[:] for row in self.models[0].P]

    # -------------------------------------------------------------- 混合
    def _mix(self) -> None:
        T = self.T
        n = len(self.models)
        cbar = [sum(T[i][j] * self.mu[i] for i in range(n)) for j in range(n)]
        cbar = [max(c, 1e-9) for c in cbar]
        w = [[T[i][j] * self.mu[i] / cbar[j] for j in range(n)] for i in range(n)]

        new_states = []
        for j in range(n):
            x0 = [0.0] * 4
            for i in range(n):
                m = self.models[i]
                x0[0] += w[i][j] * m.px
                x0[1] += w[i][j] * m.py
                x0[2] += w[i][j] * m.vx
                x0[3] += w[i][j] * m.vy
            P0 = [[0.0] * 4 for _ in range(4)]
            for i in range(n):
                m = self.models[i]
                dx = [m.px - x0[0], m.py - x0[1], m.vx - x0[2], m.vy - x0[3]]
                for a in range(4):
                    for b in range(4):
                        P0[a][b] += w[i][j] * (m.P[a][b] + dx[a] * dx[b])
            new_states.append((x0, P0))
        for j, (x0, P0) in enumerate(new_states):
            m = self.models[j]
            m.px, m.py, m.vx, m.vy = x0
            m.P = P0
            _symmetrize(m.P)
        self.mu = cbar

    # -------------------------------------------------------------- 预测
    def predict(self, dt: float, sigma_a: float | None = None) -> None:
        if dt <= 0.0:
            return
        self._mix()
        for m in self.models:
            m.predict(dt)
        self._combine()

    # -------------------------------------------------------------- 更新
    def update(self, zx: float, zy: float, sigma_obs: float) -> None:
        r2 = max(sigma_obs, 1.0) ** 2
        lik = []
        for m in self.models:
            p = m.P
            s11, s12, s21, s22 = p[0][0] + r2, p[0][1], p[1][0], p[1][1] + r2
            det = s11 * s22 - s12 * s21
            det = det if abs(det) > 1e-12 else 1e-12
            nu_x, nu_y = zx - m.px, zy - m.py
            maha = (nu_x * (s22 * nu_x - s12 * nu_y) + nu_y * (-s21 * nu_x + s11 * nu_y)) / det
            # 高斯似然（忽略常数项，只比大小）
            lik.append(math.exp(-0.5 * min(maha, 600.0)) / math.sqrt(max(det, 1e-12)))
        w = [lik[i] * self.mu[i] for i in range(len(self.models))]
        tot = sum(w) or 1.0
        self.mu = [x / tot for x in w]

        for m in self.models:
            m.update(zx, zy, sigma_obs)
        self.steps += 1
        self._combine()

    # -------------------------------------------------------------- 组合
    def _combine(self) -> None:
        px = sum(self.mu[j] * self.models[j].px for j in range(2))
        py = sum(self.mu[j] * self.models[j].py for j in range(2))
        vx = sum(self.mu[j] * self.models[j].vx for j in range(2))
        vy = sum(self.mu[j] * self.models[j].vy for j in range(2))
        P = [[0.0] * 4 for _ in range(4)]
        for j in range(2):
            m = self.models[j]
            dx = [m.px - px, m.py - py, m.vx - vx, m.vy - vy]
            for a in range(4):
                for b in range(4):
                    P[a][b] += self.mu[j] * (m.P[a][b] + dx[a] * dx[b])
        _symmetrize(P)
        self._px, self._py, self._vx, self._vy, self._P = px, py, vx, vy, P

    # -------------------------------------------------------------- 读写
    @property
    def px(self) -> float: return self._px
    @px.setter
    def px(self, v: float) -> None:
        for m in self.models: m.px = float(v)
        self._px = float(v)

    @property
    def py(self) -> float: return self._py
    @py.setter
    def py(self, v: float) -> None:
        for m in self.models: m.py = float(v)
        self._py = float(v)

    @property
    def vx(self) -> float: return self._vx
    @vx.setter
    def vx(self, v: float) -> None:
        for m in self.models: m.vx = float(v)
        self._vx = float(v)

    @property
    def vy(self) -> float: return self._vy
    @vy.setter
    def vy(self, v: float) -> None:
        for m in self.models: m.vy = float(v)
        self._vy = float(v)

    @property
    def P(self): return self._P
    @P.setter
    def P(self, v) -> None:
        for m in self.models: m.P = [row[:] for row in v]
        self._P = [row[:] for row in v]

    def pos(self):
        return self._px, self._py

    def vel(self):
        return self._vx, self._vy

    def speed(self) -> float:
        return math.hypot(self._vx, self._vy)

    def sigma(self) -> float:
        return math.sqrt(max(0.5 * (self._P[0][0] + self._P[1][1]), 1e-6))

    def heading_deg(self) -> float:
        if math.hypot(self._vx, self._vy) < 0.5:
            return 0.0
        return (math.degrees(math.atan2(self._vx, self._vy)) + 360.0) % 360.0

    def innovation(self, zx: float, zy: float, sigma_obs: float):
        d = math.hypot(zx - self._px, zy - self._py)
        if d < 1e-9:
            s2 = (self._P[0][0] + self._P[1][1]) / 2 + max(sigma_obs, 1.0) ** 2
            return 0.0, math.sqrt(max(s2, 1e-6))
        r2 = max(sigma_obs, 1.0) ** 2
        p = self._P
        s11, s12, s21, s22 = p[0][0] + r2, p[0][1], p[1][0], p[1][1] + r2
        nu_x, nu_y = zx - self._px, zy - self._py
        quad = nu_x * (s11 * nu_x + s12 * nu_y) + nu_y * (s21 * nu_x + s22 * nu_y)
        return d, math.sqrt(max(quad / (d * d), 1e-6))

    def mahalanobis2(self, zx: float, zy: float, sigma_obs: float) -> float:
        d, s_eff = self.innovation(zx, zy, sigma_obs)
        return (d / max(s_eff, 1e-6)) ** 2
