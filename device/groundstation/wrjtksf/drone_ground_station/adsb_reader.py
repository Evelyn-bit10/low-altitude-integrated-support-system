import serial
import threading
import time
import sys
import queue
import re
from datetime import datetime

# rs1090 安全导入
try:
    import rs1090
    _RS1090_AVAILABLE = True
except (ImportError, OSError, Exception) as e:
    print(f"[ADSB] rs1090 导入失败: {e}")
    _RS1090_AVAILABLE = False
    rs1090 = None

# --- Configuration ---
SERIAL_PORT = 'COM11'
BAUD_RATE = 921600


class ADSBSerialReader:
    """从串口读取ADS-B原始消息，使用独立线程。"""

    def __init__(self, port, baudrate, message_callback=None):
        self.port = port
        self.baudrate = baudrate
        self.message_callback = message_callback
        self.serial_connection = None
        self.reading = False
        self.reader_thread = None
        self.processing_thread = None
        self._line_queue = queue.Queue(maxsize=5000)  # 最多积压 5000 行

    def connect(self):
        if not self.port or not self.port.strip():
            print("Serial port not specified.")
            return False
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.5,
                rtscts=False,
                dsrdtr=False,
            )
            self.serial_connection.reset_input_buffer()
            time.sleep(0.3)
            print(f"Successfully connected to {self.port} at {self.baudrate} baud.")
            return True
        except serial.SerialException as e:
            print(f"Error opening serial port {self.port}: {e}")
            return False

    def disconnect(self):
        self.reading = False
        # 先关串口让 readline() 返回，再等线程退出
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            print("Serial connection closed.")
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
        # 放哨兵通知处理线程退出
        self._line_queue.put(None)
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=2)

    def start_reading(self):
        if self.serial_connection and self.serial_connection.is_open:
            self.reading = True
            # 先启动处理线程（消费者），再启动 I/O 线程（生产者）
            self.processing_thread = threading.Thread(target=self._process_loop, daemon=True)
            self.processing_thread.start()
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            print("Started reading ADS-B data (dual-thread: I/O + processing)...")
        else:
            print("Cannot start reading: serial port is not open.")

    def _read_loop(self):
        """I/O 线程：只负责 readline() + 入队，不做任何解析。
        921600 baud ≈ 3200 行/秒，解析（正则 + rs1090 + 锁）放在独立线程，
        避免 I/O 线程被阻塞导致串口内核缓冲区溢出。"""
        line_count = 0
        data_count = 0
        last_heartbeat = time.time()
        last_data_time = time.time()
        data_timeout = 15
        nodata_streak = 0
        MAX_NODATA_STREAK = 50

        while self.reading:
            try:
                raw_line = self.serial_connection.readline()
            except TypeError:
                break
            except serial.SerialException as e:
                err = str(e)
                if "returned no data" in err or "readiness" in err:
                    nodata_streak += 1
                    if nodata_streak <= 3 or nodata_streak % 10 == 0:
                        print(f"[ADSB-驱动] 内核误报 (第{nodata_streak}次)，忽略继续")
                    if nodata_streak >= MAX_NODATA_STREAK:
                        print(f"[ADSB-串口] 连续 {MAX_NODATA_STREAK} 次内核误报，停止重连")
                        self.reading = False
                        break
                    time.sleep(0.05)
                    continue
                else:
                    print(f"[ADSB-串口] SerialException: {e}")
                    time.sleep(0.05)
                    continue
            except (OSError, IOError) as e:
                print(f"[ADSB-串口] IO异常: {e}")
                time.sleep(0.05)
                continue

            nodata_streak = 0
            line_count += 1

            if raw_line:
                try:
                    line = raw_line.decode("ascii", errors="ignore").strip()
                except Exception:
                    continue
                if line:
                    data_count += 1
                    last_data_time = time.time()
                    # 非阻塞入队；队列满则丢弃最老的行
                    try:
                        self._line_queue.put_nowait(line)
                    except queue.Full:
                        try:
                            self._line_queue.get_nowait()
                            self._line_queue.put_nowait(line)
                        except queue.Empty:
                            pass

            if time.time() - last_data_time > data_timeout:
                print(f"[ADSB-串口] {data_timeout}s 无有效数据，停止等待重连")
                self.reading = False
                break

            now = time.time()
            if now - last_heartbeat >= 5:
                idle = int(now - last_data_time)
                qs = self._line_queue.qsize()
                print(f"[ADSB-心跳] 存活 | 5s内 {line_count}行 {data_count}非空 | 空闲{idle}s | 队列{qs}")
                line_count = 0
                data_count = 0
                last_heartbeat = now

    def _process_loop(self):
        """处理线程：从队列取行，执行 _process_line + message_callback。"""
        while True:
            try:
                line = self._line_queue.get(timeout=0.5)
            except queue.Empty:
                # 队列空 + I/O 线程已停止 → 退出
                if not self.reading:
                    return
                continue

            if line is None:
                return  # 哨兵：disconnect() 发出的退出信号

            try:
                self._process_line(line)
            except BaseException as e:
                print(f"Error processing line: {e}")

    def _process_line(self, line):
        raw = (line or "").strip().replace(" ", "")
        if not raw:
            return
        m = re.search(r"([0-9A-Fa-f]{28})", raw)
        if not m:
            return
        msg = m.group(1).upper()
        if len(msg) != 28 or not re.fullmatch(r"[0-9A-Fa-f]+", msg):
            return
        first_byte = int(msg[0:2], 16)
        df = (first_byte >> 3) & 0x1F
        if df not in (17, 18):
            return
        icao = msg[2:8].upper()
        if self.message_callback:
            self.message_callback(msg, icao)


