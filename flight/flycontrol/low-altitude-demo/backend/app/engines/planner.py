"""引擎 3: 4D 航迹动态规划引擎(最小可运行实现)。

算法支撑(详见 docs/REFERENCES.md):
  - A*    : Hart, Nilsson & Raphael (1968) —— 3D 网格启发式搜索求无碰撞路径
  - RRT*  : Karaman & Frazzoli (2011) —— 采样法渐进最优路径(备选/平滑)
  - Dubins : Dubins (1957) —— 以三点定圆半径约束实现曲率(最小转弯半径)受限平滑
  - 4D 剖面: 沿航迹积分得到速度/时间, 构成 (x,y,z,t) 四维航迹

坐标系: ENU 米, z 为相对起降点标高的 AGL 高度。
"""
from __future__ import annotations

import heapq
import math
import random
from typing import List, Optional, Tuple

from ..domain import EnvSnapshot, FlightProgram, Waypoint
from . import geometry as geo
from .compliance import calc_msa

# 网格分辨率(米)
XY_RES = 50.0
Z_RES = 5.0

COMFORT_MARGIN = 120.0   # 期望与障碍物的额外水平余量(米)
COMFORT_WEIGHT = 0.4


class BBox:
    __slots__ = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")

    def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
        self.xmin, self.xmax = xmin, xmax
        self.ymin, self.ymax = ymin, ymax
        self.zmin, self.zmax = zmin, zmax

    def sample(self) -> Tuple[float, float, float]:
        return (random.uniform(self.xmin, self.xmax),
                random.uniform(self.ymin, self.ymax),
                random.uniform(self.zmin, self.zmax))


def _compute_bounds(points, obstacles, pad: float = 700.0, zmax: float = 500.0) -> BBox:
    xs = [p[0] for p in points] + [o.x for o in obstacles]
    ys = [p[1] for p in points] + [o.y for o in obstacles]
    return BBox(min(xs) - pad, max(xs) + pad,
                min(ys) - pad, max(ys) + pad,
                0.0, zmax)


def _point_in_poly(x: float, y: float, poly) -> bool:
    """射线法判断点是否在多边形内。"""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            t = (y - yi) / (yj - yi) if abs(yj - yi) > 1e-12 else 0.0
            if x < xi + t * (xj - xi):
                inside = not inside
        j = i
    return inside


def _in_restricted(x: float, y: float, z: float, airspaces) -> bool:
    """是否落在限制空域内（按 AGL 高度区间判断）。"""
    for a in airspaces or ():
        poly = getattr(a, "polygon", None) or []
        if len(poly) < 3:
            continue
        if not (a.floor_agl <= z <= a.ceiling_agl):
            continue
        if _point_in_poly(x, y, poly):
            return True
    return False


def _cell_blocked(x: float, y: float, z: float, obstacles, clearance: float,
                  airspaces=()) -> bool:
    if _in_restricted(x, y, z, airspaces):
        return True
    for o in obstacles:
        r = o.inflated_radius + clearance
        if math.hypot(x - o.x, y - o.y) <= r and (o.base_agl - clearance) <= z <= (o.top_agl + clearance):
            return True
    return False


def _proximity_penalty(x: float, y: float, obstacles) -> float:
    """靠近障碍物时附加代价, 促使航迹留出安全余量。"""
    pen = 0.0
    for o in obstacles:
        d = math.hypot(x - o.x, y - o.y) - o.inflated_radius
        if d < COMFORT_MARGIN:
            pen += (COMFORT_MARGIN - d) * COMFORT_WEIGHT
    return pen


