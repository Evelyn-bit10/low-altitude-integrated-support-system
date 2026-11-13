# utils/weather_analyzer.py
"""天气分析工具，用于根据天气自动分配机位"""

from typing import Dict, List, Optional
from datetime import datetime

from config_stands import WEATHER_THRESHOLDS, DRONE_WIND_RESISTANCE


class WeatherAnalyzer:
    """天气分析器"""
    
    def __init__(self):
        self.thresholds = WEATHER_THRESHOLDS
        
    def analyze_weather_risk(self, weather_data: Dict) -> Dict:
        """
        分析天气风险等级
        
        Returns:
            风险分析结果
        """
        risks = {
            "rain_risk": self._analyze_rain_risk(weather_data),
            "wind_risk": self._analyze_wind_risk(weather_data),
            "visibility_risk": self._analyze_visibility_risk(weather_data),
            "temperature_risk": self._analyze_temperature_risk(weather_data),
            "overall_risk": "low",  # 默认低风险
            "recommendation": "outdoor"  # 默认推荐室外
        }
        
        # 计算整体风险
        risk_levels = {
            "rain_risk": risks["rain_risk"],
            "wind_risk": risks["wind_risk"],
            "visibility_risk": risks["visibility_risk"],
            "temperature_risk": risks["temperature_risk"]
        }
        
        # 如果有任何高风险，整体为高风险
        if any(level == "high" for level in risk_levels.values()):
            risks["overall_risk"] = "high"
            risks["recommendation"] = "indoor"
        # 如果有多个中风险，整体为中风险
        elif sum(1 for level in risk_levels.values() if level == "medium") >= 2:
            risks["overall_risk"] = "medium"
            risks["recommendation"] = "indoor"
        # 如果有单个中风险，整体为低风险但建议注意
        elif any(level == "medium" for level in risk_levels.values()):
            risks["overall_risk"] = "low_medium"
            risks["recommendation"] = "outdoor_with_caution"
            
        return risks
    
    def _analyze_rain_risk(self, weather_data: Dict) -> str:
        """分析降雨风险"""
        precip = weather_data.get("precipitation", 0)
        condition = weather_data.get("condition", "").lower()
        
        # 根据降水量判断
        if precip >= self.thresholds["rain"]["heavy"] or "大雨" in condition:
            return "high"
        elif precip >= self.thresholds["rain"]["moderate"] or "中雨" in condition:
            return "medium"
        elif precip >= self.thresholds["rain"]["light"] or "小雨" in condition:
            return "low"
        else:
            return "none"
    
    def _analyze_wind_risk(self, weather_data: Dict) -> str:
        """分析风力风险"""
        wind_speed = weather_data.get("wind_speed", 0)
        
        if wind_speed >= self.thresholds["wind"]["gale"]:
            return "high"
        elif wind_speed >= self.thresholds["wind"]["strong"]:
            return "medium"
        elif wind_speed >= self.thresholds["wind"]["moderate"]:
            return "low"
        else:
            return "none"
    
    def _analyze_visibility_risk(self, weather_data: Dict) -> str:
        """分析能见度风险"""
        visibility = weather_data.get("visibility", 10)
        
        if visibility <= self.thresholds["visibility"]["very_poor"]:
            return "high"
        elif visibility <= self.thresholds["visibility"]["poor"]:
            return "medium"
        else:
            return "none"
    
    def _analyze_temperature_risk(self, weather_data: Dict) -> str:
        """分析温度风险"""
        temp = weather_data.get("temperature", 20)
        
        if temp >= self.thresholds["temperature"]["hot"] or temp <= self.thresholds["temperature"]["cold"]:
            return "medium"
        else:
            return "none"
    
    def get_best_stand_for_drone(
        self,
        drone_model: str,
        weather_data: Dict,
        occupied_stands: List[str],
        stands: List[Dict],
    ) -> Optional[Dict]:
        """
        根据天气为特定无人机推荐最佳机位
        
        Args:
            drone_model: 无人机型号
            weather_data: 天气数据
            occupied_stands: 已占用的机位ID列表
            
        Returns:
            推荐的机位配置
        """
        risks = self.analyze_weather_risk(weather_data)
        drone_specs = DRONE_WIND_RESISTANCE.get(drone_model, {})
        
        # 过滤出空闲机位（仅从“当前存在的机位集合”中挑选）
        available_stands = [s for s in (stands or []) if s.get("id") not in occupied_stands]
        
        if not available_stands:
            return None
        
        # 根据风险等级筛选机位
        if risks["overall_risk"] == "high":
            # 高风险：只考虑室内机位
            candidates = [s for s in available_stands if s["type"] == "indoor"]
        elif risks["overall_risk"] == "medium":
            # 中风险：优先室内，但如果无人机防雨也可以考虑室外
            if drone_specs.get("rain_proof", False):
                candidates = available_stands
            else:
                candidates = [s for s in available_stands if s["type"] == "indoor"]
        else:
            # 低风险：所有机位都可用
            candidates = available_stands
        
        if not candidates:
            # 如果没有符合条件的，使用所有空闲机位
            candidates = available_stands
        
        # 按优先级排序
        candidates.sort(key=lambda x: x["priority"])
        
        return candidates[0]
    
    def get_weather_warning(self, weather_data: Dict) -> str:
        """获取天气警告信息"""
        risks = self.analyze_weather_risk(weather_data)
        warnings = []
        
        rain_risk = risks["rain_risk"]
        if rain_risk == "high":
            warnings.append("⚠️ 大雨预警")
        elif rain_risk == "medium":
            warnings.append("⚠️ 中雨预警")
        elif rain_risk == "low":
            warnings.append("☔ 有小雨")
            
        wind_risk = risks["wind_risk"]
        if wind_risk == "high":
            warnings.append("💨 强风预警")
        elif wind_risk == "medium":
            warnings.append("💨 大风预警")
        elif wind_risk == "low":
            warnings.append("🌬️ 有风")
            
        vis_risk = risks["visibility_risk"]
        if vis_risk == "high":
            warnings.append("🌫️ 低能见度预警")
        elif vis_risk == "medium":
            warnings.append("🌫️ 能见度较差")
            
        temp_risk = risks["temperature_risk"]
        if temp_risk == "medium":
            temp = weather_data.get("temperature")
            if temp >= WEATHER_THRESHOLDS["temperature"]["hot"]:
                warnings.append("🔥 高温预警")
            else:
                warnings.append("❄️ 低温预警")
        
        if not warnings:
            return "✅ 天气良好"
        
        return " | ".join(warnings)