# ============ 全局数据 ============

aircraft_data = {}
position_message_history = {}
aircraft_data_lock = threading.RLock()

# 诊断计数器
_diag_decoded_ok = 0
_diag_decoded_fail = 0
_diag_last_diag_time = time.time()


def clear_adsb_cache():
    with aircraft_data_lock:
        aircraft_data.clear()
        position_message_history.clear()


def get_aircraft_snapshot(max_age=30):
    """UI 线程调用：返回存活目标的快照，丢弃过期条目。"""
    now = time.time()
    with aircraft_data_lock:
        expired = [
            icao for icao, d in aircraft_data.items()
            if 'last_seen' in d and now - d['last_seen'] > max_age
        ]
        for icao in expired:
            age = now - aircraft_data[icao].get('last_seen', now)
            print(f"[ADSB-过期] 丢弃 {icao} (最后出现 {age:.0f}s 前)")
            del aircraft_data[icao]
            position_message_history.pop(icao, None)
        return {icao: d.copy() for icao, d in aircraft_data.items()}


def _store_position_frame(icao, raw_message, timestamp, parity):
    """缓存最近 CPR 位置帧（调用方已持锁）。"""
    history = position_message_history.setdefault(icao, [])
    history.append({
        "frame": raw_message,
        "timestamp": timestamp,
        "parity": parity,
    })
    cutoff = timestamp - 15
    history[:] = [item for item in history if item["timestamp"] >= cutoff]
    if len(history) > 6:
        del history[:-6]


def _decode_position_from_history(icao, reference=None):
    """rs1090 批量 CPR 解码（调用方已持锁）。"""
    if not _RS1090_AVAILABLE:
        return None, None
    history = position_message_history.get(icao, [])
    if not history:
        return None, None
    frames = [item["frame"] for item in history]
    timestamps = [item["timestamp"] for item in history]
    try:
        decoded_messages = rs1090.decode(frames, timestamps, reference=reference)
    except Exception:
        return None, None
    for decoded in reversed(decoded_messages):
        if not isinstance(decoded, dict):
            continue
        lat = decoded.get("latitude")
        lon = decoded.get("longitude")
        if lat is not None and lon is not None:
            return lat, lon
    return None, None


