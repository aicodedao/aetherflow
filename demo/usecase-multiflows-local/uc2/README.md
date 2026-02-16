# Usecase 2 — Exasol → 2 CSV → fill 2 Excel regions → SMB → email

Template: `templates/report_template.xlsx` with named ranges: SALES_ANCHOR, COST_ANCHOR
Production env vars:
EXA_DSN, EXA_USER, EXA_PASS
SMB_HOST, SMB_USER, SMB_PASS, SMB_SHARE
SMTP_HOST, SMTP_USER, SMTP_PASS
MAIL_TO
