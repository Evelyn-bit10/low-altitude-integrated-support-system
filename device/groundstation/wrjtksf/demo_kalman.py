# -*- coding: utf-8 -*-
"""卡尔曼滤波演示：带噪观测 + 丢包外推。

运行：
    cd device\\groundstation\\wrjtksf
    python demo_kalman.py

输出：
    1) 逐秒对比表（真值 / 观测 / 滤波值 / 误差）
    2) 原始观测与滤波后的 RMSE 对比
    3) 多目标（TrackManager）演示

依赖：numpy（工程 requirements.txt 已包含）。
"""

from __future__ import annotations

import math
import random

import numpy as np

from src.services.kalman_track import KalmanTrack, TrackManager

# ------------------------------------------------------------------ 参数
DT = 1.0              # 观测周期（秒），RID 约 1s
SPEED = 12.0          # m/s
NOISE = 10.0          # 观测噪声标准差（米）
SIGMA_A = 1.0         # 过程噪声（m/s²）：越大越跟手，越小越平滑
DROPOUT = 0.25        # 随机丢包率
GAP = range(45, 52)   # 45~51 秒连续丢包（直线段），用来看纯预测效果

rng = np.random.default_rng(2024)
random.seed(2024)


def trajectory(n: int):
    """生成一条带转弯的航迹：先直飞，20~35s 以 5°/s 转向，再直飞。"""
    px, py = 0.0, 0.0
    heading = math.radians(20.0)
    out = []
    for k in range(n + 1):
        t = k * DT
        out.append((t, px, py, math.degrees(heading)))
        turn = math.radians(5.0) if 20 <= t < 35 else 0.0
        heading += turn
        px += SPEED * math.cos(heading) * DT
        py += SPEED * math.sin(heading) * DT
    return out