def decode_and_update(raw_message, icao):
    """rs1090 解码 ADS-B 报文并更新 aircraft_data。"""
    global _diag_decoded_ok, _diag_decoded_fail, _diag_last_diag_time
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

        if not _RS1090_AVAILABLE:
            return
        try:
            decoded = rs1090.decode(raw_message.upper())
        except Exception:
            return
        if decoded is None:
            return

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

        is_position_message = (
            (df == 17 and tc is not None and 5 <= tc <= 18) or
            bds in ("05", "06")
        )

        with aircraft_data_lock:
            if icao not in aircraft_data:
                aircraft_data[icao] = {}

            aircraft_data[icao]['df'] = df
            if tc is not None:
                aircraft_data[icao]['tc'] = tc

            if is_position_message:
                reference = None
                if "lat" in aircraft_data[icao] and "lon" in aircraft_data[icao]:
                    reference = (aircraft_data[icao]["lat"], aircraft_data[icao]["lon"])
                _store_position_frame(
                    icao, raw_message, now,
                    decoded.get("parity") if isinstance(decoded, dict) else None,
                )
                hist_lat, hist_lon = _decode_position_from_history(icao, reference=reference)
                if hist_lat is not None and hist_lon is not None:
                    lat = hist_lat
                    lon = hist_lon

            if df == 17 and tc is not None:
                if 1 <= tc <= 4:
                    if callsign:
                        aircraft_data[icao]['callsign'] = callsign.strip()
                elif 5 <= tc <= 18:
                    if lat is not None and lon is not None:
                        aircraft_data[icao]['lat'] = lat
                        aircraft_data[icao]['lon'] = lon
                elif tc == 19:
                    if speed is not None:
                        aircraft_data[icao]['speed'] = speed
                    if track is not None:
                        aircraft_data[icao]['track'] = track
            else:
                if callsign:
                    aircraft_data[icao]['callsign'] = callsign.strip()
                if lat is not None and lon is not None:
                    aircraft_data[icao]['lat'] = lat
                    aircraft_data[icao]['lon'] = lon
                if speed is not None:
                    aircraft_data[icao]['speed'] = speed
                if track is not None:
                    aircraft_data[icao]['track'] = track

            aircraft_data[icao]['last_seen'] = now
            _diag_decoded_ok += 1

        # 每 10 秒输出统计
        if now - _diag_last_diag_time >= 10:
            print(f"[ADSB-解码] 10秒内 decoded_ok={_diag_decoded_ok} "
                  f"decoded_fail={_diag_decoded_fail} active={len(aircraft_data)}")
            _diag_decoded_ok = 0
            _diag_decoded_fail = 0
            _diag_last_diag_time = now

    except Exception as e:
        _diag_decoded_fail += 1
        print(f"Error decoding message {raw_message}: {e}")


# ============ GUI (独立运行时) ============

from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget, QLabel, QComboBox, QPushButton
from PyQt5.QtCore import QTimer


class ADSBMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADS-B 地面站监视器")
        self.setGeometry(100, 100, 600, 400)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.status_label = QLabel("状态: 未连接")
        layout.addWidget(self.status_label)

        self.display = QTextEdit()
        self.display.setReadOnly(True)
        layout.addWidget(self.display)

        control_layout = QVBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.addItems(['COM1', 'COM2', 'COM4'])
        control_layout.addWidget(self.port_combo)

        self.connect_button = QPushButton("连接并启动")
        self.connect_button.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.connect_button)

        layout.addLayout(control_layout)

        self.reader = None
        self.is_connected = False

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.start(1000)

    def toggle_connection(self):
        if not self.is_connected:
            port = self.port_combo.currentText()
            self.reader = ADSBSerialReader(port, BAUD_RATE, decode_and_update)
            if self.reader.connect():
                self.reader.start_reading()
                self.is_connected = True
                self.connect_button.setText("断开连接")
                self.status_label.setText(f"状态: 已连接到 {port}")
                clear_adsb_cache()
            else:
                self.status_label.setText(f"状态: 连接失败，请检查端口 {port}")
        else:
            if self.reader:
                self.reader.disconnect()
            self.is_connected = False
            clear_adsb_cache()
            self.connect_button.setText("连接并启动")
            self.status_label.setText("状态: 未连接")

    def update_display(self):
        if not self.is_connected:
            return
        display_text = f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        display_text += f"{'ICAO':<8} {'呼号':<8} {'纬度':<12} {'经度':<12} {'速度(kt)':<10} {'航向':<6}\n"
        display_text += "-" * 60 + "\n"

        current_time = time.time()
        with aircraft_data_lock:
            expired = [icao for icao, d in aircraft_data.items()
                       if 'last_seen' in d and current_time - d['last_seen'] > 30]
            for icao in expired:
                del aircraft_data[icao]
                position_message_history.pop(icao, None)

            for icao, d in aircraft_data.items():
                callsign = d.get('callsign', 'N/A')
                lat = f"{d.get('lat', 'N/A'):.4f}" if 'lat' in d else 'N/A'
                lon = f"{d.get('lon', 'N/A'):.4f}" if 'lon' in d else 'N/A'
                speed = f"{d.get('speed', 'N/A'):.0f}" if 'speed' in d else 'N/A'
                track = f"{d.get('track', 'N/A'):.0f}" if 'track' in d else 'N/A'
                display_text += f"{icao:<8} {callsign:<8} {lat:<12} {lon:<12} {speed:<10} {track:<6}\n"

        self.display.setPlainText(display_text)


def main():
    app = QApplication(sys.argv)
    window = ADSBMonitor()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
