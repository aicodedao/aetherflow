# Usecase 1 — SFTP → unzip → transform → zip → SMB → email

## Production env vars
SFTP: SFTP_HOST, SFTP_PORT (opt), SFTP_USER, SFTP_PASS
SMB:  SMB_HOST, SMB_PORT (opt), SMB_USER, SMB_PASS, SMB_SHARE
SMTP: SMTP_HOST, SMTP_PORT (opt), SMTP_USER, SMTP_PASS
MAIL_TO: comma-separated recipients

Bundle-from-SMB (if using manifest_smb.yaml):
BUNDLE_SMB_HOST, BUNDLE_SMB_SHARE, BUNDLE_SMB_USER, BUNDLE_SMB_PASS
