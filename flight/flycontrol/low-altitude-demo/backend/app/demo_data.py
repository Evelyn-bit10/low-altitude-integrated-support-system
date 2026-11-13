"""内置演示场景(无数据库 / SQLite 回退时的种子数据)。

与 db/init/02_seed.sql 保持一致: 起降点 LAC-DEMO(elev 60m, 跑道方向 0 度),
5 个障碍物(1 动态塔吊 + 4 固定), 1 个西北限飞区, 规则参数, 1 个默认进近预案。
坐标采用 ENU 米(x 东向, y 北向), 高度为 AGL。
"""
from __future__ import annotations

from .domain import AircraftLimits, Airport, Airspace, Meteo, Obstacle

AIRPORT = Airport(
    code="LAC-DEMO", name="演示垂直起降场",
    lat=30.0, lon=120.0, elevation=60.0,
    safe_radius=500.0, runway_heading=0.0,
)

# 障碍物: 施工塔吊位于进近航径上(动态, 可切换), 用于演示系统实时重规划
OBSTACLES = [
    Obstacle(id=1, name="施工塔吊(动态)", obs_type=2, x=40.0, y=-1800.0,
             base_agl=0.0, top_agl=150.0, radius=25.0, buffer=60.0),
    Obstacle(id=2, name="高层建筑(固定)", obs_type=1, x=250.0, y=400.0,
             base_agl=0.0, top_agl=110.0, radius=40.0, buffer=60.0),
    Obstacle(id=3, name="通信铁塔(固定)", obs_type=1, x=-500.0, y=600.0,
             base_agl=0.0, top_agl=160.0, radius=20.0, buffer=60.0),
    Obstacle(id=4, name="山地(固定)", obs_type=1, x=-1000.0, y=100.0,
             base_agl=0.0, top_agl=240.0, radius=200.0, buffer=80.0),
    Obstacle(id=5, name="高压线塔(固定)", obs_type=1, x=600.0, y=-300.0,
             base_agl=0.0, top_agl=60.0, radius=30.0, buffer=60.0),
]

AIRSPACES = [
    Airspace(
        id=1, name="临时限飞区-NW",
        polygon=[(-1200.0, 600.0), (-400.0, 600.0), (-400.0, 1400.0), (-1200.0, 1400.0)],
        floor_agl=0.0, ceiling_agl=340.0,
    )
]

RULES = {
    "MOC_APPROACH": "75",
    "MOC_DEPARTURE": "90",
    "MSA_MARGIN": "300",
    "OAS_HALF_WIDTH0": "100",
    "OAS_SPREAD": "0.15",
    "OAS_GLIDESLOPE_DEG": "5.7",
    "OAS_FINAL_DIST": "1500",
    "RISK_W_OBSTACLE": "0.45",
    "RISK_W_METEO": "0.35",
    "RISK_W_AIRSPACE": "0.20",
    "RISK_TH_SAFE": "20",
    "RISK_TH_NORMAL": "40",
    "RISK_TH_WARNING": "70",
}

PLANS = [
    {
        "id": 1, "point_code": "LAC-DEMO", "plan_name": "标准南向进近预案",
        "plan_type": 1, "wind_range": "0-8", "visi_range": "1000-99999",
        "is_default": 1,
        "waypoints": [
            {"x": 0, "y": -1500, "z": 180},
            {"x": 0, "y": -800, "z": 100},
            {"x": 0, "y": 0, "z": 0},
        ],
    }
]

# 初始"生效"障碍物: 动态塔吊(id=1)默认关闭, 演示时可一键激活触发实时重规划
ACTIVE_OBSTACLE_IDS = {2, 3, 4, 5}

DEFAULT_METEO = Meteo()
DEFAULT_LIMITS = AircraftLimits()