def plan_astar(start, goal, obstacles, bounds: BBox, max_gradient: float,
               clearance: float = 0.0, airspaces=None) -> Optional[List[Tuple[float, float, float]]]:
    """3D 网格 A* 搜索(A* 算法, Hart et al. 1968)。"""
    nx = int(round((bounds.xmax - bounds.xmin) / XY_RES)) + 1
    ny = int(round((bounds.ymax - bounds.ymin) / XY_RES)) + 1
    nz = int(round((bounds.zmax - bounds.zmin) / Z_RES)) + 1

    def to_idx(p):
        return (int(round((p[0] - bounds.xmin) / XY_RES)),
                int(round((p[1] - bounds.ymin) / XY_RES)),
                int(round((p[2] - bounds.zmin) / Z_RES)))

    def to_world(ix, iy, iz):
        return (bounds.xmin + ix * XY_RES,
                bounds.ymin + iy * XY_RES,
                bounds.zmin + iz * Z_RES)

    start_idx = to_idx(start)
    goal_idx = to_idx(goal)

    # 邻居偏移(26 连通)
    nbrs = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            for dz in (-1, 0, 1) if not (dx == 0 and dy == 0 and dz == 0)]

    g = {start_idx: 0.0}
    parent = {}
    open_heap = []
    counter = 0
    heapq.heappush(open_heap, (geo.dist3d(start, goal), 0, counter, start_idx))

    while open_heap:
        _, gs, _, cur = heapq.heappop(open_heap)
        if gs > g.get(cur, math.inf) + 1e-9:
            continue  # 过期条目(该节点已以更低代价更新)
        if cur == goal_idx:
            break
        cx, cy, cz = to_world(*cur)
        for ddx, ddy, ddz in nbrs:
            nix, niy, niz = cur[0] + ddx, cur[1] + ddy, cur[2] + ddz
            if not (0 <= nix < nx and 0 <= niy < ny and 0 <= niz < nz):
                continue
            dh = math.hypot(ddx * XY_RES, ddy * XY_RES)
            if dh < 1e-6:
                continue  # 不允许纯垂直机动
            dz = ddz * Z_RES
            if abs(dz) > max_gradient * dh + 1e-6:
                continue  # 梯度约束
            wx, wy, wz = to_world(nix, niy, niz)
            if _cell_blocked(wx, wy, wz, obstacles, clearance, airspaces):
                continue
            step_cost = math.hypot(dh, dz) + _proximity_penalty(wx, wy, obstacles)
            new_g = g[cur] + step_cost
            nb = (nix, niy, niz)
            if new_g < g.get(nb, math.inf):
                g[nb] = new_g
                parent[nb] = cur
                h = geo.dist3d((wx, wy, wz), goal)
                counter += 1
                heapq.heappush(open_heap, (new_g + h, new_g, counter, nb))

    if goal_idx not in parent and goal_idx != start_idx:
        return None

    # 重建路径
    path = []
    cur = goal_idx
    while True:
        path.append(to_world(*cur))
        if cur == start_idx:
            break
        cur = parent[cur]
    path.reverse()
    return path


def plan_rrtstar(start, goal, obstacles, bounds: BBox, max_gradient: float,
                 clearance: float = 0.0, iters: int = 2500, step: float = 60.0,
                 goal_bias: float = 0.2, seed: int = 0) -> Optional[List[Tuple[float, float, float]]]:
    """RRT* 采样路径规划(Karaman & Frazzoli 2011), 用于备选或平滑。"""
    rnd = random.Random(seed)
    nodes = [(start, None, 0.0)]  # (point, parent_index, cost)
    best_goal_cost = math.inf
    best_goal_idx = -1

    def steer(frm, to):
        d = geo.dist3d(frm, to)
        t = min(1.0, step / d)
        x = frm[0] + (to[0] - frm[0]) * t
        y = frm[1] + (to[1] - frm[1]) * t
        z = frm[2] + (to[2] - frm[2]) * t
        # 梯度约束: 把垂直分量钳制到 max_gradient * 水平步长以内
        dh = math.hypot(x - frm[0], y - frm[1])
        maxdz = max_gradient * dh
        z = frm[2] + max(-maxdz, min(maxdz, z - frm[2]))
        return (x, y, z)

    for _ in range(iters):
        r = rnd.random()
        if r < goal_bias:
            sample = goal
        elif r < goal_bias + 0.4:
            # 沿起点-终点连线采样(含线性高度剖面), 引导树沿下降梯度生长
            t = rnd.random()
            sample = (start[0] + (goal[0] - start[0]) * t,
                      start[1] + (goal[1] - start[1]) * t,
                      start[2] + (goal[2] - start[2]) * t)
        else:
            # 用本次调用的随机源采样，保证 seed 真正可复现（原先用全局 random，测试会偶发失败）
            sample = (rnd.uniform(bounds.xmin, bounds.xmax),
                      rnd.uniform(bounds.ymin, bounds.ymax),
                      rnd.uniform(bounds.zmin, bounds.zmax))
        # 最近节点
        ni = 0
        nd = math.inf
        for i, (p, _, _) in enumerate(nodes):
            d = geo.dist3d(p, sample)
            if d < nd:
                nd, ni = d, i
        new = steer(nodes[ni][0], sample)
        # 梯度约束(相对父节点)
        dh = math.hypot(new[0] - nodes[ni][0][0], new[1] - nodes[ni][0][1])
        if dh > 1e-6 and abs(new[2] - nodes[ni][0][2]) > max_gradient * dh:
            continue
        if not geo.segment_free(nodes[ni][0], new, obstacles, clearance):
            continue
        new_cost = nodes[ni][2] + geo.dist3d(nodes[ni][0], new)
        new_idx = len(nodes)
        nodes.append((new, ni, new_cost))
        # 重连(rewiring)
        r = step * 1.6
        for i, (p, _, c) in enumerate(nodes):
            if i == new_idx:
                continue
            if geo.dist3d(p, new) <= r and geo.segment_free(p, new, obstacles, clearance):
                cand = new_cost + geo.dist3d(new, p)
                if cand < c:
                    nodes[i] = (p, new_idx, cand)
        # 目标连接: 连接半径内且到终点无碰撞, 记录为候选
        if geo.dist3d(new, goal) <= step * 2.5 and geo.segment_free(new, goal, obstacles, clearance):
            cand_cost = new_cost + geo.dist3d(new, goal)
            if cand_cost < best_goal_cost:
                best_goal_cost = cand_cost
                best_goal_idx = new_idx

    if best_goal_idx < 0:
        return None
    path = [goal]
    idx = best_goal_idx
    while idx is not None:
        path.append(nodes[idx][0])
        idx = nodes[idx][1]
    path.reverse()
    return path


