"""
ADS-B 串口读取与目标缓存（从参考工程思路独立实现）。
依赖：pyserial。解码在 ARM 上使用纯 Python，x86 上可选 rs1090。
"""
from __future__ import annotations

import re
import math
import threading
import time
import platform
from typing import Any, Callable, Dict, Optional

# ---- ARM 检测：rs1090 (Rust/PyO3) 在 ARM 上会段错误导致闪退 ----
_IS_ARM = platform.machine().startswith(('arm', 'aarch'))
_IS_X86 = platform.machine().lower() in ('x86_64', 'amd64', 'i386', 'i686', 'x86')

if _IS_ARM:
    print("[ADSB-serial] ARM 架构，rs1090 已强制禁用，使用纯 Python 解码")
    _SKIP_RS1090 = True
    rs1090 = None
else:
    _SKIP_RS1090 = False
    try:
        import rs1090  # type: ignore
    except Exception:  # noqa: BLE001
        rs1090 = None  # type: ignore
        _SKIP_RS1090 = True

try:
    import serial
except ImportError:
    serial = None  # type: ignore

aircraft_data: Dict[str, Dict[str, Any]] = {}
position_message_history: Dict[str, list] = {}
aircraft_data_lock = threading.Lock()


def clear_adsb_cache() -> None:
    with aircraft_data_lock:
        aircraft_data.clear()
        position_message_history.clear()


def get_aircraft_snapshot(max_age: float = 45.0) -> Dict[str, Dict[str, Any]]:
    now = time.time()
    with aircraft_data_lock:
        expired = [icao for icao, data in aircraft_data.items() if now - data.get("last_seen", 0) > max_age]
        for icao in expired:
            aircraft_data.pop(icao, None)
            position_message_history.pop(icao, None)
        return {icao: data.copy() for icao, data in aircraft_data.items()}


