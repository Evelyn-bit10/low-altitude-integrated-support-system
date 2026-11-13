"""领域数据类: 全部几何量统一采用以起降点为原点的本地 ENU 坐标系。
    - x: 东向 (米)
    - y: 北向 (米)
    - z: 相对起降点标高的高度 (米, AGL)
    障碍物/航迹点均由经纬度+标高经 geometry 模块转换而来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Airport:
    code: str
    name: str
    lat: float
    lon: float
    elevation: float          # 起降点标高 MSL(m)
    safe_radius: float = 500.0
    runway_heading: float = 0.0   # 主起降方向(真北向, 度)


@dataclass
class Obstacle:
    id: int
    name: str
    obs_type: int             # 1 固定  2 临时动态
    x: float                  # ENU 东向 (米)
    y: float                  # ENU 北向 (米)
    base_agl: float           # 底部高度 AGL(m)
    top_agl: float            # 顶部高度 AGL(m)
    radius: float = 30.0      # 水平半径 (米)
    buffer: float = 60.0      # 安全缓冲区 (米)

    @property
    def inflated_radius(self) -> float:
        return self.radius + self.buffer


@dataclass
class Meteo:
    wind_speed: float = 5.0      # m/s
    wind_dir: float = 0.0        # 度
    gust: float = 8.0            # m/s
    visibility: float = 8000.0   # 米
    cloud_base: float = 600.0    # AGL(m)
    turbulence: int = 1          # 1~4 级
    wind_shear: int = 1          # 1~4 级
    temperature: float = 20.0
    pressure: float = 1013.0
    precipitation: float = 0.0   # 降水量 mm/h（0=无雨，>10 大雨）


@dataclass
class Airspace:
    id: int
    name: str
    polygon: List[Tuple[float, float]]   # ENU (x, y) 米, 逆时针或顺时针均可
    floor_agl: float
    ceiling_agl: float


@dataclass
class AircraftLimits:
    climb_gradient: float = 0.10     # 最大爬升梯度(垂直/水平)
    descent_gradient: float = 0.12   # 最大下降梯度
    min_turn_radius: float = 200.0   # 最小转弯半径(米), 对应 Dubins 曲率约束
    min_speed: float = 20.0          # m/s
    max_speed: float = 60.0          # m/s
    max_crosswind: float = 12.0      # m/s
    approach_angle_deg: float = 3.0  # 下滑角(度)


@dataclass
class Waypoint:
    x: float
    y: float
    z: float
    speed: float = 0.0
    t: float = 0.0

    def as_dict(self) -> dict:
        return {"x": round(self.x, 1), "y": round(self.y, 1), "z": round(self.z, 1),
                "speed": round(self.speed, 1), "t": round(self.t, 1)}


@dataclass
class FlightProgram:
    program_type: str                                  # 'arrival' | 'departure' | 'missed'
    waypoints: List[Waypoint] = field(default_factory=list)
    miss_approach: List[Waypoint] = field(default_factory=list)
    version: str = "v0"
    plan_id: int = 0                                   # 预案切换为预案ID, 动态生成为 0
    source: str = "dynamic"                            # 'static' | 'plan' | 'dynamic'
    direction: Optional[str] = None                    # 进出场方向 N/NE/E/SE/S/SW/W/NW
    std_name: Optional[str] = None                     # 标准程序名，如 ARR-S

    @property
    def points(self) -> List[Tuple[float, float, float]]:
        return [(w.x, w.y, w.z) for w in self.waypoints]


@dataclass
class EnvSnapshot:
    """一次调度周期所采集的某起降点运行环境。"""
    airport: Airport
    obstacles: List[Obstacle]
    airspaces: List[Airspace]
    meteo: Meteo
    limits: AircraftLimits
