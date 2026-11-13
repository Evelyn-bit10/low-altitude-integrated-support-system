"""ADS-B 风格雷达视图（从参考项目独立移植，PySide6）。"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RadarWidget(QWidget):
    """以经纬度为中心的平面极坐标雷达示意，目标为 WGS84 点集。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.base_radar_range = 50_000.0
        self.radar_range = self.base_radar_range
        self.radar_radius = 200
        self.center_lat = 29.52
        self.center_lon = 106.56
        self.targets: list[dict] = []

    def set_center(self, lat: float | None, lon: float | None) -> None:
        if lat is None or lon is None:
            return
        self.center_lat = float(lat)
        self.center_lon = float(lon)
        self.update()

    def set_targets(self, targets: list[dict]) -> None:
        self.targets = list(targets)
        self.update()

    def calculate_display_range(self) -> float:
        farthest = self.base_radar_range
        for target in self.targets:
            lat = target.get("lat")
            lon = target.get("lon")
            if lat is None or lon is None:
                continue
            d = self.haversine_distance(self.center_lat, self.center_lon, float(lat), float(lon))
            if d > farthest:
                farthest = d
        padded = farthest * 1.1
        step = 5000 if padded <= 50000 else 10000
        rounded = math.ceil(padded / step) * step
        return max(self.base_radar_range, rounded)

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r_m = 6_371_000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r_m * c

    @staticmethod
    def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        x = math.sin(dl) * math.cos(p2)
        y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
        return (math.degrees(math.atan2(x, y)) + 360) % 360

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center_x = self.width() // 2
        center_y = self.height() // 2
        self.radar_radius = max(80, min(center_x, center_y) - 24)
        self.radar_range = self.calculate_display_range()

        self._draw_background(painter, center_x, center_y)
        self._draw_targets(painter, center_x, center_y)

    def _draw_background(self, painter: QPainter, center_x: int, center_y: int) -> None:
        r = self.rect()
        grad = QLinearGradient(float(r.left()), float(r.top()), float(r.right()), float(r.bottom()))
        grad.setColorAt(0.0, QColor(30, 41, 59))
        grad.setColorAt(0.55, QColor(15, 23, 42))
        grad.setColorAt(1.0, QColor(2, 6, 23))
        painter.fillRect(r, grad)
        painter.save()
        painter.setPen(QPen(QColor(148, 163, 184), 1))
        for ratio in (0.25, 0.5, 0.75, 1.0):
            r = self.radar_radius * ratio
            painter.drawEllipse(QPointF(center_x, center_y), r, r)
        painter.drawLine(center_x - self.radar_radius, center_y, center_x + self.radar_radius, center_y)
        painter.drawLine(center_x, center_y - self.radar_radius, center_x, center_y + self.radar_radius)
        painter.setPen(QPen(QColor(203, 213, 225), 1))
        f = self.font()
        f.setPointSize(10)
        painter.setFont(f)
        painter.drawText(center_x + self.radar_radius - 14, center_y - 6, "E")
        painter.drawText(center_x - self.radar_radius + 6, center_y - 6, "W")
        painter.drawText(center_x - 5, center_y - self.radar_radius + 14, "N")
        painter.drawText(center_x - 5, center_y + self.radar_radius - 6, "S")
        painter.setBrush(QBrush(QColor(14, 165, 233)))
        painter.setPen(QPen(QColor(2, 132, 199), 1))
        painter.drawEllipse(QPointF(center_x, center_y), 5, 5)
        painter.restore()

    def _draw_targets(self, painter: QPainter, center_x: int, center_y: int) -> None:
        painter.save()
        painter.setBrush(QBrush(QColor(255, 96, 96)))
        painter.setPen(QPen(QColor(255, 160, 160), 1))
        f = self.font()
        f.setPointSize(9)
        painter.setFont(f)
        scale = self.radar_radius / self.radar_range
        for target in self.targets:
            lat = target.get("lat")
            lon = target.get("lon")
            name = str(target.get("name", "?"))
            if lat is None or lon is None:
                continue
            distance = self.haversine_distance(self.center_lat, self.center_lon, float(lat), float(lon))
            bearing = self.calculate_bearing(self.center_lat, self.center_lon, float(lat), float(lon))
            angle_rad = math.radians(90 - bearing)
            pr = distance * scale
            dx = pr * math.cos(angle_rad)
            dy = pr * math.sin(angle_rad)
            px = center_x + dx
            py = center_y - dy
            painter.drawEllipse(QPointF(px, py), 4, 4)
            painter.setPen(QPen(QColor(241, 245, 249), 1))
            painter.drawText(px + 6, py - 6, name[:12])
            painter.setPen(QPen(QColor(255, 160, 160), 1))
        painter.restore()