def _parse_cpr_from_hex(msg_hex: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """从 28 位十六进制 ADS-B 报文中提取 CPR 原始字段。"""
    try:
        msg_int = int(msg_hex, 16)
    except (ValueError, TypeError):
        return None, None, None
    oe_flag = (msg_int >> 58) & 1
    cpr_lat = (msg_int >> 41) & 0x1FFFF
    cpr_lon = (msg_int >> 24) & 0x1FFFF
    return oe_flag, cpr_lat, cpr_lon


def _cpr_nl(lat: float) -> int:
    """计算给定纬度下的经度分区数 NL（空中位置，NZ=15）。"""
    lat = abs(lat)
    if lat >= 87.0:
        return 1
    if lat < 1e-9:
        return 59
    nz = 15.0
    cos_lat = math.cos(math.radians(lat))
    inner = 1.0 - (1.0 - math.cos(math.pi / (2.0 * nz))) / (cos_lat * cos_lat)
    if inner >= 1.0:
        return 1
    if inner <= -1.0:
        return 59
    return int(math.floor((2.0 * math.pi) / math.acos(inner) + 1e-9))


def _cpr_decode_position(even_frame: Dict[str, Any], odd_frame: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """从一对奇偶 CPR 帧解码全局经纬度（纯 Python 实现）。"""
    NZ = 15.0
    NZ2 = 4.0 * NZ
    NZ2m1 = NZ2 - 1.0
    dlat_even = 360.0 / NZ2
    dlat_odd = 360.0 / NZ2m1
    lat_even = even_frame["cpr_lat"] / 131072.0
    lat_odd = odd_frame["cpr_lat"] / 131072.0
    lon_even = even_frame["cpr_lon"] / 131072.0
    lon_odd = odd_frame["cpr_lon"] / 131072.0
    j = int(math.floor(NZ2m1 * lat_even - NZ2 * lat_odd + 0.5))
    lat_even_d = dlat_even * ((j % 60) + lat_even)
    lat_odd_d = dlat_odd * ((j % 59) + lat_odd)
    lat = lat_even_d
    if lat >= 270.0:
        lat -= 360.0
    if lat > 90.0 or lat < -90.0:
        return None, None
    ni = max(_cpr_nl(lat), 1)
    m = int(math.floor(lon_even * (_cpr_nl(lat_even_d) - 1) - lon_odd * _cpr_nl(lat_even_d) + 0.5))
    dlon_even = 360.0 / max(ni, 1)
    lon = dlon_even * ((m % max(ni, 1)) + lon_even)
    if lon >= 180.0:
        lon -= 360.0
    return lat, lon


def _store_position_frame(icao: str, raw_message: str, timestamp: float, parity: Any) -> None:
    history = position_message_history.setdefault(icao, [])
    oe_flag, cpr_lat, cpr_lon = _parse_cpr_from_hex(raw_message)
    history.append({
        "frame": raw_message, "timestamp": timestamp, "parity": parity,
        "oe_flag": oe_flag, "cpr_lat": cpr_lat, "cpr_lon": cpr_lon,
    })
    cutoff = timestamp - 15
    history[:] = [item for item in history if item["timestamp"] >= cutoff]
    if len(history) > 6:
        del history[:-6]


def _decode_position_from_history(icao: str, reference: Optional[tuple] = None) -> tuple[Optional[float], Optional[float]]:
    """从 CPR 历史帧中恢复经纬度（纯 Python CPR 解码，不依赖 rs1090 批量 API）。"""
    history = position_message_history.get(icao, [])
    if len(history) < 2:
        return None, None
    even_frame = None
    odd_frame = None
    for item in reversed(history):
        oe = item.get("oe_flag")
        if oe is None:
            continue
        if oe == 0 and even_frame is None:
            even_frame = item
        elif oe == 1 and odd_frame is None:
            odd_frame = item
        if even_frame is not None and odd_frame is not None:
            break
    if even_frame is None or odd_frame is None:
        return None, None
    if abs(even_frame["timestamp"] - odd_frame["timestamp"]) > 10:
        return None, None
    if even_frame.get("cpr_lat") is None or odd_frame.get("cpr_lat") is None:
        return None, None
    try:
        lat, lon = _cpr_decode_position(even_frame, odd_frame)
        return float(lat) if lat is not None else None, float(lon) if lon is not None else None
    except Exception:
        return None, None



# ---- 纯 Python 解码器（ARM 安全，无原生依赖） ----

_CALLSIGN_CHARS = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####_###############0123456789######"


def _decode_callsign_py(msg_int: int) -> Optional[str]:
    me = (msg_int >> 24) & ((1 << 56) - 1)
    tc = me >> 51
    if tc < 1 or tc > 4:
        return None
    field = (me >> 3) & ((1 << 48) - 1)
    chars = []
    for i in range(8):
        code = (field >> (42 - i * 6)) & 0x3F
        if code < len(_CALLSIGN_CHARS):
            ch = _CALLSIGN_CHARS[code]
            if ch not in ('#', '_'):
                chars.append(ch)
    result = ''.join(chars).strip()
    return result if result else None


def _decode_velocity_py(msg_int: int) -> tuple[Optional[float], Optional[float]]:
    me = (msg_int >> 24) & ((1 << 56) - 1)
    if me >> 51 != 19:
        return None, None
    subtype = (me >> 48) & 7
    if subtype not in (1, 2):
        return None, None
    ew_raw = (me >> 31) & 0x7FF
    ew_sign = (me >> 30) & 1
    ns_raw = (me >> 19) & 0x7FF
    ns_sign = (me >> 18) & 1
    scale = 1.0 if subtype == 1 else 4.0
    ew = ew_raw * scale * (-1 if ew_sign else 1)
    ns = ns_raw * scale * (-1 if ns_sign else 1)
    speed = math.sqrt(ew * ew + ns * ns)
    if speed < 0.1:
        return None, None
    track = math.degrees(math.atan2(ew, ns)) % 360.0
    return speed, track


def _decode_with_pure_python(msg_hex: str) -> Optional[Dict[str, Any]]:
    try:
        msg_int = int(msg_hex, 16)
    except (ValueError, TypeError):
        return None
    df = (msg_int >> 107) & 0x1F
    if df not in (17, 18):
        return None
    me = (msg_int >> 24) & ((1 << 56) - 1)
    tc = me >> 51 if df == 17 else None
    result: Dict[str, Any] = {"df": df, "tc": tc}
    if df == 17 and tc is not None and 1 <= tc <= 4:
        cs = _decode_callsign_py(msg_int)
        if cs:
            result["callsign"] = cs
    if df == 17 and tc is not None and 5 <= tc <= 18:
        result["bds"] = f"{tc:02d}"
    if df == 17 and tc == 19:
        spd, trk = _decode_velocity_py(msg_int)
        if spd is not None:
            result["groundspeed"] = spd
            result["ground_speed"] = spd
        if trk is not None:
            result["track"] = trk
    return result


def decode_and_update(raw_message: str, icao: str) -> None:
    """解码 ADS-B 报文。ARM 用纯 Python，x86 用 rs1090（失败时回退纯 Python）。"""
    try:
        raw = (raw_message or "").strip().replace(" ", "")
        m = re.search(r"([0-9A-Fa-f]{28})", raw)
        if not m:
            return
        raw_message = m.group(1).upper()
        if len(raw_message) != 28 or not re.fullmatch(r"[0-9A-Fa-f]+", raw_message):
            return
        first_byte = int(raw_message[0:2], 16)
        df = (first_byte >> 3) & 0x1F
        if df not in (17, 18):
            return
        icao = raw_message[2:8].upper()
        tc = None
        if df == 17:
            me_hex = raw_message[8:22]
            me_first_byte = int(me_hex[:2], 16)
            tc = (me_first_byte >> 3) & 0x1F
        now = time.time()

        # 解码：ARM 纯 Python / x86 rs1090
        if _SKIP_RS1090 or rs1090 is None:
            decoded = _decode_with_pure_python(raw_message)
        else:
            try:
                decoded = rs1090.decode(raw_message.upper())
            except Exception:
                decoded = _decode_with_pure_python(raw_message)
        if decoded is None:
            return
        with aircraft_data_lock:
            if icao not in aircraft_data:
                aircraft_data[icao] = {}
            ad = aircraft_data[icao]
            ad["df"] = df
            if tc is not None:
                ad["tc"] = tc
            callsign = decoded.get("callsign") if isinstance(decoded, dict) else None
            lat = decoded.get("latitude") if isinstance(decoded, dict) else None
            lon = decoded.get("longitude") if isinstance(decoded, dict) else None
            speed = None
            if isinstance(decoded, dict):
                speed = decoded.get("groundspeed")
                if speed is None:
                    speed = decoded.get("ground_speed")
            track = decoded.get("track") if isinstance(decoded, dict) else None
            bds = decoded.get("bds") if isinstance(decoded, dict) else None
            is_position_message = (df == 17 and tc is not None and 5 <= tc <= 18) or bds in ("05", "06")
            if is_position_message:
                reference = None
                if "lat" in ad and "lon" in ad:
                    reference = (ad["lat"], ad["lon"])
                _store_position_frame(icao, raw_message, now, decoded.get("parity") if isinstance(decoded, dict) else None)
                hist_lat, hist_lon = _decode_position_from_history(icao, reference=reference)
                if hist_lat is not None and hist_lon is not None:
                    lat, lon = hist_lat, hist_lon
            if df == 17 and tc is not None:
                if 1 <= tc <= 4 and callsign:
                    ad["callsign"] = callsign.strip()
                elif 5 <= tc <= 18 and lat is not None and lon is not None:
                    ad["lat"] = lat
                    ad["lon"] = lon
                elif tc == 19:
                    if speed is not None:
                        ad["speed"] = speed
                    if track is not None:
                        ad["track"] = track
            else:
                if callsign:
                    ad["callsign"] = callsign.strip()
                if lat is not None and lon is not None:
                    ad["lat"] = lat
                    ad["lon"] = lon
                if speed is not None:
                    ad["speed"] = speed
                if track is not None:
                    ad["track"] = track
            ad["last_seen"] = now
    except Exception:
        return


class ADSBSerialReader:
    def __init__(self, port: str, baudrate: int, message_callback: Optional[Callable[[str, str], None]] = None) -> None:
        self.port = port
        self.baudrate = baudrate
        self.message_callback = message_callback
        self.serial_connection = None
        self.reading = False
        self.reader_thread: Optional[threading.Thread] = None

    def connect(self) -> bool:
        if serial is None:
            return False
        if not self.port or not self.port.strip():
            return False
        try:
            self.serial_connection = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=1, rtscts=False, dsrdtr=False)
            return bool(self.serial_connection.is_open)
        except Exception:
            self.serial_connection = None
            return False

    def disconnect(self) -> None:
        self.reading = False
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2.0)
        self.reader_thread = None
        if self.serial_connection and getattr(self.serial_connection, "is_open", False):
            try:
                self.serial_connection.close()
            except Exception:
                pass
        self.serial_connection = None

    def start_reading(self) -> None:
        if self.serial_connection and getattr(self.serial_connection, "is_open", False):
            self.reading = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()

    def _read_loop(self) -> None:
        while self.reading and self.serial_connection:
            try:
                line = self.serial_connection.readline().decode("ascii", errors="ignore").strip()
                if line and self.message_callback:
                    try:
                        self.message_callback(line, "")
                    except Exception:
                        pass
            except Exception:
                self.reading = False
