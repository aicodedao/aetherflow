from __future__ import annotations
from aetherflow.core.api import ConnectorError, ConnectorBase, ConnectorInit, register_connector, require, require_attr

@register_connector(kind="mail", driver="mail-dummy")
class MailDummy(ConnectorBase):
    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self.sent = []
        self.cfg = init.config or {}
        self.options = init.options or {}
        self.log = init.ctx.log if init.ctx else None
        if not self.log:
            logging = require("logging")
            self.log = logging.getLogger("aetherflow.custom.plugins.steps.mail-dummy")

    def send_dummy(self, to, subject, body, **kwargs):
        self.sent.append({"to": to, "subject": subject, "body": body, "kwargs": kwargs})

    def send_plaintext(self, *, to: list[str] | str, subject: str, body: str,
             from_addr: str | None = None, cc: list[str] | str | None = None,
             bcc: list[str] | str | None = None) -> None:
        smtplib = require("smtplib")
        EmailMessage = require_attr("email.message", "EmailMessage")
        try:
            host = self.cfg["host"]
            port = int(self.cfg.get("port", 1025))
            # user = self.cfg["user"]
            # password = self.cfg.get("password")
            # timeout = int(self.options.get("timeout", 30) or 30)
            with smtplib.SMTP(host, port) as s:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = from_addr or self._from_addr()
                msg["To"] = ", ".join(to) if isinstance(to, list) else to
                if cc:
                    msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
                # BCC is not set as header by default; still used as recipients
                msg.set_content(body)

                recipients: list[str] = []
                recipients += (to if isinstance(to, list) else [to])
                if cc:
                    recipients += (cc if isinstance(cc, list) else [cc])
                if bcc:
                    recipients += (bcc if isinstance(bcc, list) else [bcc])

                s.send_message(msg)
        except Exception as e:
            self.log.warning(f"SFTP connect failed: {e}")
            pass