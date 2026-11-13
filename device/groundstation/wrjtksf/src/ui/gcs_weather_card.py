"""天气信息卡片（样式由主窗口 QSS 的 gcsWeather* 规则控制）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout


class GcsWeatherCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("gcsWeatherCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        self.title_label = QLabel("天气信息")
        self.title_label.setObjectName("gcsWeatherTitle")
        title_row.addWidget(self.title_label)
        self.update_time_label = QLabel("")
        self.update_time_label.setObjectName("gcsWeatherHint")
        title_row.addStretch(1)
        title_row.addWidget(self.update_time_label)
        root.addLayout(title_row)

        cond_row = QHBoxLayout()
        self.condition_label = QLabel("--")
        self.condition_label.setObjectName("gcsWeatherCondition")
        self.condition_label.setWordWrap(True)
        self.condition_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        cond_row.addWidget(self.condition_label)
        self.temp_label = QLabel("--°C")
        self.temp_label.setObjectName("gcsWeatherTemp")
        self.temp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cond_row.addWidget(self.temp_label)
        root.addLayout(cond_row)

        # 位置信息容器
        location_container = QFrame()
        location_container.setObjectName("gcsWeatherLocationBox")
        location_container.setFrameShape(QFrame.StyledPanel)
        location_layout = QHBoxLayout(location_container)
        location_layout.setContentsMargins(8, 4, 8, 4)

        self.location_label = QLabel("位置: --")
        self.location_label.setObjectName("gcsWeatherSub")
        self.location_label.setWordWrap(True)
        location_layout.addWidget(self.location_label)
        root.addWidget(location_container)

        grid = QHBoxLayout()
        grid.setSpacing(8)
        self.humidity_value = QLabel("--")
        self.visibility_value = QLabel("--")
        self.precipitation_value = QLabel("--")
        self.wind_value = QLabel("--")
        self._mini(grid, "湿度", self.humidity_value)
        self._mini(grid, "能见度", self.visibility_value)
        self._mini(grid, "降水", self.precipitation_value)
        root.addLayout(grid)

        wind_aq = QHBoxLayout()
        wind_aq.setSpacing(8)

        # 风速容器
        wind_container = QFrame()
        wind_container.setObjectName("gcsWeatherMiniBox")
        wind_container.setFrameShape(QFrame.StyledPanel)
        wind_layout = QHBoxLayout(wind_container)
        wind_layout.setContentsMargins(8, 5, 8, 5)
        wind_layout.setSpacing(6)

        wv_title = QLabel("风速")
        wv_title.setObjectName("gcsWeatherHint")
        wind_layout.addWidget(wv_title)
        self.wind_value.setObjectName("gcsWeatherValue")
        wind_layout.addWidget(self.wind_value)
        wind_aq.addWidget(wind_container, 1)

        # 空气质量容器
        aq_container = QFrame()
        aq_container.setObjectName("gcsWeatherMiniBox")
        aq_container.setFrameShape(QFrame.StyledPanel)
        aq_layout = QHBoxLayout(aq_container)
        aq_layout.setContentsMargins(8, 5, 8, 5)
        aq_layout.setSpacing(6)

        aq_title = QLabel("空气质量")
        aq_title.setObjectName("gcsWeatherHint")
        aq_layout.addWidget(aq_title)
        self.air_quality_label = QLabel("--")
        self.air_quality_label.setObjectName("gcsWeatherAqi")
        aq_layout.addWidget(self.air_quality_label, 1)
        wind_aq.addWidget(aq_container, 1)

        root.addLayout(wind_aq)

    @staticmethod
    def _mini(layout: QHBoxLayout, title: str, value: QLabel) -> None:
        # 创建一个带边框的容器
        container = QFrame()
        container.setObjectName("gcsWeatherMiniBox")
        container.setFrameShape(QFrame.StyledPanel)

        col = QVBoxLayout(container)
        col.setContentsMargins(6, 5, 6, 5)
        col.setSpacing(3)

        t = QLabel(title)
        t.setObjectName("gcsWeatherHint")
        t.setAlignment(Qt.AlignCenter)

        value.setObjectName("gcsWeatherValue")
        value.setAlignment(Qt.AlignCenter)

        col.addWidget(t)
        col.addWidget(value)

        layout.addWidget(container, 1)

    @staticmethod
    def _air_quality_band(pm25: float) -> tuple[str, str]:
        if pm25 <= 35:
            return "优", "#4ade80"
        if pm25 <= 75:
            return "良", "#60a5fa"
        if pm25 <= 115:
            return "轻度", "#fbbf24"
        if pm25 <= 150:
            return "中度", "#fb923c"
        return "重度", "#f87171"

    def update_station_info(self, lat: float | None, lng: float | None, updated_at: str | None = None) -> None:
        lng_text = "--" if lng is None else f"{lng:.6f}"
        lat_text = "--" if lat is None else f"{lat:.6f}"
        self.title_label.setText(f"天气信息  ·  地面站 {lat_text}, {lng_text}")
        if updated_at:
            self.update_time_label.setText(f"更新 {updated_at}")

    def update_weather(self, weather_data: dict) -> None:
        if not weather_data:
            return
        if weather_data.get("last_updated"):
            self.update_time_label.setText(f"更新 {weather_data['last_updated']}")
        if weather_data.get("error"):
            self.condition_label.setText("天气获取失败")
            self.temp_label.setText("--°C")
            self.location_label.setText(str(weather_data.get("error")))
            self.humidity_value.setText("--")
            self.visibility_value.setText("--")
            self.precipitation_value.setText("--")
            self.wind_value.setText("--")
            self.air_quality_label.setText("--")
            return

        condition = weather_data.get("condition", "--")
        temp = weather_data.get("temperature")
        self.condition_label.setText(str(condition))
        self.temp_label.setText(f"{temp:.1f}°C" if temp is not None else "--°C")
        self.location_label.setText(f"📍 {weather_data.get('location_name', '--')}")

        h = weather_data.get("humidity")
        self.humidity_value.setText(f"{h:.0f}%" if h is not None else "--")

        vis = weather_data.get("visibility")
        self.visibility_value.setText(f"{vis:.1f} km" if vis is not None else "--")

        precip = weather_data.get("precipitation")
        if precip is None:
            self.precipitation_value.setText("--")
        elif precip < 0.1:
            self.precipitation_value.setText("无")
        else:
            self.precipitation_value.setText(f"{precip:.1f} mm")

        ws = weather_data.get("wind_speed")
        wd = weather_data.get("wind_dir") or ""
        self.wind_value.setText(f"{ws:.0f} km/h {wd}".strip() if ws is not None else "--")

        aq = weather_data.get("air_quality") or {}
        pm25 = aq.get("pm2_5")
        if pm25 is not None:
            band, color = self._air_quality_band(float(pm25))
            self.air_quality_label.setText(f"PM2.5 {pm25:.0f} ({band})")
            self.air_quality_label.setStyleSheet(f"color: {color}; font-weight: 700;")
        else:
            self.air_quality_label.setText("--")
            self.air_quality_label.setStyleSheet("color: #94a3b8; font-weight: 600;")