def _segment_clear_of_airspace(a, c, airspaces) -> bool:
    """线段是否避开限制空域（沿线采样）。"""
    if not airspaces:
        return True
    dist = geo.dist3d(a, c)
    n = max(2, int(dist / 40.0) + 1)
    for i in range(n + 1):
        t = i / n
        x = a[0] + (c[0] - a[0]) * t
        y = a[1] + (c[1] - a[1]) * t
        z = a[2] + (c[2] - a[2]) * t
        if _in_restricted(x, y, z, airspaces):
            return False
    return True


def smooth_shortcut(path, obstacles, clearance: float, min_turn_radius: float,
                    airspaces=None) -> List[Tuple[float, float, float]]:
    """视线(shortcut)平滑 + 三点定圆曲率约束(Dubins 1957)。

    注意：平滑会"拉直"路径，必须同时校验**限制空域**，否则会把 A* 绕开的
    限飞区又切回去（本项目真实踩过这个坑）。
    """
    path = [tuple(p) for p in path]
    if len(path) <= 2:
        return path

    def turn_ok(pi: int, pk: int) -> bool:
        prev = path[pi - 1] if pi > 0 else None
        a, c = path[pi], path[pk]
        nxt = path[pk + 1] if pk < len(path) - 1 else None
        if prev is not None:
            if geo.turn_radius_from_points(prev, a, c) < min_turn_radius:
                return False
        if nxt is not None:
            if geo.turn_radius_from_points(a, c, nxt) < min_turn_radius:
                return False
        return True

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(path) - 2:
            a, c = path[i], path[i + 2]
            if (geo.segment_free(a, c, obstacles, clearance)
                    and _segment_clear_of_airspace(a, c, airspaces)
                    and turn_ok(i, i + 2)):
                del path[i + 1]
                changed = True
            else:
                i += 1
    return path


def resample(path, sample_dist: float = 30.0) -> List[Tuple[float, float, float]]:
    if len(path) < 2:
        return path
    out = [path[0]]
    for p, q in zip(path, path[1:]):
        d = geo.dist3d(p, q)
        if d < 1e-9:
            continue
        n = max(1, int(round(d / sample_dist)))
        for i in range(1, n + 1):
            t = i / n
            out.append((p[0] + (q[0] - p[0]) * t,
                        p[1] + (q[1] - p[1]) * t,
                        p[2] + (q[2] - p[2]) * t))
    return out


def build_4d_profile(path, limits, program_type: str) -> List[Waypoint]:
    """沿航迹积分速度/时间, 生成 (x,y,z,t) 四维剖面。"""
    if not path:
        return []
    # 累计距离
    cum = [0.0]
    for p, q in zip(path, path[1:]):
        cum.append(cum[-1] + geo.dist3d(p, q))
    total = cum[-1]
    cruise = (limits.min_speed + limits.max_speed) / 2.0
    wps: List[Waypoint] = []
    t = 0.0
    for i, (x, y, z) in enumerate(path):
        if program_type == "arrival":
            remain = total - cum[i]
            if remain < 800.0:
                speed = limits.min_speed + (cruise - limits.min_speed) * (remain / 800.0)
            else:
                speed = cruise
        else:  # departure 加速爬升
            if cum[i] < 800.0:
                speed = limits.min_speed + (cruise - limits.min_speed) * (cum[i] / 800.0)
            else:
                speed = cruise
        wps.append(Waypoint(x, y, z, speed=speed, t=t))
        if i < len(path) - 1:
            t += geo.dist3d(path[i], path[i + 1]) / max(speed, 1e-6)
    return wps


