# config_stands.py
"""机位配置"""
from typing import Dict, List, Any

# ================== 机位配置 ==================
# 机位定义
DRONE_STANDS = [
    # 室内机位
    {"id": "in_01", "name": "室内机位 1", "type": "indoor", "priority": 1, 
     "description": "室内标准机位", "features": ["rain_proof", "wind_proof"]},
    {"id": "in_02", "name": "室内机位 2", "type": "indoor", "priority": 1, 
     "description": "室内标准机位", "features": ["rain_proof", "wind_proof"]},
    {"id": "in_03", "name": "室内机位 3", "type": "indoor", "priority": 2, 
     "description": "室内备用机位", "features": ["rain_proof", "wind_proof"]},
    
    # 室外机位
    {"id": "out_01", "name": "室外机位 1", "type": "outdoor", "priority": 1, 
     "description": "室外标准机位", "features": ["normal"]},
    {"id": "out_02", "name": "室外机位 2", "type": "outdoor", "priority": 1, 
     "description": "室外标准机位", "features": ["normal"]},
    {"id": "out_03", "name": "室外机位 3", "type": "outdoor", "priority": 2, 
     "description": "室外备用机位", "features": ["normal"]},
    {"id": "out_04", "name": "室外防风机位", "type": "outdoor", "priority": 1, 
     "description": "防风加强机位", "features": ["wind_proof"]},
]

# 天气阈值配置
WEATHER_THRESHOLDS = {
    "rain": {
        "light": 0.5,      # 小雨 (mm/h)
        "moderate": 4.0,    # 中雨
        "heavy": 15.0,      # 大雨
    },
    "wind": {
        "moderate": 5.4,    # 3-4级风 (m/s)
        "strong": 10.8,     # 5-6级风
        "gale": 17.2,       # 8级风
    },
    "visibility": {
        "poor": 3.0,        # 较差 (km)
        "very_poor": 1.0,   # 很差
    },
    "temperature": {
        "cold": -10,        # 低温
        "hot": 40,          # 高温
    }
}

# 无人机抗风等级配置（部分机型示例）
DRONE_WIND_RESISTANCE = {
    "大疆 M300": {"level": 7, "rain_proof": True, "max_wind": 15},
    "大疆 M210": {"level": 5, "rain_proof": True, "max_wind": 12},
    "大疆 M600": {"level": 6, "rain_proof": False, "max_wind": 12},
    "大疆 Phantom 4": {"level": 4, "rain_proof": False, "max_wind": 10},
    "大疆 Mavic 2": {"level": 5, "rain_proof": False, "max_wind": 10.5},
    "大疆 Mavic 3": {"level": 5, "rain_proof": True, "max_wind": 12},
    "大疆 Mini 3": {"level": 4, "rain_proof": False, "max_wind": 8.5},
    "自定义无人机": {"level": 5, "rain_proof": False, "max_wind": 10},
}