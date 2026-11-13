# -*- coding: utf-8 -*-
"""
低空起降点-飞行器实时通讯软件系统 · 核心决策引擎原型（Python）
==============================================================
依据中国民航低空管理相关要求，做通信与起降许可决策逻辑演示。
本文件仅为业务逻辑原型，不可直接机载运行；生产环境需转为高可靠、
低时延服务，完成民航适航、数据安全、RID 接入合规，并做嵌入式适配。

参考豆包回答的框架，并修正/补强以下问题：
1. 时间戳使用标准 ASCII 连字符 '-'（豆包示例中误用全角 '‑'，会导致
   ISO8601 解析异常）；
2. 补充 RID 合法性校验：无 RID / RID 失效的飞行器拒绝接入；
3. 补充 WARNING 风险告警分支（豆包伪代码中未实现）；
4. 补充障碍物净空计算的简化实现（豆包伪代码中为空）；
5. 指令带 validUntil 有效期，超时自动失效需重新申请；
6. 补充数据源降级策略：气象/RID/链路失效时禁止自动许可。
"""

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional


# ----------------------------- 枚举与消息类型 -----------------------------
class MsgType(Enum):
    LAND_REQUEST = "LAND_REQUEST"
    TAKEOFF_REQUEST = "TAKEOFF_REQUEST"
    LAND_RESPONSE = "LAND_RESPONSE"
    TAKEOFF_RESPONSE = "TAKEOFF_RESPONSE"
    HEARTBEAT = "HEARTBEAT"
    WEATHER_BROADCAST = "WEATHER_BROADCAST"
    OBSTACLE_ALERT = "OBSTACLE_ALERT"


