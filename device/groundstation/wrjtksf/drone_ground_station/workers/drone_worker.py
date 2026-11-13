# workers/drone_worker.py
"""无人机遥测工作线程"""
import time
from PyQt5.QtCore import QThread, pyqtSignal
from pymavlink import mavutil


class DroneTelemetryWorker(QThread):
    """无人机遥测数据获取线程"""
    
    telemetryUpdated = pyqtSignal(dict)
    statusUpdated = pyqtSignal(str)
    connectionChanged = pyqtSignal(str, bool)

    def __init__(self, drone_id: str, drone_name: str, drone_emoji: str, 
                 serial_port: str, baudrate: int, parent=None):
        super().__init__(parent)
        self.drone_id = str(drone_id)
        self.drone_name = drone_name
        self.drone_emoji = drone_emoji
        self.serial_port = serial_port
        self.baudrate = baudrate
        
        # 控制标志
        self._running = True
        self._should_connect = False
        self._is_connected = False
        
        # 数据变量
        self._master = None
        self._lat = None
        self._lng = None
        self._alt_m = None
        self._battery_remaining = None
        self._satellites_visible = None
        
        # 连接参数
        self.backoff = 1.0
        self.backoff_max = 15.0
        self.link_timeout = 15.0
        
        # --- 修改点 1：将 UI 发送频率从 0.01 降低到 0.1 (10Hz)，避免前端过载和放大抖动 ---
        self.emit_interval = 0.1  #

    @property
    def is_connected(self):
        """获取连接状态"""
        return self._is_connected

    def connect_drone(self):
        """请求连接无人机"""
        self._should_connect = True
        self.statusUpdated.emit(f"[{self.drone_name}] 已请求连接...")

    def disconnect_drone(self):
        """请求断开无人机"""
        self._should_connect = False
        self._close_connection()
        self.statusUpdated.emit(f"[{self.drone_name}] 已请求断开连接")

    def stop(self):
        """停止线程

        注意：这里只修改控制标志，不直接关闭串口连接，
        避免在 GUI 线程中与工作线程同时操作 `_master` 导致潜在崩溃。
        真实的 `_close_connection()` 将在工作线程 `run()` 结束前统一调用。
        """
        self._running = False
        self._should_connect = False

    def _close_connection(self):
        """关闭连接"""
        try:
            if self._master:
                self._master.close()
        except Exception:
            pass
        finally:
            self._master = None
            self._is_connected = False
            self.connectionChanged.emit(self.drone_id, False)

    def _connect_to_drone(self):
        """连接到飞控"""
        self.statusUpdated.emit(
            f"[{self.drone_name}] 正在连接飞控 {self.serial_port}，波特率 {self.baudrate}..."
        )
        
        try:
            self._master = mavutil.mavlink_connection(
                self.serial_port, baud=self.baudrate
            )
        except Exception as e:
            self.statusUpdated.emit(f"[{self.drone_name}] ❌ 串口连接失败: {e}")
            return False

        try:
            self._master.wait_heartbeat(timeout=10)
            self.statusUpdated.emit(
                f"[{self.drone_name}] ✅ 心跳包接收成功：sys={self._master.target_system}, "
                f"comp={self._master.target_component}"
            )
            self._is_connected = True
            self.connectionChanged.emit(self.drone_id, True)

            try:
                self._master.mav.request_data_stream_send(
                    self._master.target_system,
                    self._master.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_POSITION,
                    3,  # 配合前端，请求3Hz即可，50Hz容易造成串口拥堵
                    1
                )
                self.statusUpdated.emit(f"[{self.drone_name}] 📶 已向飞控请求 10Hz 轨迹刷新率")
            except Exception as req_e:
                self.statusUpdated.emit(f"[{self.drone_name}] ⚠️ 请求高频数据流异常: {req_e}")

            return True
        except Exception as e:
            self.statusUpdated.emit(f"[{self.drone_name}] ❌ 未收到心跳包: {e}")
            self._close_connection()
            return False

    def _process_message(self, msg):
        """处理MAVLink消息"""
        msg_type = msg.get_type()

        if msg_type == "GPS_RAW_INT":
            # --- 修改点 2：仅从 GPS_RAW_INT 提取卫星数量，严禁在此处更新经纬度 ---
            # 原始 GPS 数据未经过滤波，会导致轨迹剧烈跳动
            self._satellites_visible = getattr(msg, "satellites_visible", None)
            
        elif msg_type == "SYS_STATUS":
            self._battery_remaining = getattr(msg, "battery_remaining", None)
            
        elif msg_type == "ALTITUDE":
            self._alt_m = getattr(msg, "altitude_relative", None)
            
        elif msg_type == "GLOBAL_POSITION_INT":
            # --- 统一使用 GLOBAL_POSITION_INT 作为位置来源，这是飞控EKF平滑后的数据 ---
            if getattr(msg, "lat", 0) not in (0, None) and getattr(msg, "lon", 0) not in (0, None):
                self._lat = msg.lat / 1e7
                self._lng = msg.lon / 1e7
            if hasattr(msg, "relative_alt") and msg.relative_alt is not None:
                self._alt_m = msg.relative_alt / 1000.0

    def run(self):
        """线程主循环"""
        while self._running:
            if not self._should_connect:
                time.sleep(0.5)
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
                            self.statusUpdated.emit(
                                f"[{self.drone_name}] ⚠️ 串口长时间无数据，判定掉线，准备重连..."
                            )
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
                    self.statusUpdated.emit(
                        f"[{self.drone_name}] ⚠️ 串口读取异常，准备重连: {e}"
                    )
                    self._close_connection()
                    break

        self._close_connection()
        self.statusUpdated.emit(f"[{self.drone_name}] ℹ️ 串口线程已停止")

    def _emit_telemetry(self):
        """发送遥测数据"""
        payload = {
            "id": self.drone_id,
            "name": self.drone_name,
            "emoji": self.drone_emoji,
            "lat": self._lat,
            "lng": self._lng,
            "alt": self._alt_m,
            "battery": self._battery_remaining,
            "sats": self._satellites_visible,
            "ts": time.time(),
            "connected": self._is_connected
        }
        self.telemetryUpdated.emit(payload)
