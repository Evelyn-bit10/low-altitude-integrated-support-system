"""MAVLink 遥测线程（PySide6），逻辑参考独立工程。"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

try:
    from pymavlink import mavutil
except Exception:  # noqa: BLE001
    mavutil = None  # type: ignore


class DroneTelemetryWorker(QThread):
    telemetryUpdated = Signal(dict)
    statusUpdated = Signal(str)
    connectionChanged = Signal(str, bool)

    def __init__(
        self,
        drone_id: str,
        drone_name: str,
        connection_uri: str,
        baudrate: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.drone_id = str(drone_id)
        self.drone_name = drone_name
        self.connection_uri = connection_uri
        self.baudrate = baudrate
        self._running = True
        self._should_connect = False
        self._is_connected = False
        self._master: Optional[object] = None
        self._lat: Optional[float] = None
        self._lng: Optional[float] = None
        self._alt_m: Optional[float] = None
        self._battery_remaining: Optional[float] = None
        self._satellites_visible: Optional[int] = None
        self._charge_watts_est: Optional[float] = None
        self.backoff = 1.0
        self.backoff_max = 15.0
        self.link_timeout = 15.0
        self.emit_interval = 0.1

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect_drone(self) -> None:
        self._should_connect = True
        self.statusUpdated.emit(f"[{self.drone_name}] 已请求连接…")

    def disconnect_drone(self) -> None:
        self._should_connect = False
        self._close_connection()
        self.statusUpdated.emit(f"[{self.drone_name}] 已请求断开")

    def stop(self) -> None:
        self._running = False
        self._should_connect = False

    def _close_connection(self) -> None:
        try:
            if self._master:
                self._master.close()
        except Exception:
            pass
        finally:
            self._master = None
            self._is_connected = False
            self.connectionChanged.emit(self.drone_id, False)

    def _connect_to_drone(self) -> bool:
        if mavutil is None:
            self.statusUpdated.emit(f"[{self.drone_name}] 未安装 pymavlink，无法连接")
            return False
        self.statusUpdated.emit(f"[{self.drone_name}] 正在连接 {self.connection_uri} @ {self.baudrate}…")
        try:
            self._master = mavutil.mavlink_connection(self.connection_uri, baud=self.baudrate)
        except Exception as e:
            self.statusUpdated.emit(f"[{self.drone_name}] 连接失败: {e}")
            return False
        try:
            self._master.wait_heartbeat(timeout=10)
            self._is_connected = True
            self.connectionChanged.emit(self.drone_id, True)
            self.statusUpdated.emit(f"[{self.drone_name}] 已收到心跳")
            try:
                self._master.mav.request_data_stream_send(
                    self._master.target_system,
                    self._master.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_POSITION,
                    4,
                    1,
                )
            except Exception:
                pass
            return True
        except Exception as e:
            self.statusUpdated.emit(f"[{self.drone_name}] 无心跳: {e}")
            self._close_connection()
            return False

    def _process_message(self, msg) -> None:
        msg_type = msg.get_type()
        if msg_type == "GPS_RAW_INT":
            self._satellites_visible = getattr(msg, "satellites_visible", None)
        elif msg_type == "SYS_STATUS":
            self._battery_remaining = getattr(msg, "battery_remaining", None)
        elif msg_type == "BATTERY_STATUS":
            br = getattr(msg, "battery_remaining", None)
            if br is not None and br >= 0:
                self._battery_remaining = float(br)
            v0 = None
            try:
                vlist = getattr(msg, "voltages", None)
                if vlist and len(vlist) > 0 and vlist[0] != 65535:
                    v0 = float(vlist[0]) / 1000.0
            except Exception:
                v0 = None
            cur_cA = getattr(msg, "current_battery", -1)
            if v0 and cur_cA is not None and int(cur_cA) != -1:
                amps = float(cur_cA) / 100.0
                self._charge_watts_est = max(0.0, v0 * amps)
            else:
                self._charge_watts_est = None
        elif msg_type == "ALTITUDE":
            self._alt_m = getattr(msg, "altitude_relative", None)
        elif msg_type == "GLOBAL_POSITION_INT":
            if getattr(msg, "lat", 0) not in (0, None) and getattr(msg, "lon", 0) not in (0, None):
                self._lat = msg.lat / 1e7
                self._lng = msg.lon / 1e7
            if hasattr(msg, "relative_alt") and msg.relative_alt is not None:
                self._alt_m = msg.relative_alt / 1000.0

    def _emit_telemetry(self) -> None:
        self.telemetryUpdated.emit(
            {
                "id": self.drone_id,
                "name": self.drone_name,
                "lat": self._lat,
                "lng": self._lng,
                "alt": self._alt_m,
                "battery": self._battery_remaining,
                "charge_w": self._charge_watts_est,
                "sats": self._satellites_visible,
                "ts": time.time(),
                "connected": self._is_connected,
            }
        )

    def run(self) -> None:  # noqa: N802
        if mavutil is None:
            self.statusUpdated.emit("pymavlink 未安装，遥测线程空闲")
            return
        while self._running:
            if not self._should_connect:
                time.sleep(0.2)
                continue
            if not self._connect_to_drone():
                if not self._running or not self._should_connect:
                    continue
                time.sleep(self.backoff)
                self.backoff = min(self.backoff * 1.6, self.backoff_max)
                continue
            self.backoff = 1.0
            last_emit = 0.0
            last_msg_time = time.time()
            while self._running and self._should_connect:
                try:
                    msg = self._master.recv_match(blocking=True, timeout=1)
                    now = time.time()
                    if msg is None:
                        if now - last_msg_time >= self.link_timeout:
                            raise TimeoutError("link timeout")
                        continue
                    last_msg_time = now
                    self._process_message(msg)
                    if now - last_emit >= self.emit_interval:
                        self._emit_telemetry()
                        last_emit = now
                except Exception as e:
                    if not self._running or not self._should_connect:
                        break
                    self.statusUpdated.emit(f"[{self.drone_name}] 链路异常，重连: {e}")
                    self._close_connection()
                    break
        self._close_connection()
        self.statusUpdated.emit(f"[{self.drone_name}] 遥测线程结束")