def build_missed_approach(threshold: Tuple[float, float, float], heading: float,
                          msa: float, limits, obstacles=None,
                          airspaces=None) -> List[Waypoint]:
    """复飞程序：沿着陆方向爬升，遇到障碍/限飞区就提前转向。

    标准复飞是"直线爬升到安全高度再掉头"。但直线一冲就是几公里：
        * 会扎进限制空域（SE 进场正对 NW 限飞区）
        * 会飞出画面，看起来像程序跑飞了
    所以这里做两件事：
        1) 直线段最长 1200 m；
        2) 沿线探测障碍/限飞区，发现冲突就**提前 120 m 转向**，
           并且自动选择"不撞的那一侧"（先试左转，不行再右转）。
    """
    mh = min(msa, 450.0)
    ux, uy = math.sin(math.radians(heading)), math.cos(math.radians(heading))
    grad = max(limits.climb_gradient, 0.05)
    obstacles = list(obstacles or ())
    airspaces = list(airspaces or ())

    SAFE = 15.0            # 比仿真检查的 10m 留更多余量

    def blocked_at(x, y, z):
        return (_in_restricted(x, y, z, airspaces)
                or _cell_blocked(x, y, z, obstacles, SAFE, ()))

    # ① 直线爬升能走多远
    d_straight = 1200.0
    step = 25.0
    d = 0.0
    while d < 1200.0:
        d += step
        x, y = threshold[0] + ux * d, threshold[1] + uy * d
        if blocked_at(x, y, d * grad):
            d_straight = max(300.0, d - 320.0)
            break

    # ② 直线段
    pts = [threshold]
    d = 0.0
    seg = 100.0
    while d < d_straight - 1e-6:
        d = min(d_straight, d + seg)
        pts.append((threshold[0] + ux * d, threshold[1] + uy * d, d * grad))
    turn_start = pts[-1]

    # ③ 180° 掉头：选一个不撞障碍/空域的方向（先左后右）
    arc_steps = 12
    best = None
    for sign in (1.0, -1.0):
        cand = list(pts)
        ok = True
        for i in range(1, arc_steps + 1):
            ang = math.pi * i / arc_steps
            lx = sign * limits.min_turn_radius * math.sin(ang)
            ly = limits.min_turn_radius * (1 - math.cos(ang))
            rx = lx * math.cos(math.radians(heading)) - ly * math.sin(math.radians(heading))
            ry = lx * math.sin(math.radians(heading)) + ly * math.cos(math.radians(heading))
            x, y = turn_start[0] + rx, turn_start[1] + ry
            z = min(mh, turn_start[2] + limits.min_turn_radius * ang * grad)
            if blocked_at(x, y, z):
                ok = False
                break
            cand.append((x, y, z))
        if ok:
            best = cand
            break
        if best is None:
            best = cand          # 两侧都不行就保留左转（至少形状是对的）
    pts = best or pts

    # ④ 自检：整条复飞段逐段验一遍，不通过就退化成一个"贴跑道口的短爬升"，
    #    宁可保守，也不能让画面上的线穿过障碍物。
    def _free(seq):
        for a, b in zip(seq, seq[1:]):
            if not geo.segment_free(a, b, obstacles, SAFE):
                return False
        return True

    if obstacles and not _free(pts):
        short = [threshold,
                 (threshold[0] + ux * 150.0, threshold[1] + uy * 150.0, 150.0 * grad),
                 (threshold[0] + ux * 300.0, threshold[1] + uy * 300.0, 300.0 * grad)]
        if _free(short):
            pts = short
    return [Waypoint(p[0], p[1], p[2]) for p in pts]


# 8 方位（方位角 = 从起降点看向该方向，真北为 0，顺时针）
DIRECTIONS = {
    "N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
    "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0,
}
DIRECTION_CN = {
    "N": "北", "NE": "东北", "E": "东", "SE": "东南",
    "S": "南", "SW": "西南", "W": "西", "NW": "西北",
}


def bearing_of(direction) -> Optional[float]:
    """把方向名（N/NE/...）或角度（0~359）统一成方位角；无法识别返回 None。"""
    if direction is None or direction == "":
        return None
    if isinstance(direction, (int, float)):
        return float(direction) % 360.0
    name = str(direction).strip().upper()
    if name in DIRECTIONS:
        return DIRECTIONS[name]
    try:
        return float(name) % 360.0
    except ValueError:
        return None


