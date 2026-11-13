# ui/weather_card.py
"""地面站信息与天气信息合并卡片。"""
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt


class WeatherInfoCard(QFrame):
    """在同一窗口中显示地面站信息和天气信息。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet("""
            WeatherInfoCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e6f7ff, stop:1 #bae7ff);
                border: 2px solid #69c0ff;
                border-radius: 12px;
                margin: 0px;
            }
            QLabel#titleLabel {
                font-size: 15px;
                font-weight: bold;
                color: #003a8c;
                padding: 6px 0px;
                background: transparent;
            }
            QLabel#stationInlineLabel {
                font-size: 13px;
                font-weight: 600;
                color: #1890ff;
                background: transparent;
                padding: 6px 0px;
            }
            QLabel#sectionTitle {
                font-size: 13px;
                font-weight: bold;
                color: #0050b3;
                background: transparent;
            }
            QFrame#sectionBox {
                background-color: rgba(255, 255, 255, 0.78);
                border: 1px solid #91d5ff;
                border-radius: 10px;
            }
            QLabel#coordLabel {
                font-size: 13px;
                font-weight: 700;
                color: #0050b3;
                background: transparent;
            }
            QLabel#coordValue {
                font-size: 13px;
                font-weight: 600;
                color: #1890ff;
                background-color: rgba(255, 255, 255, 0.95);
                padding: 6px 10px;
                border-radius: 8px;
                border: 1px solid #91d5ff;
            }
            QLabel#weatherValue {
                font-size: 12px;
                font-weight: 600;
                color: #1890ff;
                background-color: rgba(255, 255, 255, 0.9);
                padding: 5px 8px;
                border-radius: 6px;
                border: 1px solid #91d5ff;
            }
            QLabel#weatherLabel {
                font-size: 12px;
                color: #0050b3;
                font-weight: 600;
                background: transparent;
            }
            QLabel#conditionLabel {
                font-size: 15px;
                font-weight: bold;
                color: #0050b3;
                background-color: rgba(255, 255, 255, 0.95);
                padding: 6px 10px;
                border-radius: 8px;
                border: 2px solid #40a9ff;
            }
            QLabel#tempLabel {
                font-size: 24px;
                font-weight: bold;
                color: #ff4d4f;
                padding: 4px 8px;
                background: rgba(255, 255, 255, 0.8);
                border-radius: 8px;
            }
            QLabel#locationLabel {
                font-size: 12px;
                color: #434343;
                font-weight: 500;
                background: transparent;
            }
            QLabel#hintLabel {
                font-size: 12px;
                color: #595959;
                background: transparent;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 8, 10, 8)

        title_layout = QHBoxLayout()
        title_label = QLabel("地面站信息 / 天气信息")
        title_label.setObjectName("titleLabel")
        title_layout.addWidget(title_label)

        self.station_info_label = QLabel("经度: --    纬度: --")
        self.station_info_label.setObjectName("stationInlineLabel")
        title_layout.addWidget(self.station_info_label)
        layout.addLayout(title_layout)

        weather_box = QFrame()
        weather_box.setObjectName("sectionBox")
        weather_layout = QVBoxLayout(weather_box)
        weather_layout.setContentsMargins(10, 8, 10, 8)
        weather_layout.setSpacing(6)
        weather_title_layout = QHBoxLayout()
        weather_title_layout.setContentsMargins(0, 0, 0, 0)
        weather_title_layout.setSpacing(8)

        weather_title = QLabel("天气信息")
        weather_title.setObjectName("sectionTitle")
        weather_title_layout.addWidget(weather_title)
        weather_title_layout.addStretch()

        self.update_time_label = QLabel("")
        self.update_time_label.setStyleSheet(
            "color: #595959; font-size: 11px; font-weight: 500; background: transparent;"
        )
        weather_title_layout.addWidget(self.update_time_label, alignment=Qt.AlignRight)
        weather_layout.addLayout(weather_title_layout)

        condition_layout = QHBoxLayout()
        self.condition_label = QLabel("--")
        self.condition_label.setObjectName("conditionLabel")
        self.condition_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.condition_label.setWordWrap(True)
        condition_layout.addWidget(self.condition_label)

        self.temp_label = QLabel("--°C")
        self.temp_label.setObjectName("tempLabel")
        self.temp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        condition_layout.addWidget(self.temp_label)
        weather_layout.addLayout(condition_layout)

        self.location_label = QLabel("位置: --")
        self.location_label.setObjectName("locationLabel")
        self.location_label.setWordWrap(True)
        weather_layout.addWidget(self.location_label)

        info_layout = QHBoxLayout()
        info_layout.setSpacing(6)
        info_layout.setContentsMargins(0, 4, 0, 0)

        self.humidity_value = QLabel("--")
        self.visibility_value = QLabel("--")
        self.precipitation_value = QLabel("--")
        self.wind_value = QLabel("--")

        self._add_info_item(info_layout, "湿度", self.humidity_value, "💧")
        self._add_info_item(info_layout, "能见度", self.visibility_value, "👁️")
        self._add_info_item(info_layout, "降水量", self.precipitation_value, "☔")
        weather_layout.addLayout(info_layout)

        air_layout = QHBoxLayout()
        air_layout.setSpacing(10)

        wind_title = QLabel("💨 风速:")
        wind_title.setObjectName("weatherLabel")
        air_layout.addWidget(wind_title, 0, Qt.AlignLeft)
        self.wind_value.setAlignment(Qt.AlignCenter)
        self.wind_value.setWordWrap(False)
        self.wind_value.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.wind_value.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #1890ff; background: transparent; border: none; padding: 0px;"
        )
        air_layout.addWidget(self.wind_value, 0, Qt.AlignLeft)

        air_title = QLabel("🌫️ 空气质量:")
        air_title.setObjectName("weatherLabel")
        air_layout.addWidget(air_title, 0, Qt.AlignLeft)
        self.air_quality_label = QLabel("--")
        self.air_quality_label.setStyleSheet(
            "color: #52c41a; font-weight: bold; font-size: 12px; background: transparent;"
        )
        self.air_quality_label.setWordWrap(True)
        air_layout.addWidget(self.air_quality_label, 1, Qt.AlignLeft)
        air_layout.addStretch()
        weather_layout.addLayout(air_layout)

        layout.addWidget(weather_box)
        layout.addStretch(1)
    def _add_info_item(self, layout: QHBoxLayout, label_text: str, value_label: QLabel, icon: str):
        wrap = QFrame()
        wrap.setStyleSheet("QFrame{background:transparent; border:none;}")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        label = QLabel(f"{icon} {label_text}")
        label.setObjectName("weatherLabel")
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        value_label.setObjectName("weatherValue")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setWordWrap(False)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row.addWidget(label)
        row.addWidget(value_label, 1)
        layout.addWidget(wrap, 1)

    def _get_air_quality_text(self, pm25):
        if pm25 <= 35:
            return "优", "#52c41a"
        if pm25 <= 75:
            return "良", "#1890ff"
        if pm25 <= 115:
            return "轻度污染", "#faad14"
        if pm25 <= 150:
            return "中度污染", "#fa8c16"
        return "重度污染", "#f5222d"

    def update_station_info(self, lat=None, lng=None, updated_at: str = None):
        """更新地面站经纬度与刷新时间。"""
        lng_text = "--" if lng is None else f"{lng:.6f}"
        lat_text = "--" if lat is None else f"{lat:.6f}"
        self.station_info_label.setText(f"经度: {lng_text}    纬度: {lat_text}")
        if updated_at:
            self.update_time_label.setText(f"更新: {updated_at}")

    def update_weather(self, weather_data):
        """更新天气显示。"""
        if not weather_data:
            return

        if weather_data.get("last_updated"):
            self.update_time_label.setText(f"更新: {weather_data['last_updated']}")

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
        self.condition_label.setText(condition)
        self.temp_label.setText(f"{temp:.1f}°C" if temp is not None else "--°C")

        location_name = weather_data.get("location_name", "--")
        self.location_label.setText(f"📍 {location_name}")

        humidity = weather_data.get("humidity")
        self.humidity_value.setText(f"{humidity:.0f}%" if humidity is not None else "--")

        visibility = weather_data.get("visibility")
        self.visibility_value.setText(f"{visibility:.1f} km" if visibility is not None else "--")

        precip = weather_data.get("precipitation")
        if precip is None:
            self.precipitation_value.setText("--")
        elif precip < 0.1:
            self.precipitation_value.setText("无")
        else:
            self.precipitation_value.setText(f"{precip:.1f} mm")

        wind_speed = weather_data.get("wind_speed")
        wind_dir = weather_data.get("wind_dir", "")
        self.wind_value.setText(
            f"{wind_speed:.0f} km/h {wind_dir}".strip() if wind_speed is not None else "--"
        )

        air_quality = weather_data.get("air_quality", {})
        pm25 = air_quality.get("pm2_5") if air_quality else None
        if pm25 is not None:
            quality, color = self._get_air_quality_text(pm25)
            self.air_quality_label.setText(f"PM2.5: {pm25:.0f} ({quality})")
            self.air_quality_label.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 12px; background: transparent;"
            )
        else:
            self.air_quality_label.setText("--")
