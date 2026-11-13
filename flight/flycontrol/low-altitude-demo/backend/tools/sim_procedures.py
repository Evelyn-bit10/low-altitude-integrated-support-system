# -*- coding: utf-8 -*-
"""8 方向进出场轨迹模拟。

对 N/NE/E/SE/S/SW/W/NW 八个方向分别生成进近与离场程序：
  - 先取方案库模板；
  - 模板不合规/仿真不通过时自动动态重规划（A*+Dubins）；
  - 输出统计表 + 一张轨迹图。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    python tools\\sim_procedures.py                # 生成图并打印表格
    python tools\\sim_procedures.py --no-plot      # 只打印表格
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import demo_data                                    # noqa: E402
from app.domain import EnvSnapshot                            # noqa: E402
from app.engines import compliance, planner, simulate         # noqa: E402
from app.engines.geometry import dist3d                       # noqa: E402
from app.plans_library import build_library, find_plans, plan_to_program  # noqa: E402

DIRS = list(planner.DIRECTIONS.keys())
CN = planner.DIRECTION_CN


def make_env() -> EnvSnapshot:
    return EnvSnapshot(
        airport=demo_data.AIRPORT,
        obstacles=list(demo_data.OBSTACLES),
        airspaces=list(demo_data.AIRSPACES),
        meteo=demo_data.DEFAULT_METEO,
        limits=demo_data.DEFAULT_LIMITS,
    )


def path_stats(wps) -> dict:
    """航路点 -> 长度 / 时长 / 最大梯度。"""
    length = dur = 0.0
    max_grad = 0.0
    for a, b in zip(wps, wps[1:]):
        d3 = dist3d((a.x, a.y, a.z), (b.x, b.y, b.z))
        dh = math.hypot(b.x - a.x, b.y - a.y)
        length += d3
        if dh > 1e-6:
            max_grad = max(max_grad, abs(b.z - a.z) / dh)
        spd = a.speed or 20.0
        dur += (d3 / spd) if spd > 0 else 0.0
    return {"length_m": round(length, 1), "duration_s": round(dur, 1),
            "max_grad_pct": round(max_grad * 100, 1)}


def build_one(env, rules, library, program_type, direction):
    """生成单个方向的程序：模板优先，不合格则动态重规划。"""
    plans = find_plans(library, program_type, direction)
    if plans:
        prog = plan_to_program(plans[0], program_type)
        comp = compliance.check_full(prog, env, rules, env.limits)
        sim = simulate.simulate_check(prog, env)
        if comp.is_pass and sim.is_pass:
            return prog, comp, sim, "template", ""
        reason = comp.err_msg() or sim.err_msg() or "模板未通过"
    else:
        reason = "方案库无该方向"

    if program_type == "arrival":
        prog = planner.replan_arrival(env, rules, direction=direction)
    else:
        prog = planner.replan_departure(env, rules, direction=direction)
    prog.std_name = "%s-%s+DYN" % ("ARR" if program_type == "arrival" else "DEP", direction)
    comp = compliance.check_full(prog, env, rules, env.limits)
    sim = simulate.simulate_check(prog, env)
    return prog, comp, sim, "dynamic", reason


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--out", default=os.path.join("docs", "procedures_8dir.png"))
    args = ap.parse_args()

    env = make_env()
    rules = demo_data.RULES
    library = build_library(env.airport.code)

    results = {}
    print("=" * 104)
    print(" 8 方向进出场程序生成结果（机场 %s，标高 %.0f m）"
          % (env.airport.code, env.airport.elevation))
    print("=" * 104)
    print("%-4s %-10s %-9s %-7s %5s %9s %8s %7s %6s %6s %s"
          % ("方向", "类型", "模式", "标准程序", "点数", "长度(m)", "时长(s)", "梯度(%)", "合规", "仿真", "说明"))
    print("-" * 104)

    for ptype, label in (("arrival", "进近"), ("departure", "离场")):
        for d in DIRS:
            prog, comp, sim, mode, reason = build_one(env, rules, library, ptype, d)
            st = path_stats(prog.waypoints)
            ok = comp.pass_ if hasattr(comp, "pass_") else comp.passed
            ok = ok and sim.passed
            results[(ptype, d)] = dict(prog=prog, comp=comp, sim=sim, mode=mode,
                                       stats=st, ok=ok, reason=reason)
            print("%-4s %-10s %-9s %-7s %5d %9.0f %8.0f %7.1f %6s %6s %s"
                  % (d, label, mode, prog.std_name or "-", len(prog.waypoints),
                     st["length_m"], st["duration_s"], st["max_grad_pct"],
                     "✓" if comp.passed else "✗", "✓" if sim.passed else "✗",
                     (reason[:26] if reason else "")))
        print("-" * 104)

    total = len(results)
    ok_n = sum(1 for v in results.values() if v["ok"])
    tpl = sum(1 for v in results.values() if v["mode"] == "template")
    print("合计 %d 条：可用 %d 条，方案库直出 %d 条，动态重规划 %d 条"
          % (total, ok_n, tpl, total - tpl))

    if not args.no_plot:
        try:
            plot(env, results, args.out)
            print("轨迹图已保存: %s" % args.out)
        except Exception as exc:  # noqa: BLE001
            print("（未生成图：%s）" % exc)
    return 0


def plot(env, results, out_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon

    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    colors = {"N": "#2f9bff", "NE": "#27e0d8", "E": "#49e3ae", "SE": "#ffb35c",
              "S": "#ff6279", "SW": "#7c5cff", "W": "#c084fc", "NW": "#94a3b8"}

    fig, ax = plt.subplots(figsize=(8.6, 8.2), dpi=140)

    # 障碍物
    for o in env.obstacles:
        ax.add_patch(Circle((o.x, o.y), o.radius, color="#ff8a5c", alpha=.28, zorder=1))
        ax.text(o.x, o.y, o.name.split("(")[0], fontsize=6, ha="center", va="center",
                color="#8a3b1c", zorder=2)
    # 限飞区
    for a in env.airspaces:
        ax.add_patch(Polygon(a.polygon, closed=True, facecolor="#7c5cff", alpha=.10,
                             edgecolor="#7c5cff", linestyle="--", lw=1, zorder=1))
        cx = sum(p[0] for p in a.polygon) / len(a.polygon)
        cy = sum(p[1] for p in a.polygon) / len(a.polygon)
        ax.text(cx, cy, a.name, fontsize=7, color="#5b46c9", ha="center", zorder=2)

    for (ptype, d), r in results.items():
        wps = r["prog"].waypoints
        xs = [w.x for w in wps]
        ys = [w.y for w in wps]

        # 进近与离场在同一条射线上，画图时各偏 70 m 以便区分（仅示意，不改数据）
        ang = math.atan2(ys[-1] - ys[0], xs[-1] - xs[0]) + math.pi / 2
        off = (-70.0 if ptype == "arrival" else 70.0)
        xs = [x + off * math.cos(ang) for x in xs]
        ys = [y + off * math.sin(ang) for y in ys]

        style = "-" if ptype == "arrival" else "--"
        lw = 1.9 if ptype == "arrival" else 1.4
        ax.plot(xs, ys, style, color=colors[d], lw=lw,
                alpha=.95 if r["ok"] else .42, zorder=3)
        # 外端点 + 标签
        ex, ey = (xs[0], ys[0]) if ptype == "arrival" else (xs[-1], ys[-1])
        ax.scatter([ex], [ey], s=15, color=colors[d], zorder=4)
        ax.annotate("%s%s" % (d, "进" if ptype == "arrival" else "离"),
                    (ex, ey), fontsize=7, color=colors[d],
                    xytext=(5, 3), textcoords="offset points")
        if not r["ok"]:
            ax.scatter([xs[len(xs) // 2]], [ys[len(ys) // 2]], s=46, marker="x",
                       color="#c83c3c", zorder=5)

    ax.scatter([0], [0], s=70, marker="^", color="#111827", zorder=6)
    ax.annotate("起降点", (0, 0), fontsize=8, xytext=(6, -12), textcoords="offset points")

    ax.set_aspect("equal")
    ax.grid(alpha=.18)
    ax.set_xlabel("东向 x (m)")
    ax.set_ylabel("北向 y (m)")
    ax.set_title("8 方向进出场程序（实线=进近，虚线=离场，×=不可用；为区分进/离场各偏 70 m）", fontsize=11)
    ax.legend(handles=[plt.Line2D([], [], color=colors[d], label="%s %s" % (d, CN[d]))
                       for d in DIRS],
              loc="lower right", fontsize=7, ncol=2, frameon=False)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
