# Aetherflow – production-grade demo bundle (2 use-cases)

This bundle contains **two end-to-end examples**:
1) SFTP list → SFTP download → local unzip → local transform → local zip → SMB upload → email
2) Exasol query → 2 CSV → write 2 regions in Excel template → SMB upload → email

Each usecase includes:
- flow YAMLs (`flows/main.yaml` for remote)
- profiles/resources (`profiles.yaml`)
- manifest for bundle fetch from SMB (`manifest_smb.yaml`)
- custom plugins (connectors + steps) under `plugins/`

## Install (PyPI)
```bash
pip install "aetherflow-core[reports]"
pip install paramiko pysmb pyexasol
```

## Run remote demo
```bash
# setup envs in Windows
set SFTP_HOST=
set SFTP_PORT=22
set SFTP_USER=
set SFTP_PASS=<encoded_value, which decoded by set_envs.py>

set SMB_HOST=
set SMB_PORT=445
set SMB_USER=
set SMB_PASS=<encoded_value, which decoded by set_envs.py>

# MailHog Container as test
# docker run -d --name mailhog -p 1025:1025 -p 8025:8025 mailhog/mailhog
set SMTP_HOST=localhost
set SMTP_PORT=1025
set SMTP_USER=
set SMTP_PASS=

set EXA_DSN=
set EXA_USER=
set EXA_PASS=<encoded_value, which decoded by set_envs.py>

set AETHERFLOW_SECRETS_PATH=<...\set_envs.py>

```

```bash
cd uc1
aetherflow bundle sync --bundle-manifest manifest_smb.yaml
aetherflow run --bundle-manifest manifest_smb.yaml --flow-yaml flows/main.yaml
```

```bash
cd ../uc2
aetherflow bundle sync --bundle-manifest manifest_smb.yaml
aetherflow run --bundle-manifest manifest_smb.yaml --flow-yaml flows/main.yaml
```