def direction_name(bearing: float) -> str:
    """方位角 -> 最近的 8 方位名。"""
    b = float(bearing) % 360.0
    best = min(DIRECTIONS.items(), key=lambda kv: min(abs(kv[1] - b), 360 - abs(kv[1] - b)))
    return best[0]


def _entry_point(heading: float, dist: float) -> Tuple[float, float, float]:
    ux, uy = math.sin(math.radians(heading)), math.cos(math.radians(heading))
    return (-ux * dist, -uy * dist, 0.0)


def _exit_point(heading: float, dist: float, alt: float) -> Tuple[float, float, float]:
    ux, uy = math.sin(math.radians(heading)), math.cos(math.radians(heading))
    return (ux * dist, uy * dist, alt)


def replan_arrival(env: EnvSnapshot, rules: dict, method: str = "astar",
                   direction=None) -> FlightProgram:
    """进近程序动态重规划。

    direction: 进场方向（飞机「从哪边来」，N/NE/.../NW 或方位角）。
               指定后，着陆航向 = 方向 + 180°，入口点落在该方向 2500 m 处。
    """
    msa = calc_msa(env.obstacles, float(rules.get("MSA_MARGIN", 300)))
    moc = float(rules.get("MOC_APPROACH", 75))  # 障碍物净空按 MOC 膨胀
    bearing = bearing_of(direction)
    if bearing is None:
        heading = env.airport.runway_heading
        dir_name = direction_name(heading + 180.0)
    else:
        heading = (bearing + 180.0) % 360.0       # 从该方向进场 -> 反向着陆
        dir_name = direction_name(bearing)
    entry = _entry_point(heading, 2500.0)
    start = (entry[0], entry[1], 250.0)
    goal = (0.0, 0.0, 0.0)
    max_grad = max(env.limits.climb_gradient, env.limits.descent_gradient)

    bounds = _compute_bounds([start, goal], env.obstacles, zmax=520.0)
    path = plan_astar(start, goal, env.obstacles, bounds, max_grad, clearance=moc,
                      airspaces=getattr(env, "airspaces", None))
    if path is None:
        path = plan_rrtstar(start, goal, env.obstacles, bounds, max_grad, clearance=moc)
    if path is None:
        # 极端兜底: 直线进近
        path = [start, goal]

    path = smooth_shortcut(path, env.obstacles, moc, env.limits.min_turn_radius,
                           airspaces=getattr(env, "airspaces", None))
    path = resample(path, 30.0)
    wps = build_4d_profile(path, env.limits, "arrival")
    miss = build_missed_approach(goal, heading, msa, env.limits,
                                 obstacles=env.obstacles, airspaces=getattr(env, "airspaces", None))
    return FlightProgram("arrival", wps, miss, source="dynamic", direction=dir_name)


def replan_departure(env: EnvSnapshot, rules: dict, method: str = "astar",
                     direction=None) -> FlightProgram:
    """离场程序动态重规划。

    direction: 离场方向（飞机「往哪边飞」）。指定后起飞航向 = 该方向。
    """
    msa = calc_msa(env.obstacles, float(rules.get("MSA_MARGIN", 300)))
    moc = float(rules.get("MOC_DEPARTURE", 90))
    bearing = bearing_of(direction)
    if bearing is None:
        heading = env.airport.runway_heading
        dir_name = direction_name(heading)
    else:
        heading = bearing
        dir_name = direction_name(bearing)
    start = (0.0, 0.0, 0.0)
    goal = _exit_point(heading, 3000.0, 300.0)
    max_grad = max(env.limits.climb_gradient, env.limits.descent_gradient)

    bounds = _compute_bounds([start, goal], env.obstacles, zmax=520.0)
    path = plan_astar(start, goal, env.obstacles, bounds, max_grad, clearance=moc,
                      airspaces=getattr(env, "airspaces", None))
    if path is None:
        path = plan_rrtstar(start, goal, env.obstacles, bounds, max_grad, clearance=moc)
    if path is None:
        path = [start, goal]

    path = smooth_shortcut(path, env.obstacles, moc, env.limits.min_turn_radius,
                           airspaces=getattr(env, "airspaces", None))
    path = resample(path, 30.0)
    wps = build_4d_profile(path, env.limits, "departure")
    miss = build_missed_approach((0.0, 0.0, 0.0), heading, msa, env.limits,
                                 obstacles=env.obstacles, airspaces=getattr(env, "airspaces", None))
    return FlightProgram("departure", wps, miss, source="dynamic", direction=dir_name)
