import sys
import math
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt5.QtCore import QTimer, QPointF, Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont

from PyQt5.QtWidgets import QLabel, QTextEdit, QComboBox

from adsb_reader import (
    ADSBSerialReader,
    BAUD_RATE,
    SERIAL_PORT,
    clear_adsb_cache,
    decode_and_update,
    get_aircraft_snapshot,
)
from utils.location import get_location_sync


def _enumerate_serial_ports():
    """枚举本机可用串口。"""
    try:
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


DEFAULT_CENTER = (39.9042, 116.4074)
TARGET_MAX_AGE_SECONDS = 30


class RadarWidget(QWidget):
    """Real-time radar view backed by location and ADS-B targets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_radar_range = 50000.0
        self.radar_range = self.base_radar_range
        self.radar_radius = 200
        self.center_lat, self.center_lon = DEFAULT_CENTER
        self.targets = []

    def set_center(self, lat, lon):
        if lat is None or lon is None:
            return
        center_changed = self.center_lat != lat or self.center_lon != lon
        self.center_lat = lat
        self.center_lon = lon
        if center_changed:
            print(f"[Radar] Center updated: lat={lat:.6f}, lon={lon:.6f}")
        self.update()

    def set_targets(self, targets):
        self.targets = targets
        self.update()

    def calculate_display_range(self):
        farthest_distance = self.base_radar_range
        for target in self.targets:
            lat = target.get("lat")
            lon = target.get("lon")
            if lat is None or lon is None:
                continue
            distance = self.haversine_distance(
                self.center_lat,
                self.center_lon,
                lat,
                lon,
            )
            if distance > farthest_distance:
                farthest_distance = distance

        padded_distance = farthest_distance * 1.1
        step = 5000 if padded_distance <= 50000 else 10000
        rounded_distance = math.ceil(padded_distance / step) * step
        return max(self.base_radar_range, rounded_distance)

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        radius_m = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius_m * c

    def calculate_bearing(self, lat1, lon1, lat2, lon2):
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)

        x = math.sin(delta_lambda) * math.cos(phi2)
        y = (
            math.cos(phi1) * math.sin(phi2)
            - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
        )

        return (math.degrees(math.atan2(x, y)) + 360) % 360

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center_x = self.width() // 2
        center_y = self.height() // 2
        self.radar_radius = max(80, min(center_x, center_y) - 24)
        self.radar_range = self.calculate_display_range()

        self._draw_background(painter, center_x, center_y)
        self._draw_targets(painter, center_x, center_y)

    def _draw_background(self, painter, center_x, center_y):
        painter.fillRect(self.rect(), QColor(10, 18, 14))

        painter.save()
        painter.setPen(QPen(QColor(52, 140, 88), 1))
        for ratio in (0.25, 0.5, 0.75, 1.0):
            radius = self.radar_radius * ratio
            painter.drawEllipse(QPointF(center_x, center_y), radius, radius)

        painter.drawLine(center_x - self.radar_radius, center_y, center_x + self.radar_radius, center_y)
        painter.drawLine(center_x, center_y - self.radar_radius, center_x, center_y + self.radar_radius)

        painter.setPen(QPen(QColor(120, 220, 160), 1))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(center_x + self.radar_radius - 14, center_y - 6, "E")
        painter.drawText(center_x - self.radar_radius + 6, center_y - 6, "W")
        painter.drawText(center_x - 5, center_y - self.radar_radius + 14, "N")
        painter.drawText(center_x - 5, center_y + self.radar_radius - 6, "S")

        painter.setBrush(QBrush(QColor(90, 220, 255)))
        painter.setPen(QPen(QColor(90, 220, 255), 1))
        painter.drawEllipse(QPointF(center_x, center_y), 5, 5)
        painter.restore()

    def _draw_targets(self, painter, center_x, center_y):
        painter.save()
        painter.setBrush(QBrush(QColor(255, 96, 96)))
        painter.setPen(QPen(QColor(255, 160, 160), 1))
        painter.setFont(QFont("Arial", 9))

        scale = self.radar_radius / self.radar_range
        for target in self.targets:
            distance = self.haversine_distance(
                self.center_lat,
                self.center_lon,
                target["lat"],
                target["lon"],
            )

            bearing = self.calculate_bearing(
                self.center_lat,
                self.center_lon,
                target["lat"],
                target["lon"],
            )
            angle_rad = math.radians(90 - bearing)
            pixel_radius = distance * scale
            dx = pixel_radius * math.cos(angle_rad)
            dy = pixel_radius * math.sin(angle_rad)

            point_x = center_x + dx
            point_y = center_y - dy
            painter.drawEllipse(QPointF(point_x, point_y), 4, 4)
            painter.drawText(int(point_x + 6), int(point_y - 6), target["name"])

        painter.restore()



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADS-B Radar")
        self.setGeometry(60, 60, 1280, 920)
        self.setMinimumSize(1100, 820)

        self.reader = None
        self.is_adsb_connected = False
        self.last_center = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.status_label = QLabel("ADSB: disconnected")
        self.center_label = QLabel("Center: loading...")
        self.targets_label = QLabel("Targets: 0")

        layout.addWidget(self.status_label)
        layout.addWidget(self.center_label)
        layout.addWidget(self.targets_label)

        # 串口选择行：下拉框 + 刷新 + 连接按钮
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(160)
        self._refresh_ports()
        port_row.addWidget(QLabel("串口:"))
        port_row.addWidget(self.port_combo)
        btn_refresh = QPushButton("刷新串口")
        btn_refresh.clicked.connect(self._refresh_ports)
        port_row.addWidget(btn_refresh)
        self.connect_button = QPushButton("连接 ADS-B")
        self.connect_button.clicked.connect(self.toggle_adsb_connection)
        port_row.addWidget(self.connect_button)
        port_row.addStretch(1)
        layout.addLayout(port_row)

        self.radar_widget = RadarWidget()
        self.radar_widget.setMinimumHeight(620)
        layout.addWidget(self.radar_widget, 5)

        self.data_view = QTextEdit()
        self.data_view.setReadOnly(True)
        self.data_view.setMinimumHeight(220)
        self.data_view.setFont(QFont("Consolas", 10))
        layout.addWidget(self.data_view, 2)

        self.location_timer = QTimer(self)
        self.location_timer.timeout.connect(self.refresh_center_location)
        self.location_timer.start(1000)

        self.targets_timer = QTimer(self)
        self.targets_timer.timeout.connect(self.refresh_targets)
        self.targets_timer.start(1000)

        self.refresh_center_location()

    def _refresh_ports(self) -> None:
        """刷新串口下拉列表。"""
        current = self.port_combo.currentText().strip()
        self.port_combo.clear()
        self.port_combo.addItem("无")
        ports = _enumerate_serial_ports()
        for p in ports:
            if self.port_combo.findText(p) == -1:
                self.port_combo.addItem(p)
        if not ports:
            self.port_combo.addItem("（未检测到串口）")
        if current:
            idx = self.port_combo.findText(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def _get_selected_port(self) -> str:
        """获取当前选择的串口，'无'或提示文本返回空字符串。"""
        t = self.port_combo.currentText().strip()
        if t == "无" or t.startswith("（"):
            return ""
        return t

    def toggle_adsb_connection(self):
        if self.is_adsb_connected:
            if self.reader:
                self.reader.disconnect()
            self.reader = None
            self.is_adsb_connected = False
            clear_adsb_cache()
            self.radar_widget.set_targets([])
            self.targets_label.setText("Targets: 0")
            self.data_view.clear()
            self.status_label.setText("ADSB: disconnected")
            self.connect_button.setText("连接 ADS-B")
            return

        port = self._get_selected_port()
        if not port:
            self.status_label.setText("ADSB: 请先选择串口")
            return
        self.reader = ADSBSerialReader(port, BAUD_RATE, decode_and_update)
        if not self.reader.connect():
            self.reader = None
            self.status_label.setText(f"ADSB: 连接失败 {port}")
            return

        clear_adsb_cache()
        self.reader.start_reading()
        self.is_adsb_connected = True
        self.status_label.setText(f"ADSB: 已连接 {port}")
        self.connect_button.setText("断开 ADS-B")

    def refresh_center_location(self):
        lat, lon = get_location_sync()
        if lat is None or lon is None:
            self.center_label.setText(
                f"Center: fallback {self.radar_widget.center_lat:.6f}, {self.radar_widget.center_lon:.6f}"
            )
            return

        center = (round(lat, 6), round(lon, 6))
        if self.last_center != center:
            self.last_center = center
            self.radar_widget.set_center(lat, lon)
        self.center_label.setText(f"Center: {lat:.6f}, {lon:.6f}")

    def refresh_targets(self):
        snapshot = get_aircraft_snapshot(max_age=TARGET_MAX_AGE_SECONDS)
        targets = []
        lines = [
            f"{'ICAO':<8} {'CALLSIGN':<10} {'LAT':<12} {'LON':<12} {'SPEED':<8} {'TRACK':<8}"
        ]
        for icao, data in snapshot.items():
            lat = data.get("lat")
            lon = data.get("lon")
            if lat is None or lon is None:
                continue

            label = data.get("callsign") or icao
            targets.append({"lat": lat, "lon": lon, "name": label})

            speed = data.get("speed")
            track = data.get("track")
            speed_text = f"{speed:.0f}" if isinstance(speed, (int, float)) else "N/A"
            track_text = f"{track:.0f}" if isinstance(track, (int, float)) else "N/A"
            callsign_text = (data.get("callsign") or "N/A")[:10]
            lines.append(
                f"{icao:<8} {callsign_text:<10} {lat:<12.6f} {lon:<12.6f} {speed_text:<8} {track_text:<8}"
            )

        self.radar_widget.set_targets(targets)
        self.targets_label.setText(
            f"Targets: {len(targets)} | Range: {self.radar_widget.calculate_display_range() / 1000:.1f} km"
        )
        self.data_view.setPlainText("\n".join(lines))

    def closeEvent(self, event):
        if self.reader:
            self.reader.disconnect()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
