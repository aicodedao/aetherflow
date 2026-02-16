from __future__ import annotations
from aetherflow.core.api import ConnectorBase, ConnectorInit, register_connector

@register_connector(kind="mail", driver="mail-dummy")
class MailDummy(ConnectorBase):
    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self.sent = []

    def send(self, to, subject, body, **kwargs):
        self.sent.append({"to": to, "subject": subject, "body": body, "kwargs": kwargs})
