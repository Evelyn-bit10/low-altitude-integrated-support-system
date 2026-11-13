"""四大引擎最小原型单元测试。

运行方式(在 backend 目录下):
    python tests/test_engines.py
或:
    pytest tests/test_engines.py -q
"""
from __future__ import annotations

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import app.demo_data as dd  # noqa: E402
from app.domain import (AircraftLimits, EnvSnapshot, FlightProgram,  # noqa: E402
                        Meteo, Obstacle, Waypoint)
from app.engines import compliance, geometry as geo, planner, risk, simulate  # noqa: E402

try:  # 调度闭环测试需要 sqlalchemy; 无该依赖时自动跳过
    import sqlalchemy  # noqa: F401
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


def make_env(active_ids=None) -> EnvSnapshot:
    ids = set(active_ids) if active_ids is not None else set(dd.ACTIVE_OBSTACLE_IDS)
    obs = [o for o in dd.OBSTACLES if o.id in ids]
    return EnvSnapshot(dd.AIRPORT, obs, list(dd.AIRSPACES), Meteo(), AircraftLimits())


def test_point_in_polygon():
    poly = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert geo.point_in_polygon(5, 5, poly)
    assert not geo.point_in_polygon(15, 5, poly)


def test_calc_msa():
    obs = [Obstacle(1, "a", 1, 0, 0, 0, 100, 10, 10),
           Obstacle(2, "b", 1, 0, 0, 0, 200, 10, 10)]
    assert compliance.calc_msa(obs, 300) == 500.0


def test_astar_avoids_obstacle():
    start, goal = (0.0, -1000.0, 200.0), (0.0, 0.0, 0.0)
    wall = Obstacle(99, "wall", 1, 0.0, -500.0, 0.0, 300.0, 60.0, 60.0)
    bounds = planner.BBox(-1000, 1000, -1500, 500, 0, 500)
    path = planner.plan_astar(start, goal, [wall], bounds, 0.15, clearance=10.0)
    assert path is not None, "A* 未找到路径"
    for p, q in zip(path, path[1:]):
        assert geo.segment_free(p, q, [wall], 10.0), "A* 路径存在碰撞"


def test_rrtstar_finds_path():
    start, goal = (0.0, -1000.0, 200.0), (0.0, 0.0, 0.0)
    wall = Obstacle(99, "wall", 1, 0.0, -500.0, 0.0, 300.0, 60.0, 60.0)
    bounds = planner.BBox(-1000, 1000, -1500, 500, 0, 500)
    path = planner.plan_rrtstar(start, goal, [wall], bounds, 0.15,
                                clearance=10.0, iters=800, seed=1)
    assert path is not None, "RRT* 未找到路径"


def test_replan_arrival_clean_compliant():
    env = make_env()  # 塔吊关闭
    prog = planner.replan_arrival(env, dd.RULES)
    assert len(prog.waypoints) > 2
    res = compliance.check_full(prog, env, dd.RULES, env.limits)
    assert res.passed, res.err_msg()
    sim = simulate.simulate_check(prog, env)
    assert sim.passed, sim.err_msg()


def test_replan_arrival_with_crane_compliant():
    env = make_env({1, 2, 3, 4, 5})  # 塔吊激活
    prog = planner.replan_arrival(env, dd.RULES)
    assert len(prog.waypoints) > 2
    res = compliance.check_full(prog, env, dd.RULES, env.limits)
    assert res.passed, res.err_msg()
    sim = simulate.simulate_check(prog, env)
    assert sim.passed, sim.err_msg()
    crane = next(o for o in env.obstacles if o.id == 1)
    for w in prog.waypoints:
        assert (math.hypot(w.x - crane.x, w.y - crane.y) > crane.inflated_radius
                or w.z > crane.top_agl + 75), "航迹未绕开塔吊"


def test_risk_triggers_adjust_on_crane():
    clean = make_env()
    prog = planner.replan_arrival(clean, dd.RULES)
    rr = risk.assess(clean, prog, dd.PLANS, dd.RULES)
    assert rr.program_status == "STATIC_VALID", f"干净环境应为可用, 得到 {rr}"

    crane_env = make_env({1, 2, 3, 4, 5})
    rr2 = risk.assess(crane_env, prog, dd.PLANS, dd.RULES)
    assert rr2.program_status == "NEED_ADJUST", f"塔吊侵入应触发调整, 得到 {rr2}"


def test_dispatch_full_loop():
    """端到端: 塔吊激活后, 调度闭环应自动重规划并发布合规程序。"""
    if not HAS_SQLALCHEMY:
        return  # 无 sqlalchemy, 跳过(由 main() 统一汇报)
    from app.services.dispatch import DispatchService
    from app.store import Store
    from app.config import Settings

    st = Store(Settings(database_url="sqlite:///:memory:", dispatch_interval=99, auth_enabled=False))
    st.init()
    svc = DispatchService(st)
    svc.run_cycle()  # 生成初始程序
    assert st.current_program is not None
    v1 = st.current_program.version
    # 激活塔吊 -> 下一周期应触发调整并发布新版本
    st.toggle_obstacle(1, True)
    svc.run_cycle()
    assert st.current_program is not None
    assert st.current_program.version != v1, "塔吊激活后应发布新程序版本"
    assert st.risk_result.level >= 3, "塔吊激活后风险应升级为高风险"
    assert st.compliance is not None and st.compliance.passed, "调度发布的程序应通过合规校验"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    skipped = 0
    for t in tests:
        if t.__name__ == "test_dispatch_full_loop" and not HAS_SQLALCHEMY:
            print("SKIP  test_dispatch_full_loop (sqlalchemy 未安装)")
            skipped += 1
            continue
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed - skipped}/{len(tests)} 通过, {skipped} 跳过")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
