#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  RID900 无人机探测模块 — 核心解析引擎
=============================================================================
  功能:
    1. 解析 $HBRID 心跳报文  — 设备自身状态（ID / RSSI / SNR / GPS位置）
    2. 解析 $GBRID 探测报文  — 无人机 RID 信息（身份 / 位置 / 速度 / 姿态 / 飞手）
    3. 校验 NMEA checksum
    4. 多目标并发追踪（≥100 架）
    5. 线程安全的串口数据流读取

  协议说明:
    模块串口参数: 115200, 8N1, 无流控
    报文格式兼容 NMEA-0183 标准, 以 $ 开头, * 结尾带校验和

  依赖:  pyserial  (pip install pyserial)

  用法:
    from rid_module import RIDParser, RIDSerialReader
=============================================================================
"""

import os
import sys
import time
import threading
import queue
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict


# =============================================================================
#  数据模型
# =============================================================================

@dataclass
class HeartbeatInfo:
    """RID900 模块自身心跳信息 ($HBRID)"""
    device_id: str = "--"           # 设备号
    rssi: int = 0                   # 信号强度 (dBm)
    snr: int = 0                    # 信噪比 (dB)
    longitude: float = 0.0          # 设备经度
    latitude: float = 0.0           # 设备纬度
    altitude: float = 0.0           # 设备海拔高度 (m)
    status: int = 0                 # 状态码
    raw: str = ""                   # 原始报文
    timestamp: float = 0.0          # 接收时间戳

    def is_valid(self) -> bool:
        return self.device_id != "--"


@dataclass
class DroneInfo:
    """单架无人机的完整 RID 信息 ($GBRID)"""
    # ── 信号质量 ──
    detect_rssi: int = 0            # 信号强度 (dBm)
    detect_snr: int = 0             # 信噪比 (dB)

    # ── 身份信息 ──
    drone_serial_num: str = "--"    # 无人机序列号 (唯一标识)
    vendor_str: str = "--"          # 生产厂商
    product_type_str: str = "--"    # 无人机型号

    # ── 设备属性 ──
    drone_type: int = 0             # 设备类型
    drone_class: int = 0            # 设备种类
    state_info: int = 0             # 状态信息

    # ── 无人机位置 ──
    drone_longitude: float = 0.0    # 无人机经度 (°)
    drone_latitude: float = 0.0     # 无人机纬度 (°)
    height: float = 0.0             # 离地高度 (m)
    altitude: float = 0.0           # 海拔高度 (m)
    pressure: float = 0.0           # 气压高度 (m)

    # ── 飞行参数 ──
    yaw_angle: int = 0              # 航向角 (°, 0-359)
    east_speed: int = 0             # 水平速度 (m/s)
    up_speed: int = 0               # 垂直速度 (m/s)

    # ── 精度信息 ──
    position_error: int = 0         # 位置误差 (m)
    height_error: int = 0           # 高度误差 (m)

    # ── 飞手 (操控员) 位置 ──
    pilot_longitude: float = 0.0    # 飞手经度
    pilot_latitude: float = 0.0     # 飞手纬度
    pilot_height: float = 0.0       # 飞手海拔高度 (m)

    # ── 元数据 ──
    raw: str = ""                   # 原始报文
    timestamp: float = 0.0          # 接收时间戳
    update_count: int = 0           # 累计更新次数

    @property
    def is_valid(self) -> bool:
        """序列号有效即为合法目标"""
        return self.drone_serial_num != "--"

    @property
    def heading_str(self) -> str:
        """航向角 → 中文方位描述"""
        if not self.is_valid:
            return "--"
        a = self.yaw_angle % 360
        if a < 22.5 or a >= 337.5:
            return "北 ↑"
        elif a < 67.5:
            return "东北 ↗"
        elif a < 112.5:
            return "东 →"
        elif a < 157.5:
            return "东南 ↘"
        elif a < 202.5:
            return "南 ↓"
        elif a < 247.5:
            return "西南 ↙"
        elif a < 292.5:
            return "西 ←"
        else:
            return "西北 ↖"

    @property
    def speed_kmh(self) -> float:
        """水平速度 km/h"""
        return round(self.east_speed * 3.6, 1)

    @property
    def has_pilot_position(self) -> bool:
        """飞手位置是否有效"""
        return not (self.pilot_longitude == 0.0 and self.pilot_latitude == 0.0)


# =============================================================================
#  NMEA 解析工具
# =============================================================================

def _nmea_checksum_ok(sentence: str) -> bool:
    """
    校验 NMEA 语句的 XOR checksum。
    格式: $<data>*<hex_checksum>
    """
    try:
        body, cs_hex = sentence[1:].rsplit("*", 1)
    except ValueError:
        return False  # 无校验和, 仍接受

    expected = 0
    for ch in body:
        expected ^= ord(ch)

    try:
        actual = int(cs_hex.strip(), 16)
    except ValueError:
        return False

    return expected == actual


def _strip_checksum(sentence: str) -> str:
    """去除 NMEA 校验和部分, 返回纯数据 ($ 前缀保留)"""
    idx = sentence.rfind("*")
    if idx > 0:
        return sentence[:idx]
    return sentence


# =============================================================================
#  报文解析器
# =============================================================================

class RIDParser:
    """
    RID900 报文解析器。
    支持 $HBRID (心跳) 和 $GBRID (无人机探测) 两种报文。
    """

    @staticmethod
    def parse_line(raw_line: str) -> Tuple[Optional[str], object]:
        """
        解析单行 NMEA 报文。

        Args:
            raw_line: 原始报文行 (如 "$GBRID,-38,43,...")

        Returns:
            (报文类型, 解析结果) — 类型: "HBRID" | "GBRID" | None
        """
        line = raw_line.strip()
        if not line or not line.startswith("$"):
            return None, None

        # 校验
        if "*" in line and not _nmea_checksum_ok(line):
            pass  # 校验失败时仍尝试解析

        body = _strip_checksum(line)
        parts = body.split(",")
        if len(parts) < 2:
            return None, None

        header = parts[0]

        if header == "$HBRID":
            return "HBRID", RIDParser._parse_hbrid(parts, line)
        elif header == "$GBRID":
            return "GBRID", RIDParser._parse_gbrid(parts, line)

        return None, None

    @staticmethod
    def _parse_hbrid(parts: List[str], raw: str) -> HeartbeatInfo:
        """解析 $HBRID 心跳报文"""
        hb = HeartbeatInfo(raw=raw, timestamp=time.time())
        try:
            # $HBRID,heartbeat,<device_id>,<rssi>,<snr>,<lon>,<lat>,<alt>,<status>*cs
            if len(parts) >= 8:
                hb.device_id  = parts[2].strip()
                hb.rssi       = int(float(parts[3])) if parts[3] else 0
                hb.snr        = int(float(parts[4])) if parts[4] else 0
                hb.longitude  = float(parts[5]) if parts[5] else 0.0
                hb.latitude   = float(parts[6]) if parts[6] else 0.0
                hb.altitude   = float(parts[7]) if parts[7] else 0.0
            if len(parts) >= 9:
                hb.status     = int(float(parts[8])) if parts[8] else 0
        except (ValueError, IndexError):
            pass
        return hb

    @staticmethod
    def _parse_gbrid(parts: List[str], raw: str) -> DroneInfo:
        """解析 $GBRID 无人机探测报文"""
        d = DroneInfo(raw=raw, timestamp=time.time())
        try:
            n = len(parts)

            if n > 1:
                d.detect_rssi = int(float(parts[1])) if parts[1] else 0
            if n > 2:
                d.detect_snr = int(float(parts[2])) if parts[2] else 0
            if n > 3:
                d.drone_serial_num = parts[3].strip()
            if n > 4:
                d.vendor_str = parts[4].strip()
            if n > 5:
                d.product_type_str = parts[5].strip()
            if n > 6:
                d.drone_type = int(float(parts[6])) if parts[6] else 0
            if n > 7:
                d.drone_class = int(float(parts[7])) if parts[7] else 0
            if n > 8:
                d.state_info = int(float(parts[8])) if parts[8] else 0
            if n > 9:
                d.drone_longitude = float(parts[9]) if parts[9] else 0.0
            if n > 10:
                d.drone_latitude = float(parts[10]) if parts[10] else 0.0
            if n > 11:
                d.height = float(parts[11]) if parts[11] else 0.0
            if n > 12:
                d.altitude = float(parts[12]) if parts[12] else 0.0
            if n > 13:
                d.pressure = float(parts[13]) if parts[13] else 0.0
            if n > 14:
                d.yaw_angle = int(float(parts[14])) if parts[14] else 0
            if n > 15:
                d.east_speed = int(float(parts[15])) if parts[15] else 0
            if n > 16:
                d.up_speed = int(float(parts[16])) if parts[16] else 0
            if n > 17:
                d.position_error = int(float(parts[17])) if parts[17] else 0
            if n > 18:
                d.height_error = int(float(parts[18])) if parts[18] else 0
            if n > 19:
                d.pilot_longitude = float(parts[19]) if parts[19] else 0.0
            if n > 20:
                d.pilot_latitude = float(parts[20]) if parts[20] else 0.0
            if n > 21:
                d.pilot_height = float(parts[21]) if parts[21] else 0.0
        except (ValueError, IndexError) as e:
            pass

        return d


# =============================================================================
#  多目标追踪器
# =============================================================================

class DroneTracker:
    """
    多无人机目标追踪器。
    以序列号 (drone_serial_num) 为 key, 维护实时目标列表。
    支持超时自动淘汰 (默认 60 秒未更新则移除)。
    """

    def __init__(self, timeout: float = 60.0, max_drones: int = 200):
        self._drones: OrderedDict[str, DroneInfo] = OrderedDict()
        self._timeout = timeout
        self._max_drones = max_drones
        self._lock = threading.Lock()

    def update(self, drone: DroneInfo) -> bool:
        """
        更新或新增一架无人机。

        Returns:
            True 表示新目标, False 表示更新已有目标
        """
        if not drone.is_valid:
            return False

        with self._lock:
            key = drone.drone_serial_num
            is_new = key not in self._drones

            if is_new and len(self._drones) >= self._max_drones:
                # 淘汰最旧的目标
                self._drones.popitem(last=False)

            existing = self._drones.get(key)
            if existing:
                drone.update_count = existing.update_count + 1
            else:
                drone.update_count = 1

            self._drones[key] = drone
            # 移到末尾 (保持 LRU 顺序)
            self._drones.move_to_end(key)
            return is_new

    def get(self, serial: str) -> Optional[DroneInfo]:
        """按序列号获取目标"""
        with self._lock:
            return self._drones.get(serial)

    def get_all(self) -> List[DroneInfo]:
        """获取所有在线目标"""
        with self._lock:
            return list(self._drones.values())

    def get_sorted(self, key='rssi', reverse=True) -> List[DroneInfo]:
        """获取排序后的目标列表 (默认按信号强度降序)"""
        drones = self.get_all()
        if key == 'rssi':
            drones.sort(key=lambda d: d.detect_rssi, reverse=reverse)
        elif key == 'distance':
            # 简易排序 — 这里需要与模块距离计算配合
            drones.sort(key=lambda d: abs(d.height), reverse=reverse)
        elif key == 'time':
            drones.sort(key=lambda d: d.timestamp, reverse=reverse)
        elif key == 'speed':
            drones.sort(key=lambda d: d.east_speed, reverse=reverse)
        return drones

    def remove_stale(self) -> int:
        """移除超时目标, 返回移除数量"""
        now = time.time()
        removed = 0
        with self._lock:
            stale_keys = [
                k for k, v in self._drones.items()
                if now - v.timestamp > self._timeout
            ]
            for k in stale_keys:
                del self._drones[k]
                removed += 1
        return removed

    def clear(self):
        """清空所有目标"""
        with self._lock:
            self._drones.clear()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._drones)

    @property
    def total_updates(self) -> int:
        with self._lock:
            return sum(d.update_count for d in self._drones.values())


# =============================================================================
#  Linux USB CDC ACM 复位工具
# =============================================================================

def _find_usb_interface_name(port: str) -> Optional[str]:
    """
    通过 sysfs 查找串口对应的 USB 接口名称。
    例如 /dev/ttyACM0 → "1-1.4:1.0" (用于 unbind/bind)
    """
    dev_name = os.path.basename(port)
    sysfs_tty = f"/sys/class/tty/{dev_name}"
    if not os.path.exists(sysfs_tty):
        return None
    device_path = os.path.realpath(os.path.join(sysfs_tty, "device"))
    # 检查是否由 cdc_acm 驱动
    driver_link = os.path.join(device_path, "driver")
    if not os.path.exists(driver_link):
        return None
    try:
        driver_name = os.path.basename(os.readlink(driver_link))
    except OSError:
        return None
    if "cdc_acm" not in driver_name:
        return None
    return os.path.basename(device_path)


def _reset_usb_device(port: str) -> bool:
    """
    通过 sysfs unbind/bind 复位 USB CDC ACM 设备，模拟物理插拔效果。
    解决树莓派上冷启动后 /dev/ttyACM0 无数据的 Linux 内核问题。
    返回 True 表示成功, False 表示跳过 (非 Linux / 权限不足 / 非 USB 设备)。
    """
    if not sys.platform.startswith("linux"):
        return False

    iface = _find_usb_interface_name(port)
    if not iface:
        return False

    unbind = "/sys/bus/usb/drivers/cdc_acm/unbind"
    bind   = "/sys/bus/usb/drivers/cdc_acm/bind"

    if not os.path.exists(unbind) or not os.path.exists(bind):
        return False

    try:
        with open(unbind, "w") as f:
            f.write(iface)
        time.sleep(1.0)
        with open(bind, "w") as f:
            f.write(iface)
        time.sleep(1.5)  # 等待内核重新初始化 ttyACM 节点
        return True
    except (PermissionError, OSError):
        return False


# =============================================================================
#  串口数据流读取器 (后台线程)
# =============================================================================

class RIDSerialReader(threading.Thread):
    """
    后台串口读取线程:
      - 持续从串口读取 NMEA 报文
      - 自动解析 $HBRID / $GBRID
      - 通过 queue 将结果推送给主线程
    """

    def __init__(self, port: str, baudrate: int = 115200,
                 result_queue: queue.Queue = None):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.result_queue = result_queue or queue.Queue()
        self.running = True
        self.connected = False
        self._ser = None
        self._read_buffer = b""
        self._line_count = 0
        self._error_count = 0

    def run(self):
        import serial

        # ── Linux: 连接前先尝试 USB 复位 (解决冷启动 CDC ACM 无数据问题) ──
        _reset_usb_device(self.port)

        # ── 连接串口 ──
        try:
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.02,          # 短超时保证实时读取
                write_timeout=1.0,
                rtscts=False,          # 禁用硬件流控 (Linux 兼容性关键)
                dsrdtr=False,          # 禁用 DSR/DTR 流控
            )
            # 关键：在 Linux 下模拟 stty -hupcl 的效果，拉低 DTR 唤醒传感器
            self._ser.setDTR(False)
            time.sleep(0.5)   # 等待传感器稳定
            self.connected = True
            self.result_queue.put(("STATUS", "connected", self.port, self.baudrate))
        except Exception as e:
            self.result_queue.put(("STATUS", "error", str(e)))
            return

        # ── 数据看门狗 ──
        NO_DATA_TIMEOUT = 5.0           # 连接后无数据超时 (秒)
        MAX_USB_RETRIES = 3             # USB 复位最大重试次数
        _retry_count = 0
        _last_data_time = time.time()

        # ── 持续读取循环 ──
        while self.running and self._ser and self._ser.is_open:
            try:
                chunk = self._ser.read(1024)
                if chunk:
                    self._read_buffer += chunk
                    self._process_buffer()
                    _last_data_time = time.time()    # 收到数据, 重置看门狗
                    _retry_count = 0                 # 数据正常, 清零重试
                else:
                    # 未读到数据 — 检查是否一直没有收到过任何数据
                    if self._line_count == 0 and time.time() - _last_data_time > NO_DATA_TIMEOUT:
                        if _retry_count < MAX_USB_RETRIES:
                            _retry_count += 1
                            self.result_queue.put(("STATUS", "nodata",
                                f"连接 {NO_DATA_TIMEOUT}s 无数据, USB 复位 {_retry_count}/{MAX_USB_RETRIES}"))
                            # 关闭当前串口, 复位 USB, 重新打开
                            self._close_serial()
                            _reset_usb_device(self.port)
                            time.sleep(2.0)
                            try:
                                self._ser = serial.Serial(
                                    port=self.port,
                                    baudrate=self.baudrate,
                                    bytesize=serial.EIGHTBITS,
                                    parity=serial.PARITY_NONE,
                                    stopbits=serial.STOPBITS_ONE,
                                    timeout=0.02,
                                    write_timeout=1.0,
                                    rtscts=False,
                                    dsrdtr=False,
                                )
                                self._ser.setDTR(False)
                                time.sleep(0.5)
                                self.connected = True
                                _last_data_time = time.time()
                                self.result_queue.put(("STATUS", "reconnected", self.port, self.baudrate))
                            except Exception as e:
                                self.result_queue.put(("STATUS", "error", f"USB 复位后重连失败: {e}"))
                                self.connected = False
                                return
                        else:
                            self.result_queue.put(("STATUS", "nodata_max",
                                f"USB 复位 {MAX_USB_RETRIES} 次仍无数据, 请手动插拔 RID 设备后重试"))
                            self.connected = False
                            break
            except serial.SerialException as e:
                self.result_queue.put(("STATUS", "disconnected", str(e)))
                self.connected = False
                break
            except Exception as e:
                self._error_count += 1
                if self._error_count > 100:
                    self.result_queue.put(("STATUS", "error", f"连续读取错误: {e}"))
                    break

        self._close()

    def _process_buffer(self):
        """从缓冲区切割完整行并解析"""
        while True:
            idx = self._read_buffer.find(b"\n")
            if idx == -1:
                break

            line_bytes = self._read_buffer[:idx]
            self._read_buffer = self._read_buffer[idx + 1:]

            try:
                line = line_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                continue

            if not line:
                continue

            self._line_count += 1
            msg_type, data = RIDParser.parse_line(line)

            if msg_type == "HBRID":
                self.result_queue.put(("HBRID", data))
            elif msg_type == "GBRID":
                self.result_queue.put(("GBRID", data))
            # 忽略未知类型

    def _close_serial(self):
        """仅关闭串口句柄 (不改变 running 标志, 用于 USB 复位后重连场景)"""
        self.connected = False
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def _close(self):
        self.running = False
        self._close_serial()

    def stop(self):
        self.running = False
        self._close()

    @property
    def stats(self) -> Dict:
        return {
            "lines_read": self._line_count,
            "errors": self._error_count,
            "connected": self.connected,
        }