def main():
    truth = trajectory(60)
    kf = KalmanTrack("UAS-DEMO", dt=DT, sigma_xy=NOISE, sigma_a=SIGMA_A)

    err_raw, err_kf, err_kf_obs, gap_err = [], [], [], []
    rows = []

    for t, px, py, hdg in truth[1:]:
        dropped = (int(t) in GAP) or (random.random() < DROPOUT)
        z = None if dropped else (px + rng.normal(0, NOISE), py + rng.normal(0, NOISE))

        kf.predict(t)
        if z is not None:
            kf.update(z)
            err_raw.append(math.hypot(z[0] - px, z[1] - py))

        fx, fy = kf.position
        e = math.hypot(fx - px, fy - py)
        err_kf.append(e)
        if z is not None:                 # 只统计"有观测"的帧，与原始观测公平对比
            err_kf_obs.append(e)
        if int(t) in GAP:
            gap_err.append(e)

        rows.append((t, dropped, px, py, None if z is None else z[0],
                     None if z is None else z[1], fx, fy, e, kf.speed, hdg))

    # ---- 逐秒表（每 2 秒打一行，丢包段全打）----
    print("=" * 92)
    print("  时间   状态      真值(东,北)       观测(东,北)       滤波(东,北)      误差   估计速度")
    print("=" * 92)
    for r in rows:
        t, dropped, px, py, zx, zy, fx, fy, e, spd, _ = r
        if int(t) % 2 and int(t) not in GAP:
            continue
        obs = "     — 丢包  —   " if zx is None else "(%7.1f,%7.1f)" % (zx, zy)
        print("  %4.0fs  %s  (%7.1f,%7.1f)  %s  (%7.1f,%7.1f)  %5.1fm  %5.1f m/s"
              % (t, "丢包" if dropped else "观测", px, py, obs, fx, fy, e, spd))

    rmse_raw = math.sqrt(sum(v * v for v in err_raw) / len(err_raw))
    rmse_kf = math.sqrt(sum(v * v for v in err_kf) / len(err_kf))
    rmse_kf_obs = math.sqrt(sum(v * v for v in err_kf_obs) / len(err_kf_obs))
    print("-" * 92)
    print("  观测样本 %d 个（共 %d 帧，丢包 %d 帧）"
          % (len(err_raw), len(rows), len(rows) - len(err_raw)))
    print("  原始观测 RMSE          : %6.2f m" % rmse_raw)
    print("  滤波后 RMSE（有观测帧）: %6.2f m    （降低 %.0f%%）"
          % (rmse_kf_obs, (1 - rmse_kf_obs / rmse_raw) * 100))
    print("  滤波后 RMSE（全部帧）  : %6.2f m    （含 7 秒纯预测）" % rmse_kf)
    print("  连续丢包段最大误差     : %6.2f m    （纯外推，未校正）" % max(gap_err))

    # ---- 预测未来 5 秒 ----
    ax, ay = kf.predict_ahead(5.0)
    print("  当前速度 %.1f m/s，预测 5 秒后位置 (%.1f, %.1f)" % (kf.speed, ax, ay))
    sx, sy = kf.position
    sig = math.sqrt(max(kf.P[0, 0], 0.0))
    print("  位置 1σ 不确定度   : %6.2f m" % sig)

    # ---- 多目标演示 ----
    print("\n" + "=" * 92)
    print("  多目标：TrackManager 同时跟踪两架（含交叉航迹）")
    print("=" * 92)
    tm = TrackManager(sigma_xy=NOISE, sigma_a=SIGMA_A, max_age=10.0)
    a = (0.0, 0.0, 10.0, 2.0)     # x, y, vx, vy
    b = (200.0, 150.0, -9.0, -2.5)
    for k in range(1, 13):
        t = float(k)
        a = (a[0] + a[2], a[1] + a[3], a[2], a[3])
        b = (b[0] + b[2], b[1] + b[3], b[2], b[3])
        obs = [("UAS-A", a[0] + rng.normal(0, NOISE), a[1] + rng.normal(0, NOISE)),
               ("UAS-B", b[0] + rng.normal(0, NOISE), b[1] + rng.normal(0, NOISE))]
        # 第 8~9 秒 B 丢包
        if k in (8, 9):
            obs = obs[:1]
        tracks = tm.step(t, obs)
        if k % 3 == 0:
            line = "  t=%4.0fs  " % t
            for tid, s in tracks.items():
                line += "%s(%6.1f,%6.1f) v=%4.1f %s   " % (
                    tid, s.px, s.py, math.hypot(s.vx, s.vy),
                    "观测" if s.updated else "预测")
            print(line)
    print("  说明：B 在第 8~9 秒无观测，仍能靠预测维持航迹，恢复观测后自动校正。")

    # ---- 断言（可当作最小自测）----
    assert rmse_kf_obs < rmse_raw * 0.7, "有观测帧的滤波误差应显著小于原始观测"
    assert max(gap_err) < 35, "7 秒连续丢包的外推误差应保持在合理范围"
    assert len(tm.tracks) == 2, "两个目标都应保持航迹"
    print("\n自测通过 ✅")

    # ---- 可选绘图 ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # 中文字体（否则标题/图例会显示成方框）
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False

        fig, ax = plt.subplots(figsize=(7.5, 6.0), dpi=130)
        ax.plot([r[2] for r in rows], [r[3] for r in rows], "k-", lw=1.6, label="真值")
        ax.scatter([r[4] for r in rows if r[4] is not None],
                   [r[5] for r in rows if r[5] is not None],
                   s=16, c="#e88a28", alpha=.75, label="观测")
        ax.plot([r[6] for r in rows], [r[7] for r in rows], "-", c="#2e5c8a", lw=2, label="卡尔曼滤波")
        gx = [r[6] for r in rows if int(r[0]) in GAP]
        gy = [r[7] for r in rows if int(r[0]) in GAP]
        ax.scatter(gx, gy, s=42, facecolors="none", edgecolors="#c83c3c",
                   label="丢包段预测")
        ax.set_aspect("equal")
        ax.grid(alpha=.25)
        ax.legend(loc="upper left", fontsize=8)
        ax.set_xlabel("东向 x (m)")
        ax.set_ylabel("北向 y (m)")
        ax.set_title("Kalman 航迹跟踪（含 7 秒丢包）")
        out = "kalman_demo.png"
        fig.tight_layout()
        fig.savefig(out)
        print("图已保存: %s" % out)
    except Exception as exc:  # pragma: no cover - 无 matplotlib 时跳过
        print("（未生成图片：%s）" % exc)


if __name__ == "__main__":
    main()
