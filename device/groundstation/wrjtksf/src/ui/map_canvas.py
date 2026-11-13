from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QToolTip, QWidget

from src.domain.models import Drone, DroneStatus, NoFlyZone, Obstacle, RectangleZone, Slot, Vec2
from src.services.geo_math import world_meters_to_wgs84


class MapCanvas(QWidget):
    scale_changed = Signal(float)
    """世界坐标 m；仅在停机坪 pad_zone 内点击时发出。"""
    slot_placement_chosen = Signal(float, float)

    def __init__(
        self,
        waiting_zone: RectangleZone,
        pad_zone: RectangleZone,
        slots: List[Slot],
        obstacles: List[Obstacle],
        no_fly_zones: List[NoFlyZone],
        surveillance_radius: float,
        safe_altitude_max: float,
        background_image: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.waiting_zone = waiting_zone
        self.pad_zone = pad_zone
        self.slots = slots
        self.obstacles = obstacles
        self.no_fly_zones = no_fly_zones
        self.surveillance_radius = surveillance_radius
        self.safe_altitude_max = safe_altitude_max
        self.drones: List[Drone] = []
        self.scale = 2.0
        self.min_scale = 0.6
        self.max_scale = 6.0
        self.pan_offset = QPointF(0.0, 0.0)
        self._is_panning = False
        self._last_mouse_pos = QPoint()
        self.background = QPixmap()
        if background_image:
            img_path = Path(background_image)
            if img_path.exists():
                self.background = QPixmap(str(img_path))
        self.layer_visible: Dict[str, bool] = {
            "base": True,
            "slots": True,
            "obstacles": True,
            "no_fly": True,
            "routes": True,
        }
        self.show_altitude_labels = True
        self._last_hover_key = ""
        self._default_scale = self.scale
        self._default_pan_offset = QPointF(self.pan_offset)
        self.show_zoom_hud = True
        # 与地图 (0,0) 对齐的地面站 WGS84，用于标注与无人机经纬度推算
        self.ref_lat: float = 29.52
        self.ref_lon: float = 106.56
        # Enable true hover tracking (mouse move without button pressed),
        # otherwise tooltip updates/hide may not run reliably.
        self.setMouseTracking(True)
        self.setMinimumSize(900, 700)
        self.slot_placement_mode = False

    def set_geo_reference(self, lat: float, lon: float) -> None:
        self.ref_lat = float(lat)
        self.ref_lon = float(lon)
        self.update()

    def reset_view(self) -> None:
        self.scale = self._default_scale
        self.pan_offset = QPointF(self._default_pan_offset)
        self.scale_changed.emit(self.scale)
        self.update()

    def center_on_origin(self) -> None:
        self.pan_offset = QPointF(0.0, 0.0)
        self.update()

    def _content_bounds(self) -> tuple[float, float, float, float]:
        xs: list[float] = [self.waiting_zone.x_min, self.waiting_zone.x_max, self.pad_zone.x_min, self.pad_zone.x_max]
        ys: list[float] = [self.waiting_zone.y_min, self.waiting_zone.y_max, self.pad_zone.y_min, self.pad_zone.y_max]
        for s in self.slots:
            rm = float(getattr(s, "footprint_radius_m", 14.0))
            xs.extend([s.center.x - rm, s.center.x + rm])
            ys.extend([s.center.y - rm, s.center.y + rm])
        for o in self.obstacles:
            xs.extend([o.center.x - o.radius, o.center.x + o.radius])
            ys.extend([o.center.y - o.radius, o.center.y + o.radius])
        for z in self.no_fly_zones:
            xs.extend([z.zone.x_min, z.zone.x_max])
            ys.extend([z.zone.y_min, z.zone.y_max])
        min_x = min(xs) if xs else -100.0
        max_x = max(xs) if xs else 100.0
        min_y = min(ys) if ys else -100.0
        max_y = max(ys) if ys else 100.0
        # Pad bounds a bit
        pad = 40.0
        return min_x - pad, min_y - pad, max_x + pad, max_y + pad

    def fit_to_content(self) -> None:
        min_x, min_y, max_x, max_y = self._content_bounds()
        if self.width() <= 0 or self.height() <= 0:
            return
        w = max(1e-6, max_x - min_x)
        h = max(1e-6, max_y - min_y)
        margin_px = 40.0
        sx = (self.width() - margin_px * 2) / w
        sy = (self.height() - margin_px * 2) / h
        target_scale = max(self.min_scale, min(self.max_scale, min(sx, sy)))
        # Center bounds to view center
        cx_world = (min_x + max_x) / 2
        cy_world = (min_y + max_y) / 2
        self.scale = target_scale
        self.pan_offset = QPointF(-cx_world * self.scale, cy_world * self.scale)
        self.scale_changed.emit(self.scale)
        self.update()

    def _clamp_pan(self) -> None:
        # Keep the content roughly within view so user won't lose it.
        min_x, min_y, max_x, max_y = self._content_bounds()
        rect = QRectF(self._to_view(min_x, max_y), self._to_view(max_x, min_y)).normalized()
        margin = 80.0
        dx = 0.0
        dy = 0.0
        if rect.right() < margin:
            dx = margin - rect.right()
        elif rect.left() > self.width() - margin:
            dx = (self.width() - margin) - rect.left()
        if rect.bottom() < margin:
            dy = margin - rect.bottom()
        elif rect.top() > self.height() - margin:
            dy = (self.height() - margin) - rect.top()
        if dx or dy:
            self.pan_offset += QPointF(dx, dy)

    def set_scale(self, new_scale: float, anchor_view_pos: QPointF | None = None) -> None:
        new_scale = max(self.min_scale, min(self.max_scale, float(new_scale)))
        if abs(new_scale - self.scale) < 1e-9:
            return

        if anchor_view_pos is None:
            anchor_view_pos = QPointF(self.width() / 2, self.height() / 2)

        cx = self.width() / 2
        cy = self.height() / 2
        wx = (anchor_view_pos.x() - cx - self.pan_offset.x()) / self.scale
        wy = -(anchor_view_pos.y() - cy - self.pan_offset.y()) / self.scale

        self.scale = new_scale
        self.pan_offset = QPointF(
            anchor_view_pos.x() - cx - wx * self.scale,
            anchor_view_pos.y() - cy + wy * self.scale,
        )
        self._clamp_pan()
        self.scale_changed.emit(self.scale)
        self.update()

    def update_state(self, drones: List[Drone]) -> None:
        self.drones = drones
        self.update()

    def set_layer_visible(self, key: str, visible: bool) -> None:
        self.layer_visible[key] = visible
        # If the hovered item layer is turned off, hide tooltip immediately.
        if not visible and self._last_hover_key:
            if (key == "obstacles" and self._last_hover_key.startswith("obs:")) or (
                key == "no_fly" and self._last_hover_key.startswith("nfz:")
            ):
                self._last_hover_key = ""
                QToolTip.hideText()
        self.update()

    def set_show_altitude_labels(self, visible: bool) -> None:
        self.show_altitude_labels = visible
        self.update()

    def set_slot_placement_mode(self, enabled: bool) -> None:
        self.slot_placement_mode = bool(enabled)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.update()

    def _to_view(self, x: float, y: float) -> QPointF:
        cx = self.width() / 2
        cy = self.height() / 2
        return QPointF(cx + x * self.scale + self.pan_offset.x(), cy - y * self.scale + self.pan_offset.y())

    def _to_world(self, view_x: float, view_y: float) -> Vec2:
        cx = self.width() / 2
        cy = self.height() / 2
        wx = (view_x - cx - self.pan_offset.x()) / self.scale
        wy = -(view_y - cy - self.pan_offset.y()) / self.scale
        return Vec2(wx, wy)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            return
        zoom_factor = 1.12 if delta > 0 else 1 / 1.12
        cursor_pos = event.position()
        self.set_scale(self.scale * zoom_factor, cursor_pos)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.slot_placement_mode:
            pos = event.position()
            w = self._to_world(pos.x(), pos.y())
            if self.pad_zone.contains(w):
                self.slot_placement_chosen.emit(w.x, w.y)
            else:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    "机位只能添加在机场绿色停机坪（Airport Boundary）区域内。",
                    self,
                )
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._is_panning = True
            self._last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            if self._last_hover_key:
                self._last_hover_key = ""
                QToolTip.hideText()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.slot_placement_mode:
            self._update_hover_tooltip(event)
            return
        if self._is_panning:
            current = event.position().toPoint()
            delta = current - self._last_mouse_pos
            self.pan_offset += QPointF(float(delta.x()), float(delta.y()))
            self._last_mouse_pos = current
            self._clamp_pan()
            self.update()
        else:
            self._update_hover_tooltip(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._last_hover_key = ""
        QToolTip.hideText()
        super().leaveEvent(event)

    def _update_hover_tooltip(self, event) -> None:
        world = self._to_world(event.position().x(), event.position().y())
        for obs in self.obstacles:
            if world.distance_to(obs.center) <= obs.radius:
                key = f"obs:{obs.name}"
                if self._last_hover_key != key:
                    text = (
                        f"障碍物: {obs.name}\n"
                        f"中心: ({obs.center.x:.1f}, {obs.center.y:.1f})\n"
                        f"半径: {obs.radius:.1f}m\n"
                        f"高度: {obs.height:.1f}m"
                    )
                    QToolTip.showText(event.globalPosition().toPoint(), text, self)
                    self._last_hover_key = key
                return
        for nfz in self.no_fly_zones:
            if nfz.zone.contains(world):
                key = f"nfz:{nfz.name}"
                if self._last_hover_key != key:
                    corners = [
                        (nfz.zone.x_min, nfz.zone.y_min),
                        (nfz.zone.x_min, nfz.zone.y_max),
                        (nfz.zone.x_max, nfz.zone.y_max),
                        (nfz.zone.x_max, nfz.zone.y_min),
                    ]
                    boundary_text = " -> ".join(f"({x:.1f},{y:.1f})" for x, y in corners)
                    text = (
                        f"禁飞区: {nfz.name}\n"
                        f"范围边界: {boundary_text}\n"
                        f"高度限制: <= {nfz.max_allowed_altitude:.1f}m"
                    )
                    QToolTip.showText(event.globalPosition().toPoint(), text, self)
                    self._last_hover_key = key
                return
        if self._last_hover_key:
            self._last_hover_key = ""
            QToolTip.hideText()

    def _zone_rect(self, zone: RectangleZone) -> QRectF:
        top_left = self._to_view(zone.x_min, zone.y_max)
        bottom_right = self._to_view(zone.x_max, zone.y_min)
        return QRectF(top_left, bottom_right).normalized()

    def _draw_grid(self, p: QPainter) -> None:
        p.setPen(QPen(QColor(71, 85, 105, 220), 1))
        step = 50
        for x in range(0, self.width(), step):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            p.drawLine(0, y, self.width(), y)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.font())
        cx = float(self.width()) * 0.5
        cy = float(self.height()) * 0.5
        rad = max(float(self.width()), float(self.height())) * 0.72
        vignette = QRadialGradient(cx, cy, rad)
        vignette.setColorAt(0.0, QColor(252, 253, 255))
        vignette.setColorAt(0.42, QColor(236, 242, 252))
        vignette.setColorAt(0.78, QColor(200, 212, 232))
        vignette.setColorAt(1.0, QColor(148, 163, 184))
        p.fillRect(self.rect(), vignette)
        if self.layer_visible.get("base", True):
            if not self.background.isNull():
                bg = self.background.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                p.setOpacity(0.28)
                p.drawPixmap(0, 0, bg)
                p.setOpacity(1.0)
            self._draw_grid(p)
            center = self._to_view(0, 0)
            radius = self.surveillance_radius * self.scale
            p.setPen(QPen(QColor(59, 130, 246, 180), 2))
            p.setBrush(QColor(37, 99, 235, 65))
            p.drawEllipse(center, radius, radius)
            p.setPen(QPen(QColor(37, 99, 235), 1))
            p.drawText(center + QPointF(-60, -radius + 20), "Ground Control Surveillance Range")
            p.setPen(QPen(QColor(51, 65, 85), 1))
            p.drawText(
                center + QPointF(-120, -radius + 36),
                f"地面站 WGS84  {self.ref_lat:.6f}°, {self.ref_lon:.6f}°",
            )
            if self.show_altitude_labels:
                p.setPen(QPen(QColor(51, 65, 85), 1))
                p.drawText(center + QPointF(-80, -radius + 54), f"Safe Alt <= {self.safe_altitude_max:.0f}m")

            p.setPen(QPen(QColor(100, 149, 237), 2, Qt.DashLine))
            p.setBrush(QColor(100, 149, 237, 80))
            p.drawRect(self._zone_rect(self.waiting_zone))
            p.setPen(QPen(QColor(30, 64, 175), 1))
            p.drawText(self._to_view(self.waiting_zone.x_min + 8, self.waiting_zone.y_max - 8), "Waiting Zone")
            p.setPen(QPen(QColor(34, 197, 94), 2))
            p.setBrush(QColor(34, 197, 94, 80))
            p.drawRect(self._zone_rect(self.pad_zone))
            p.setPen(QPen(QColor(21, 128, 61), 1))
            p.drawText(self._to_view(self.pad_zone.x_min + 8, self.pad_zone.y_max - 10), "Airport Boundary")
            if self.show_altitude_labels:
                p.drawText(self._to_view(self.pad_zone.x_min + 8, self.pad_zone.y_max - 24), "Dock Alt = 0m")

        if self.layer_visible.get("slots", True):
            for slot in self.slots:
                rm = float(getattr(slot, "footprint_radius_m", 14.0))
                max_sz = float(getattr(slot, "max_drone_size_m", 5.0))
                pkw = float(getattr(slot, "station_charge_kw", 10.0))
                p.setPen(QPen(QColor(16, 185, 129), 2))
                p.setBrush(QColor(16, 185, 129, 45))
                center = self._to_view(slot.center.x, slot.center.y)
                rx = rm * self.scale
                p.drawEllipse(center, rx, rx)
                slot_rect = QRectF(center.x() - rx, center.y() - rx, 2 * rx, 2 * rx)
                p.setPen(QPen(QColor(21, 128, 61), 1))
                slot_text = f"{slot.slot_id} z=0m" if self.show_altitude_labels else slot.slot_id
                p.drawText(slot_rect.topLeft() + QPointF(2, -4), slot_text)
                name = slot.display_name
                if len(name) > 12:
                    name = name[:11] + "…"
                occ = slot.occupied_by or "空闲"
                p.drawText(slot_rect.bottomLeft() + QPointF(2, -rx + 14), name)
                p.drawText(slot_rect.bottomLeft() + QPointF(2, -rx + 28), f"≤{max_sz:.1f}m · {pkw:.0f}kW · {occ}")
                p.setPen(QPen(QColor(16, 185, 129), 2))

        if self.layer_visible.get("obstacles", True):
            for obs in self.obstacles:
                p.setPen(QPen(QColor(249, 115, 22), 2))
                p.setBrush(QColor(249, 115, 22, 80))
                center = self._to_view(obs.center.x, obs.center.y)
                r = obs.radius * self.scale
                p.drawEllipse(center, r, r)
                p.setPen(QPen(QColor(154, 52, 18), 1))
                text = f"{obs.name} Obstacle H:{obs.height:.0f}m" if self.show_altitude_labels else obs.name
                p.drawText(center + QPointF(8, -8), text)

        if self.layer_visible.get("no_fly", True):
            for nfz in self.no_fly_zones:
                p.setPen(QPen(QColor(239, 68, 68), 2))
                p.setBrush(QColor(239, 68, 68, 65))
                p.drawRect(self._zone_rect(nfz.zone))
                p.setPen(QPen(QColor(127, 29, 29), 1))
                nfz_text = (
                    f"{nfz.name} No-Fly (Alt <= {nfz.max_allowed_altitude:.0f}m)"
                    if self.show_altitude_labels
                    else f"{nfz.name} No-Fly"
                )
                p.drawText(self._to_view(nfz.zone.x_min + 5, nfz.zone.y_max - 5), nfz_text)

        for drone in self.drones:
            if drone.planned_route and self.layer_visible.get("routes", True):
                total_segments = max(1, len(drone.planned_route.waypoints) - 1)
                for i in range(total_segments):
                    a = drone.planned_route.waypoints[i].position
                    b = drone.planned_route.waypoints[i + 1].position
                    # Passed segments fade, upcoming segments remain brighter.
                    if i < max(0, drone.route_progress_idx - 1):
                        seg_alpha_scale = 0.25
                    elif i == max(0, drone.route_progress_idx - 1):
                        seg_alpha_scale = 0.5
                    else:
                        seg_alpha_scale = 1.0
                    route_color = QColor(251, 146, 60)
                    alpha = int(255 * drone.planned_route_opacity * seg_alpha_scale)
                    route_color.setAlpha(max(10, min(255, alpha)))
                    p.setPen(QPen(route_color, 2, Qt.DashLine))
                    p.drawLine(self._to_view(a.x, a.y), self._to_view(b.x, b.y))

            if drone.completed_inbound_route and drone.completed_inbound_route_opacity > 0 and self.layer_visible.get("routes", True):
                completed_color = QColor(245, 158, 11)
                completed_color.setAlpha(max(10, min(255, int(255 * drone.completed_inbound_route_opacity))))
                p.setPen(QPen(completed_color, 2, Qt.DashLine))
                for i in range(len(drone.completed_inbound_route.waypoints) - 1):
                    a = drone.completed_inbound_route.waypoints[i].position
                    b = drone.completed_inbound_route.waypoints[i + 1].position
                    p.drawLine(self._to_view(a.x, a.y), self._to_view(b.x, b.y))

            if len(drone.history) > 1 and self.layer_visible.get("routes", True):
                for i in range(len(drone.history) - 1):
                    age_ratio = (i + 1) / len(drone.history)
                    alpha = max(10, int(age_ratio * 170))
                    trail_color = QColor(71, 85, 105, alpha)
                    p.setPen(QPen(trail_color, 1))
                    a = drone.history[i].position
                    b = drone.history[i + 1].position
                    p.drawLine(self._to_view(a.x, a.y), self._to_view(b.x, b.y))

            color = QColor(220, 38, 38) if drone.status == DroneStatus.DOCKED else QColor(56, 189, 248)
            p.setPen(QPen(color, 2))
            p.setBrush(color)
            pos = self._to_view(drone.position.x, drone.position.y)
            p.drawEllipse(pos, 6, 6)

            # Draw local XYZ axes around drone icon for orientation + altitude cue.
            p.setPen(QPen(QColor(239, 68, 68), 2))
            p.drawLine(pos, pos + QPointF(12, 0))  # X axis
            p.drawText(pos + QPointF(14, 2), "X")
            p.setPen(QPen(QColor(34, 197, 94), 2))
            p.drawLine(pos, pos + QPointF(0, -12))  # Y axis
            p.drawText(pos + QPointF(2, -14), "Y")
            p.setPen(QPen(QColor(37, 99, 235), 2))
            p.drawLine(pos, pos + QPointF(-8, -8))  # Z axis projection
            p.drawText(pos + QPointF(-18, -10), "Z")

            p.setPen(QPen(QColor(51, 65, 85), 1))
            w_lat, w_lon = world_meters_to_wgs84(self.ref_lat, self.ref_lon, drone.position.x, drone.position.y)
            if self.show_altitude_labels:
                drone_text = (
                    f"{drone.drone_id}  φ={w_lat:.6f}° λ={w_lon:.6f}°  "
                    f"本地 x={drone.position.x:.1f} y={drone.position.y:.1f} z={drone.altitude:.1f}m"
                )
            else:
                drone_text = f"{drone.drone_id}  φ={w_lat:.6f}° λ={w_lon:.6f}°"
            p.drawText(pos + QPointF(8, -8), drone_text)

        if self.show_altitude_labels:
            self._draw_altitude_legend(p)
        if self.show_zoom_hud:
            self._draw_zoom_hud(p)

    def _draw_altitude_legend(self, p: QPainter) -> None:
        panel = QRectF(12, 12, 320, 132)
        p.setPen(QPen(QColor(127, 145, 175), 1))
        lg = QLinearGradient(panel.topLeft(), panel.bottomRight())
        lg.setColorAt(0.0, QColor(255, 251, 245, 250))
        lg.setColorAt(0.55, QColor(240, 248, 255, 248))
        lg.setColorAt(1.0, QColor(230, 238, 252, 246))
        p.setBrush(lg)
        p.drawRoundedRect(panel, 6, 6)
        p.setPen(QPen(QColor(15, 23, 42), 1))
        p.drawText(panel.left() + 10, panel.top() + 20, "Altitude Info")
        p.drawText(panel.left() + 10, panel.top() + 40, f"- Global Safe Alt: <= {self.safe_altitude_max:.0f}m")
        y = panel.top() + 58
        for obs in self.obstacles[:2]:
            p.drawText(panel.left() + 10, y, f"- {obs.name}: obstacle H={obs.height:.0f}m")
            y += 16
        for nfz in self.no_fly_zones[:2]:
            p.drawText(panel.left() + 10, y, f"- {nfz.name}: no-fly Alt<={nfz.max_allowed_altitude:.0f}m")
            y += 16

    def _draw_zoom_hud(self, p: QPainter) -> None:
        # Bottom-right zoom + scale bar.
        level = 1 + int(((self.scale - self.min_scale) / (self.max_scale - self.min_scale)) * 19)
        level = max(1, min(20, level))
        text = f"Zoom: Z{level}  {self.scale:.2f}x"

        fm = QFontMetrics(p.font())
        padding = 10
        text_w = fm.horizontalAdvance(text)
        text_h = fm.height()

        bar_px = 90
        meters = bar_px / max(1e-6, self.scale)
        # Round to nice values
        nice = [5, 10, 20, 50, 100, 200, 500]
        m_label = min(nice, key=lambda v: abs(v - meters))
        bar_px_nice = int(m_label * self.scale)
        bar_px_nice = max(50, min(140, bar_px_nice))

        panel_w = max(text_w, bar_px_nice) + padding * 2
        panel_h = text_h + 28 + padding
        x = self.width() - panel_w - 12
        y = self.height() - panel_h - 12

        p.setPen(QPen(QColor(127, 145, 175), 1))
        hud = QRectF(x, y, panel_w, panel_h)
        lg2 = QLinearGradient(hud.topLeft(), hud.bottomRight())
        lg2.setColorAt(0.0, QColor(248, 250, 255, 252))
        lg2.setColorAt(1.0, QColor(214, 226, 245, 250))
        p.setBrush(lg2)
        p.drawRoundedRect(hud, 8, 8)
        p.setPen(QPen(QColor(15, 23, 42), 1))
        p.drawText(int(x + padding), int(y + padding + text_h), text)

        # Scale bar
        bar_y = y + padding + text_h + 14
        bar_x = x + padding
        p.setPen(QPen(QColor(71, 85, 105), 2))
        p.drawLine(int(bar_x), int(bar_y), int(bar_x + bar_px_nice), int(bar_y))
        p.drawLine(int(bar_x), int(bar_y - 5), int(bar_x), int(bar_y + 5))
        p.drawLine(int(bar_x + bar_px_nice), int(bar_y - 5), int(bar_x + bar_px_nice), int(bar_y + 5))
        p.setPen(QPen(QColor(71, 85, 105), 1))
        p.drawText(int(bar_x), int(bar_y + 18), f"{m_label}m")
