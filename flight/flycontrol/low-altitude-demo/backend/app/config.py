"""应用配置: 全部可通过环境变量覆盖。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


def _json_env(name: str):
    """把 JSON 形式的环境变量解析成 dict；解析失败返回空 dict。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class Settings:
    database_url: str        # Postgres(SQLAlchemy 驱动) 或 sqlite
    dispatch_interval: float # 调度周期(秒)
    auth_enabled: bool       # 演示阶段关闭鉴权

    # ---- 多设备态势去重（第二部分功能）----
    node_id: str = "NODE-A"          # 本节点标识，写入 traffic.source_node
    dedup_enabled: bool = True       # 是否启用同一性判定与去重
    dedup_v_max: float = 30.0        # 门限速度上限 m/s（门限 = v_max*Δt + 3σ）
    dedup_sigma_m: float = 15.0      # 单源位置误差 σ（米）
    dedup_ttl: float = 15.0          # 无观测后航迹保留时长（秒）
    dedup_gate_k: float = 3.44       # 门限系数（χ²(2,99.7%)）
    dedup_default_sigma: float = 20.0  # 未标定源的默认 σ（米）
    dedup_sigma_floor: float = 8.0   # σ 下限，防止低估导致漏配
    dedup_source_sigmas: dict = None  # {"A-RID": 10, "B-RID": 30}
    dedup_autocalib: bool = True     # 用双源残差在线校正 σ 尺度
    dedup_calib_samples: int = 200   # 累计多少对样本后更新一次

    # ---- 对外推送（UOM / 地方平台）----
    push_enabled: bool = True        # 是否启用推送
    push_mode: str = "dry-run"       # dry-run 本地演示 / http 真实发送
    push_endpoint: str = "http://127.0.0.1:8099/uom/v1/messages"
    push_app_key: str = "demo-app"
    push_app_secret: str = "demo-secret"
    push_interval: float = 2.0       # 发件箱轮询周期（秒）
    push_track_interval: float = 5.0 # 态势推送间隔（秒）
    push_batch: int = 20             # 每轮最多发几条
    push_timeout: float = 5.0
    outbox_path: str = "push_outbox.db"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./flight_demo.db"),
            dispatch_interval=float(os.getenv("DISPATCH_INTERVAL", "2")),
            auth_enabled=os.getenv("AUTH_ENABLED", "false").lower() in ("1", "true", "yes"),
            node_id=os.getenv("NODE_ID", "NODE-A"),
            dedup_enabled=os.getenv("DEDUP_ENABLED", "true").lower() in ("1", "true", "yes"),
            dedup_v_max=float(os.getenv("DEDUP_V_MAX", "30")),
            dedup_sigma_m=float(os.getenv("DEDUP_SIGMA_M", "15")),
            dedup_ttl=float(os.getenv("DEDUP_TTL", "15")),
            push_enabled=os.getenv("PUSH_ENABLED", "true").lower() in ("1", "true", "yes"),
            push_mode=os.getenv("PUSH_MODE", "dry-run"),
            push_endpoint=os.getenv("PUSH_ENDPOINT", "http://127.0.0.1:8099/uom/v1/messages"),
            push_app_key=os.getenv("PUSH_APP_KEY", "demo-app"),
            push_app_secret=os.getenv("PUSH_APP_SECRET", "demo-secret"),
            push_interval=float(os.getenv("PUSH_INTERVAL", "2")),
            push_track_interval=float(os.getenv("PUSH_TRACK_INTERVAL", "5")),
            push_batch=int(os.getenv("PUSH_BATCH", "20")),
            push_timeout=float(os.getenv("PUSH_TIMEOUT", "5")),
            outbox_path=os.getenv("OUTBOX_DB", "push_outbox.db"),
            dedup_gate_k=float(os.getenv("DEDUP_GATE_K", "3.44")),
            dedup_default_sigma=float(os.getenv("DEDUP_DEFAULT_SIGMA", "20")),
            dedup_sigma_floor=float(os.getenv("DEDUP_SIGMA_FLOOR", "8")),
            dedup_source_sigmas=_json_env("DEDUP_SOURCE_SIGMAS"),
            dedup_autocalib=os.getenv("DEDUP_AUTOCALIB", "true").lower() in ("1", "true", "yes"),
            dedup_calib_samples=int(os.getenv("DEDUP_CALIB_SAMPLES", "200")),
        )
