# aetherflow demo

This folder is a runnable “smoke test” for the repo.

What it demonstrates:

- loading profiles from `demo/profiles.yaml`
- optional secrets decoding via `demo/secrets/set_envs.py`
- running a simple flow (`db_extract` writing an artifact file)
- job-level gating via `job.when` (skip a job if a condition is false)
- step-level short-circuit via `step.on_no_data: skip_job` (skip the rest of a job)
- running the APScheduler adapter

## 1) Install

You can run the demo in three ways.

### A) Install from PyPI (end users)

```bash
python -m pip install -U pip
pip install "aetherflow-core[all]" aetherflow-scheduler
```

### B) Install from TestPyPI (maintainers / pre-release validation)

```bash
python -m pip install -U pip
pip install -i https://test.pypi.org/simple \
  --extra-index-url https://pypi.org/simple \
  "aetherflow-core[all]" aetherflow-scheduler
```

### C) Install from source (editable, for development)

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

pip install -e packages/aetherflow-core[all,dev]
pip install -e packages/aetherflow-scheduler[dev]
```


## 2) Run the flow once

```bash
export AETHERFLOW_PROFILES_FILE=demo/profiles.yaml
export AETHERFLOW_SECRETS_PATH=demo/secrets/set_envs.py  # optional

# For the demo flow you just need a SQLAlchemy DB_URL.
# Example: SQLite file
export DB_URL="sqlite:///demo_state/demo.sqlite"

aetherflow run demo/flows/demo_flow.yaml
```

### Optional: load env from files (dotenv/json/dir)

You can load env vars into the run snapshot without touching `os.environ`, by
setting `AETHERFLOW_ENV_FILES_JSON`:

```bash
export AETHERFLOW_ENV_FILES_JSON='[{"type":"dotenv","path":"demo/.env","optional":true}]'
```

The load order is deterministic:

`os.environ` < `env_files` (from `AETHERFLOW_ENV_FILES_JSON`) < `step.env` (per step)

### Try the skip behavior

Open `demo/flows/demo_flow.yaml` and set:

```yaml
items: []
```

Then rerun the flow. The `probe` job will still run, but `extract_only` will be marked **SKIPPED** because
`jobs.probe.outputs.has_data == true` evaluates to false.

Artifacts are written under `/tmp/demo_work/.../artifacts/`.

## 3) Secrets decoding demo (Oracle profile)

`demo/profiles.yaml` also includes an `oracle_main` profile. It marks `config.password` as `decode: true`.

If you switch the flow resource to use `driver: oracledb` and `profile: oracle_main`, aetherflow will call your secrets provider’s `decode()` for the password.

The included demo decoder expects the raw env var to be base64:

```bash
export AETHERFLOW_PROFILES_FILE=demo/profiles.yaml
export AETHERFLOW_SECRETS_PATH=demo/secrets/set_envs.py

export ORA_USER="my_user"
export ORA_DSN="my_dsn"
export ORA_PASS="bXlfcGFzc3dvcmQ="  # base64("my_password")
```

### Debug helpers

Check missing env keys required by profiles:

```bash
aetherflow doctor demo/flows/demo_flow.yaml
```

Explain profile -> env attribution (and decode flags):

```bash
aetherflow explain demo/flows/demo_flow.yaml
```

### Doctor + explain (env/profile sanity)

Check that all required env keys for profiles are present:

```bash
aetherflow doctor demo/flows/demo_flow.yaml
```

And explain which env keys map into each profile field (with redaction):

```bash
aetherflow explain demo/flows/demo_flow.yaml
```

## 4) Run the scheduler

```bash
aetherflow-scheduler run demo/scheduler/scheduler.yaml
```

This schedules the demo flow every 5 minutes.
