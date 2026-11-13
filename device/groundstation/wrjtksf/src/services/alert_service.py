from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Dict, List, Optional

from src.domain.models import AlertRecord


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    to_email: str


class MockMailer:
    def send(self, subject: str, body: str) -> str:
        return f"[MOCK] {subject} | {body}"


class SmtpMailer:
    def __init__(self, config: SMTPConfig) -> None:
        self.config = config

    def send(self, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config.from_email
        msg["To"] = self.config.to_email
        msg.set_content(body)

        with smtplib.SMTP(self.config.host, self.config.port, timeout=8) as smtp:
            smtp.starttls()
            smtp.login(self.config.username, self.config.password)
            smtp.send_message(msg)
        return f"[SMTP] sent to {self.config.to_email}"


class AlertService:
    def __init__(self, cooldown_seconds: float, mode: str = "mock", smtp_config: Optional[SMTPConfig] = None) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.mode = mode
        self.smtp_config = smtp_config
        self.records: List[AlertRecord] = []
        self.last_sent_at: Dict[str, float] = {}

        self.mailer = MockMailer()
        if mode == "smtp" and smtp_config:
            self.mailer = SmtpMailer(smtp_config)

    def trigger_deviation_alert(self, drone_id: str, now: float, distance: float) -> str:
        last = self.last_sent_at.get(drone_id, -1e9)
        if now - last < self.cooldown_seconds:
            return "cooldown"

        subject = f"Drone {drone_id} deviation warning"
        body = f"Drone {drone_id} is off route, distance={distance:.2f}m."
        result = self.mailer.send(subject, body)
        self.last_sent_at[drone_id] = now
        self.records.append(
            AlertRecord(
                drone_id=drone_id,
                message=f"{subject} | {result}",
                timestamp=now,
                active=True,
            )
        )
        return result

    def trigger_event_alert(self, drone_id: str, now: float, event: str, detail: str) -> str:
        key = f"{drone_id}:{event}"
        last = self.last_sent_at.get(key, -1e9)
        if now - last < self.cooldown_seconds:
            return "cooldown"
        subject = f"Drone {drone_id} {event} warning"
        body = f"{event}: {detail}"
        result = self.mailer.send(subject, body)
        self.last_sent_at[key] = now
        self.records.append(
            AlertRecord(
                drone_id=drone_id,
                message=f"{subject} | {result}",
                timestamp=now,
                active=True,
            )
        )
        return result

    def reset_session(self) -> None:
        """清空告警记录与冷却表（场景切换 / 演示重置时使用）。"""
        self.records.clear()
        self.last_sent_at.clear()
