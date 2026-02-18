# Docker MailHog: docker run -d --name mailhog -p 1025:1025 -p 8025:8025 mailhog/mailhog

import smtplib
from email.message import EmailMessage

import pytest


@pytest.mark.slow
def test_smtp():
    msg = EmailMessage()
    msg["Subject"] = "Test email"
    msg["From"] = "no-reply@example.com"
    msg["To"] = "huuthuong.nguyen@bertelsmann.de"
    msg.set_content("Hello from Python via MailHog!")

    with smtplib.SMTP("localhost", 1025) as s:
        s.send_message(msg)

    print("sent")

