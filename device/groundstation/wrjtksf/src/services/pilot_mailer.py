"""飞手通知邮件（HTML），配置来自 config/demo_config.yaml 的 gcs 段与环境变量。"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _gcs_bool(gcs: Dict[str, Any], key: str, default: bool) -> bool:
    v = gcs.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class PilotMailer:
    def __init__(self, gcs: Optional[Dict[str, Any]] = None) -> None:
        self._gcs: Dict[str, Any] = dict(gcs or {})

    def is_enabled(self) -> bool:
        if _env_bool("PILOT_SMTP_ENABLED", False):
            return True
        if _gcs_bool(self._gcs, "pilot_smtp_enabled", False):
            return True
        if _env_bool("SMTP_ENABLED", False):
            return True
        return False

    def send_html(self, to_addrs: List[str], subject: str, html_body: str) -> Tuple[bool, str]:
        if not to_addrs or not any(x.strip() for x in to_addrs):
            return False, "无收件人"
        recipients = [x.strip() for x in to_addrs if x.strip()]
        host = (
            os.environ.get("PILOT_SMTP_HOST")
            or str(self._gcs.get("pilot_smtp_host") or "").strip()
            or os.environ.get("SMTP_SERVER")
            or ""
        )
        port_raw = os.environ.get("PILOT_SMTP_PORT") or self._gcs.get("pilot_smtp_port") or os.environ.get("SMTP_PORT")
        port = int(port_raw or 465)
        user = (
            os.environ.get("PILOT_SMTP_USERNAME")
            or str(self._gcs.get("pilot_smtp_username") or "").strip()
            or os.environ.get("SMTP_USERNAME")
            or ""
        )
        password = (
            os.environ.get("PILOT_SMTP_PASSWORD")
            or str(self._gcs.get("pilot_smtp_password") or "").strip()
            or os.environ.get("SMTP_PASSWORD")
            or ""
        )
        use_ssl = _env_bool(
            "PILOT_SMTP_USE_SSL",
            _gcs_bool(self._gcs, "pilot_smtp_use_ssl", _env_bool("SMTP_USE_SSL", True)),
        )
        use_tls = _env_bool(
            "PILOT_SMTP_USE_STARTTLS",
            _gcs_bool(self._gcs, "pilot_smtp_use_starttls", _env_bool("SMTP_USE_STARTTLS", False)),
        )
        sender = (
            os.environ.get("PILOT_MAIL_SENDER")
            or str(self._gcs.get("pilot_mail_sender") or "").strip()
            or os.environ.get("MAIL_SENDER")
            or user
        )
        if not host or not user or not password:
            return False, "SMTP 未完整配置（config/demo_config.yaml 中 gcs.pilot_smtp_* 或环境变量 PILOT_SMTP_* / SMTP_*）"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.set_content("请使用支持 HTML 的邮件客户端查看。")
        msg.add_alternative(html_body, subtype="html")

        try:
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=12) as smtp:
                    smtp.login(user, password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=12) as smtp:
                    if use_tls:
                        smtp.starttls()
                    smtp.login(user, password)
                    smtp.send_message(msg)
        except Exception as e:
            return False, str(e)
        return True, f"已发送至 {', '.join(recipients)}"
