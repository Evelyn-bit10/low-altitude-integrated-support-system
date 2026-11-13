# -*- coding: utf-8 -*-
"""进出场方向与方案库测试。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    pytest tests/test_procedures.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import demo_data                                      # noqa: E402
from app.domain import EnvSnapshot                              # noqa: E402
from app.engines import compliance, planner                     # noqa: E402
from app.plans_library import build_library, find_plans, plan_to_program  # noqa: E402

DIRS = list(planner.DIRECTIONS.keys())


def env():
    return EnvSnapshot(demo_data.AIRPORT, list(demo_data.OBSTACLES),
                       list(demo_data.AIRSPACES), demo_data.DEFAULT_METEO,
                       demo_data.DEFAULT_LIMITS)


def bearing_of_xy(x, y):
    return math.degrees(math.atan2(x, y)) % 360.0


def near(a, b, tol=8.0):
    return abs(((a - b + 180) % 360) - 180) <= tol


def test_library_covers_all_directions():
    lib = build_library("LAC-DEMO")
    assert len(lib) == 16
    assert len(find_plans(lib, "arrival")) == 8
    assert len(find_plans(lib, "departure")) == 8
    for d in DIRS:
        assert len(find_plans(lib, "arrival", d)) == 1
        assert len(find_plans(lib, "departure", d)) == 1


def test_template_profile_gradient_within_limits():
    """模板梯度必须落在机型包线内（否则每次都要回退动态规划）。"""
    lib = build_library("LAC-DEMO")
    limit = demo_data.DEFAULT_LIMITS.descent_gradient
    for p in lib:
        wps = p["waypoints"]
        for a, b in zip(wps, wps[1:]):
            dh = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            grad = abs(b["z"] - a["z"]) / dh
            assert grad <= limit + 1e-6, "%s 梯度 %.3f 超限" % (p["std_name"], grad)


def test_arrival_entry_matches_direction():
    e, rules = env(), demo_data.RULES
    for d, bearing in planner.DIRECTIONS.items():
        prog = planner.replan_arrival(e, rules, direction=d)
        first = prog.waypoints[0]
        ang = bearing_of_xy(first.x, first.y)
        assert near(ang, bearing), "%s 入口方位 %.1f ≠ %.1f" % (d, ang, bearing)
        assert 2400 < math.hypot(first.x, first.y) < 2600
        assert prog.direction == d


def test_departure_exit_matches_direction():
    e, rules = env(), demo_data.RULES
    for d, bearing in planner.DIRECTIONS.items():
        prog = planner.replan_departure(e, rules, direction=d)
        last = prog.waypoints[-1]
        ang = bearing_of_xy(last.x, last.y)
        assert near(ang, bearing), "%s 出口方位 %.1f ≠ %.1f" % (d, ang, bearing)
        assert 2900 < math.hypot(last.x, last.y) < 3100
        assert abs(last.z - 300.0) < 1.0
        assert prog.direction == d


def test_direction_accepts_bearing_number():
    e, rules = env(), demo_data.RULES
    p1 = planner.replan_arrival(e, rules, direction="E")
    p2 = planner.replan_arrival(e, rules, direction=90)
    a, b = p1.waypoints[0], p2.waypoints[0]
    assert abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6
    assert p2.direction == "E"


def test_open_directions_template_compliant():
    """无遮挡的方向，模板方案应直接通过合规与仿真。"""
    e, rules = env(), demo_data.RULES
    lib = build_library(e.airport.code)
    for d in ("N", "E", "SE", "S", "SW"):
        prog = plan_to_program(find_plans(lib, "arrival", d)[0], "arrival")
        comp = compliance.check_full(prog, e, rules, e.limits)
        assert comp.passed, "%s 模板合规失败: %s" % (d, comp.err_msg())


def test_default_direction_is_runway_aligned():
    """不指定方向时保持旧行为：使用跑道方向。"""
    e, rules = env(), demo_data.RULES
    prog = planner.replan_arrival(e, rules)
    first = prog.waypoints[0]
    # 跑道朝向 0°（向北），进近来自南侧
    assert abs(bearing_of_xy(first.x, first.y) - 180.0) < 8


if __name__ == "__main__":
    funcs = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    ok = True
    for name, fn in funcs:
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as exc:
            ok = False
            print("  FAIL  %s  %s" % (name, exc))
    print("全部通过 ✅" if ok else "存在失败项 ❌")
    sys.exit(0 if ok else 1)


def test_direction_recommendation():
    """自动推荐方向：8 个候选都要评估，且逆风方向应优于顺风方向。"""
    from app.services import recommend as rec
    from app.config import Settings
    from app.store import Store
    from app.engines import planner, compliance, simulate

    st = Store(Settings(database_url="sqlite://", dispatch_interval=5.0, auth_enabled=False))
    env = st.snapshot()
    rows = []
    for d, bearing in (("N", 0.0), ("S", 180.0)):
        prog = planner.replan_arrival(env, st.rules, direction=d)
        comp = compliance.check_full(prog, env, st.rules, st.limits)
        sim = simulate.simulate_check(prog, env)
        hdg = (bearing + 180.0) % 360.0
        row = rec.score_one(d, bearing, prog, comp, sim, env.meteo, hdg)
        row["entry_heading"] = hdg
        rows.append(row)

    ranked = rec.rank(rows)
    assert ranked[0]["direction"] == "S"          # 风从北来，向南进场是逆风
    assert ranked[1]["metrics"]["tailwind_mps"] > 0
    assert all(r["score"] > 0 for r in ranked)
