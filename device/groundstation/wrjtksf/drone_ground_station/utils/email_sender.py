import os
import socket
import smtplib
from typing import List, Optional, Sequence, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


class EmailSender:
    """
    一个简洁稳健的邮件发送器，支持：
    - TLS/SSL（端口 587 一般配合 STARTTLS，端口 465 使用 SSL）
    - 文本或 HTML 正文
    - 抄送（cc）与密送（bcc）
    - 多个附件
    - 简单重试与超时控制

    常见 SMTP 服务器与端口：
    - QQ: smtp.qq.com:465 (SSL) 或 587 (STARTTLS)（需开启“POP3/SMTP服务”并使用授权码）
    - 163: smtp.163.com:465 (SSL) 或 587 (STARTTLS)
    - Gmail: smtp.gmail.com:465 (SSL) 或 587 (STARTTLS)
    """

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        use_ssl: bool = False,
        use_starttls: bool = True,
        timeout_sec: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        if use_ssl and use_starttls:
            # 二者不可同时为 True
            use_starttls = False
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.use_starttls = use_starttls
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    def _build_message(
        self,
        sender: str,
        to: Sequence[str],
        subject: str,
        body: str,
        body_is_html: bool,
        cc: Optional[Sequence[str]] = None,
        bcc: Optional[Sequence[str]] = None,
        attachments: Optional[Sequence[str]] = None,
    ) -> Tuple[MIMEMultipart, List[str]]:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)

        mime = MIMEText(body, "html" if body_is_html else "plain", "utf-8")
        msg.attach(mime)

        # 附件
        for path in attachments or []:
            if not path:
                continue
            if not os.path.exists(path):
                continue
            filename = os.path.basename(path)
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)

        # 收件人总表（直投）
        all_rcpts: List[str] = list(to)
        if cc:
            all_rcpts.extend(cc)
        if bcc:
            all_rcpts.extend(bcc)
        return msg, all_rcpts

    def send_email(
        self,
        sender: str,
        to: Sequence[str],
        subject: str,
        body: str,
        body_is_html: bool = False,
        cc: Optional[Sequence[str]] = None,
        bcc: Optional[Sequence[str]] = None,
        attachments: Optional[Sequence[str]] = None,
    ) -> None:
        if not to:
            raise ValueError("收件人列表 to 不能为空")

        msg, all_rcpts = self._build_message(
            sender=sender,
            to=to,
            subject=subject,
            body=body,
            body_is_html=body_is_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 2):  # 尝试 max_retries 次 + 第一次
            try:
                socket.setdefaulttimeout(self.timeout_sec)

                if self.use_ssl:
                    server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=self.timeout_sec)
                else:
                    server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout_sec)

                try:
                    server.ehlo()
                    if self.use_starttls and not self.use_ssl:
                        server.starttls()
                        server.ehlo()

                    server.login(self.username, self.password)
                    server.sendmail(sender, all_rcpts, msg.as_string())
                finally:
                    try:
                        server.quit()
                    except Exception:
                        pass
                return
            except Exception as e:
                last_err = e
                if attempt <= self.max_retries + 1:
                    continue
        # 如果执行到这里，说明全部尝试失败
        raise RuntimeError(f"发送邮件失败: {last_err}") from last_err



