"""侧边栏「无人机信息」页中的遥测卡片。"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class UavStripCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("uavStripCard")
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self.title = QLabel("—")
        self.title.setObjectName("uavStripTitle")
        self.body = QLabel("—")
        self.body.setObjectName("uavStripBody")
        self.body.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.body)

    def set_sim(
        self,
        drone_id: str,
        lat: float,
        lon: float,
        alt: float,
        speed: float,
        status: str,
    ) -> None:
        self.title.setText(f"{drone_id}  ·  仿真")
        self.body.setText(
            f"φ {lat:.5f}°  λ {lon:.5f}°\n"
            f"高度 {alt:.1f} m  ·  {speed:.1f} m/s  ·  {status}"
        )

    def set_real(
        self,
        drone_id: str,
        name: str,
        lat: float | None,
        lon: float | None,
        alt: float | None,
        battery: float | None,
        sats: int | None,
        connected: bool,
    ) -> None:
        st = "已连接" if connected else "未连接"
        self.title.setText(f"{drone_id}  ·  实机 ({name})")
        la = f"{lat:.5f}" if lat is not None else "—"
        lo = f"{lon:.5f}" if lon is not None else "—"
        al = f"{alt:.1f}" if alt is not None else "—"
        bat = f"{battery:.0f}%" if battery is not None else "—"
        sv = str(sats) if sats is not None else "—"
        self.body.setText(f"φ {la}°  λ {lo}°\n高度 {al} m  ·  电量 {bat}  ·  星 {sv}  ·  {st}")

    def set_placeholder(self, text: str = "—") -> None:
        self.title.setText("空")
        self.body.setText(text)
