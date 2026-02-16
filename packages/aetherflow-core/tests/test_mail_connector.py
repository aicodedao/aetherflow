from __future__ import annotations


class DummySMTP:
    def __init__(self, host=None, port=None, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sent = []
        self.closed = False

    def ehlo(self):
        return None

    def starttls(self):
        return None

    def login(self, user, pwd):
        return None

    def send_message(self, msg, to_addrs=None):
        self.sent.append((msg, tuple(to_addrs or [])))
        return {}

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


def test_mail_smtp_send_plaintext(monkeypatch):
    # Late import so builtins have loaded.
    import aetherflow.core.builtins.connectors  # noqa: F401
    from aetherflow.core.registry.connectors import REGISTRY

    import smtplib

    dummy = DummySMTP()

    def _smtp(host=None, port=None, timeout=None):
        dummy.host = host
        dummy.port = port
        dummy.timeout = timeout
        return dummy

    monkeypatch.setattr(smtplib, "SMTP", _smtp)

    conn = REGISTRY.create(
        name="mail1",
        kind="mail",
        driver="smtp",
        config={"host": "smtp.example", "port": 587, "username": "u", "password": "p"},
        options={"timeout": 5, "retry": {"max_attempts": 1}},
        ctx=None,
    )

    conn.send_plaintext(to=["a@example"], subject="hi", body="yo")
    assert len(dummy.sent) == 1
    msg, to_addrs = dummy.sent[0]
    assert "hi" in msg["Subject"]
    assert "a@example" in to_addrs

