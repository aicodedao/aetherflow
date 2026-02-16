from __future__ import annotations

from typing import Any, Dict

from aetherflow.core.api import Step, register_step


@register_step("mail_send_dummy")
class MailSend(Step):
    """Send an email via a configured mail resource.

    Inputs:
      - resource: mail resource name (kind=mail, driver=smtp)
      - to: string or list of strings
      - subject: string
      - body: plaintext body OR html body (when html=true)
      - html: bool (default false)
      - text: optional plaintext fallback when html=true
      - cc: optional string/list
      - bcc: optional string/list
      - from_addr: optional override
    """

    required_inputs = {"resource", "to", "subject", "body"}

    def run(self) -> Dict[str, Any]:
        self.validate()
        mail = self.ctx.connectors[self.inputs["resource"]]
        to = self.inputs["to"]
        subject = str(self.inputs["subject"])
        body = str(self.inputs["body"])

        cc = self.inputs.get("cc")
        bcc = self.inputs.get("bcc")
        from_addr = self.inputs.get("from_addr", "no-reply@test.com")

        mail.send_plaintext(to=to, subject=subject, body=body, cc=cc, bcc=bcc, from_addr=from_addr)
        return {"sent": True, "to": to, "subject": subject, "body": body}
