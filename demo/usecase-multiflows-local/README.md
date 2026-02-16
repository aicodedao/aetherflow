# Aetherflow – production-grade demo bundle (2 use-cases)

This bundle contains **two end-to-end examples**:
1) SFTP list → SFTP download → local unzip → local transform → local zip → SMB upload → email
2) Exasol query → 2 CSV → write 2 regions in Excel template → SMB upload → email

Each usecase includes:
- flow YAMLs (`flows/demo_local.yaml` for local infra-free test)
- profiles/resources (`profiles.yaml`)
- manifest for filesystem (`manifest_local.yaml`) 
- custom plugins (connectors + steps) under `plugins/`

## Install (PyPI)
```bash
pip install "aetherflow-core[reports]"
pip install paramiko pysmb pyexasol
```

## Run local demo (no infra)
```bash
cd uc1
aetherflow bundle sync --bundle-manifest manifest_local.yaml
aetherflow run --bundle-manifest manifest_local.yaml --flow-yaml flows/demo_local.yaml
```

```bash
cd ../uc2
aetherflow bundle sync --bundle-manifest manifest_local.yaml
aetherflow run --bundle-manifest manifest_local.yaml --flow-yaml flows/demo_local.yaml
```