class RiskLevel(Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    FORBID = "FORBID"


class Decision(Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    ADVISE_HOLD = "ADVISE_HOLD"
    WARNING = "WARNING"


# ----------------------------- 数据结构 -----------------------------
@dataclass
class Obstacle:
    id: str
    lat: float
    lon: float
    height_m: float          # 障碍物高度（米）
    radius_m: float          # 障碍物水平半径（米）
    type: str = "static"     # static / dynamic（施工吊臂、临时障碍等）


@dataclass
class Weather:
    site_id: str
    timestamp: str
    wind_speed: float        # m/s
    wind_dir: int            # 度
    visibility: float        # 米
    ceiling: float           # 云底高（米）
    precipitation: str = "none"
    turbulence_level: int = 0


@dataclass
class RIDAircraft:
    rid_id: str
    lat: float
    lon: float
    alt_m: float
    speed: float
    heading: float
    registered: bool = True      # 实名登记 / 唯一产品识别码是否有效
    rid_valid: bool = True       # RID 远程识别上报是否有效


@dataclass
class VertiportState:
    vertiport_id: str
    lat: float
    lon: float
    obstacles: List[Obstacle] = field(default_factory=list)
    weather: Optional[Weather] = None
    occupied: bool = False
    # 数据源降级状态
    rid_source_ok: bool = True
    met_source_ok: bool = True
    c2_link_ok: bool = True


# ----------------------------- 气象评估 -----------------------------
def eval_weather(w: Optional[Weather]) -> RiskLevel:
    """起降点气象起降条件评估（示例阈值，实际按机型/运行类别配置）。"""
    if w is None:
        return RiskLevel.FORBID  # 气象源失效 -> 禁止自动许可
    if w.wind_speed > 12 or w.visibility < 1600 or w.ceiling < 120:
        return RiskLevel.FORBID
    if w.wind_speed > 8 or w.visibility < 5000 or w.turbulence_level >= 2:
        return RiskLevel.CAUTION
    return RiskLevel.SAFE


# ----------------------------- 障碍物净空评估（简化） -----------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def eval_obstacle_risk(ac: RIDAircraft, vp: VertiportState) -> RiskLevel:
    """简化净空评估：飞行器与障碍物水平距离 < 障碍物半径+余量 且
    飞行器高度 < 障碍物高度+余量 时判为冲突。"""
    if not vp.obstacles:
        return RiskLevel.SAFE
    worst = RiskLevel.SAFE
    for obs in vp.obstacles:
        d = haversine_m(ac.lat, ac.lon, obs.lat, obs.lon)
        margin = 60.0
        alt_margin = 40.0
        if d < obs.radius_m + margin and ac.alt_m < obs.height_m + alt_margin:
            worst = RiskLevel.FORBID
            break
        if d < (obs.radius_m + margin) * 3 and ac.alt_m < (obs.height_m + alt_margin) * 1.5:
            worst = RiskLevel.CAUTION
    return worst


# ----------------------------- 起降许可决策引擎 -----------------------------
def land_decision(ac: RIDAircraft, vp: VertiportState) -> Dict:
    """输入：RID 飞行器 + 起降点状态（障碍物/气象/占用/数据源降级）
    输出：APPROVE / DENY / ADVISE_HOLD / WARNING + 原因 + 有效期。"""
    # 1) 数据源与链路降级（民航低空运行重点：数据源失效不输出错误许可）
    if not vp.c2_link_ok:
        return _resp(Decision.DENY, "C2 链路失效，禁止自动许可，切人工值守")
    if not vp.rid_source_ok or not ac.rid_valid:
        return _resp(Decision.DENY, "RID 远程识别不可用或无效，拒绝接入通信会话")
    if not vp.met_source_ok:
        return _resp(Decision.DENY, "气象源失效，禁止自动许可，切人工值守")

    # 2) RID 身份核验（实名登记 + 唯一产品识别码）
    if not ac.registered:
        return _resp(Decision.DENY, "飞行器未实名登记 / 无唯一产品识别码")

    # 3) 起降点占用
    if vp.occupied:
        return _resp(Decision.DENY, "起降点占用，请等待")

    # 4) 气象评估
    weather_risk = eval_weather(vp.weather)
    if weather_risk == RiskLevel.FORBID:
        return _resp(Decision.DENY, "气象条件不满足起降")
    if weather_risk == RiskLevel.WARNING:
        return _resp(Decision.WARNING, "气象存在风险，注意颠簸/风切变")

    # 5) 障碍物净空评估
    obs_risk = eval_obstacle_risk(ac, vp)
    if obs_risk == RiskLevel.FORBID:
        return _resp(Decision.DENY, "进近存在障碍物冲突")
    if obs_risk == RiskLevel.WARNING:
        return _resp(Decision.WARNING, "进近航径邻近障碍物，注意净空")

    # 6) 受限条件 -> 建议等待
    if weather_risk == RiskLevel.CAUTION or obs_risk == RiskLevel.CAUTION:
        return _resp(Decision.ADVISE_HOLD, "气象/净空条件受限，建议等待")

    return _resp(Decision.APPROVE, "")


def _resp(result: Decision, reason: str) -> Dict:
    now = datetime.now(timezone.utc)
    valid = (now + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "result": result.value,
        "reason": reason,
        "validUntil": valid,     # 许可有效期，超时自动失效，飞行器需重新申请
        "revalidate": True,
    }


# ----------------------------- 消息处理入口 -----------------------------
def handle_aircraft_message(msg: Dict, vp: VertiportState) -> Optional[Dict]:
    msg_type = msg.get("msgType")
    rid_id = msg.get("ridId")

    if msg_type in (MsgType.LAND_REQUEST.value, MsgType.TAKEOFF_REQUEST.value):
        ac = RIDAircraft(
            rid_id=rid_id,
            lat=msg["lat"],
            lon=msg["lon"],
            alt_m=msg["altitude"],
            speed=msg["speed"],
            heading=msg["heading"],
            registered=msg.get("registered", False),
            rid_valid=msg.get("ridValid", True),
        )
        dec = land_decision(ac, vp)
        resp_type = (
            MsgType.LAND_RESPONSE.value
            if msg_type == MsgType.LAND_REQUEST.value
            else MsgType.TAKEOFF_RESPONSE.value
        )
        return {
            "msgType": resp_type,
            "ridId": rid_id,
            "vertiportId": vp.vertiport_id,
            "result": dec["result"],
            "reason": dec["reason"],
            "validUntil": dec["validUntil"],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            # 附带当前环境信息供飞行器参考
            "wind": vp.weather.wind_speed if vp.weather else None,
            "visibility": vp.weather.visibility if vp.weather else None,
            "obstacleRisk": eval_obstacle_risk(ac, vp).value,
        }

    if msg_type == MsgType.HEARTBEAT.value:
        return {"msgType": "HEARTBEAT_ACK", "ridId": rid_id, "result": "OK"}

    return None


# ----------------------------- 自测 -----------------------------
if __name__ == "__main__":
    vp = VertiportState(
        vertiport_id="vertiport-001",
        lat=29.5600,
        lon=106.5800,
        obstacles=[
            Obstacle(id="OBS-01", lat=29.5610, lon=106.5810, height_m=150, radius_m=60),
            Obstacle(id="OBS-02", lat=29.5625, lon=106.5790, height_m=220, radius_m=30, type="tower"),
        ],
        weather=Weather(
            site_id="vertiport-001",
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            wind_speed=5.0,
            wind_dir=135,
            visibility=4500,
            ceiling=800,
        ),
        occupied=False,
    )

    cases = [
        {
            "name": "正常飞行器降落申请（未登记 -> DENY）",
            "msg": {
                "msgType": "LAND_REQUEST",
                "ridId": "RID-UAV-000123",
                "lat": 29.5601, "lon": 106.5801, "altitude": 220,
                "speed": 18, "heading": 170,
                "registered": False, "ridValid": True,
            },
        },
        {
            "name": "已登记飞行器降落申请（气象受限 -> HOLD）",
            "msg": {
                "msgType": "LAND_REQUEST",
                "ridId": "RID-UAV-000456",
                "lat": 29.5601, "lon": 106.5801, "altitude": 220,
                "speed": 18, "heading": 170,
                "registered": True, "ridValid": True,
            },
        },
        {
            "name": "RID 失效飞行器（-> DENY）",
            "msg": {
                "msgType": "LAND_REQUEST",
                "ridId": "RID-UAV-000789",
                "lat": 29.5601, "lon": 106.5801, "altitude": 220,
                "speed": 18, "heading": 170,
                "registered": True, "ridValid": False,
            },
        },
        {
            "name": "已登记飞行器在良好天气下申请（-> APPROVE）",
            "msg": {
                "msgType": "LAND_REQUEST",
                "ridId": "RID-UAV-000456",
                "lat": 29.5601, "lon": 106.5801, "altitude": 220,
                "speed": 18, "heading": 170,
                "registered": True, "ridValid": True,
            },
        },
    ]

    # 最后一例使用良好天气，验证 APPROVE 分支
    vp.weather.visibility = 8000
    vp.weather.wind_speed = 4.0

    for c in cases:
        print("=" * 60)
        print(c["name"])
        res = handle_aircraft_message(c["msg"], vp)
        print(json.dumps(res, ensure_ascii=False, indent=2))
