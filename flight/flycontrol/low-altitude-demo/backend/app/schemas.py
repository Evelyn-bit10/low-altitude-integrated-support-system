"""API 请求体模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MeteoUpdate(BaseModel):
    wind_speed: float = Field(5.0, description="风速 m/s")
    wind_dir: float = Field(0.0, description="风向 度")
    gust: float = Field(8.0, description="阵风 m/s")
    visibility: float = Field(8000.0, description="能见度 米")
    cloud_base: float = Field(600.0, description="云底高 AGL 米")
    turbulence: int = Field(1, ge=1, le=4)
    wind_shear: int = Field(1, ge=1, le=4)
    temperature: float = 20.0
    pressure: float = 1013.0
    precipitation: float = Field(0.0, ge=0.0, le=50.0, description="降水量 mm/h")


class ReplanRequest(BaseModel):
    program_type: str = Field("arrival", description="arrival 进近 / departure 离场")
    direction: str | None = Field(None, description="进出场方向 N/NE/E/SE/S/SW/W/NW 或方位角")


class GenerateRequest(BaseModel):
    program_type: str = Field("arrival", description="arrival 进近 / departure 离场")
    direction: str = Field("S", description="进出场方向 N/NE/E/SE/S/SW/W/NW")
    mode: str = Field("template", description="template=方案库直出 / dynamic=动态重规划")


class ObstacleToggle(BaseModel):
    id: int
    active: bool
