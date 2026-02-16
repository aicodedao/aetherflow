# 19 — Connectors

Sources:
- aetherflow.core.connectors.base
- aetherflow.core.connectors.manager
- aetherflow.core.registry.connectors
- built-ins: aetherflow.core.builtins.connectors
- resource + profiles pipeline: aetherflow.core.runner, aetherflow.core.spec, aetherflow.core.resolution

Connectors are thin wrappers around drivers/transports (DB / HTTP / SFTP / SMTP / SMB / Archive …).

They are:
- created from `resources` (plus optional profiles overlay)
- resolved deterministically via the single resolver pipeline
- exposed to steps through:

  ctx.connectors["resource_name"]

This document is split into four parts:

- Part 1 — Conceptual model (resource → connector instance), resolution, merging, caching
- Part 2 — Using connectors (for users)
- Part 3 — Writing connectors (for plugin authors)
- Part 4 — Spec reference (advanced)

Related:
- 09-profiles-and-resources.md
- 18-plugins.md
- 06-yaml-spec.md

---

# Part 1 — Conceptual Model (Resource → Connector Instance)

## 1) What a Connector Is (and Is Not)

A connector is:
- a small object that wraps a driver/client (session, connection, transport)
- configured only by resolved `config` and `options`
- used by steps as a primitive (execute/query/upload/send/etc.)

A connector is NOT:
- an orchestrator
- a workflow engine
- a scheduler
- a global singleton that lives across runs by default

Core idea:

    Resource definition (YAML)
        → resolved config/options
        → connector instance
        → ctx.connectors

---

## 2) Resource Definition Fields (Flow YAML)

Resource shape:

    resources:
      <name>:
        kind: string
        driver: string
        profile: string        # optional
        config: {}
        options: {}
        decode: {}

Meaning:

- name → accessed via `ctx.connectors[name]`
- kind → logical category (db, rest, sftp, mail, smb, archive, …)
- driver → concrete implementation
- profile → optional overlay
- config → driver configuration
- options → runtime knobs
- decode → keys passed through secrets decoder

See:
- 06-yaml-spec.md
- 12-secrets.md

---

## 3) Connector Build Pipeline

When building connectors, the runner:

1. Loads env snapshot (`ctx.env`)
2. Loads profiles
3. For each resource:
  - Applies profile overlay
  - Resolves templates in `config` and `options`
  - Applies secrets decoding
  - Instantiates connector via registry
  - Applies caching policy
4. Publishes instance to `ctx.connectors`

Properties:
- deterministic
- no `os.environ` mutation
- connector receives fully resolved config/options

---

## 4) Merge Order

Conceptual merge order:

    Base resource YAML
      → apply profile overlay
      → resolve templates
      → apply decode hook
      → instantiate connector

Resource YAML defines intent.  
Profiles define environment-specific overlays.

---

## 5) Caching Model

Caching behavior is controlled by:

- AETHERFLOW_CONNECTOR_CACHE_DEFAULT
- AETHERFLOW_CONNECTOR_CACHE_DISABLED

General rule:
- cache safely within a single run
- do not rely on global process-wide caching unless explicitly configured

Recommended:
- cache per-run only

See:
- 14-settings.md
- 15-concurrency.md

---

# Part 2 — Using Connectors (Users)

## 1) Define a Resource

REST example:

    resources:
      api:
        kind: rest
        driver: httpx
        config:
          base_url: "https://example.com"
          token: "{{ env.API_TOKEN }}"
        options:
          timeout_seconds: 30
        decode:
          config:
            token: true

DB example:

    resources:
      db_main:
        kind: db
        driver: postgres
        profile: prod
        config:
          host: "{{ env.DB_HOST }}"
          user: "{{ env.DB_USER }}"
          password: "{{ env.DB_PASSWORD }}"
        options:
          connect_timeout: 10
        decode:
          config:
            password: true

Steps access connectors via:

    ctx.connectors["db_main"]

Never instantiate drivers manually inside steps.

---

## 2) Step Usage Pattern

Inside a step:

- retrieve connector from `ctx.connectors`
- call connector primitive
- write results to artifacts
- return metadata outputs

Do NOT:
- read secrets directly from `os.environ`
- recreate connections repeatedly
- bypass the connector layer

---

## 3) Usage Best Practices

- Keep outputs small (metadata only)
- Write large data to artifacts
- Lock shared side-effects with `with_lock`
- Let steps orchestrate, connectors transport

---

# Part 3 — Writing Connectors (Plugin Authors)

## 1) Public API Only

    from aetherflow.core.api import register_connector, ConnectorBase

Do not import internal modules.

---

## 2) Connector Lifecycle

A connector:

- is instantiated once per resource (subject to cache policy)
- stores resolved `config` and `options`
- lazily creates underlying client/handle

Minimal template:

    from aetherflow.core.api import register_connector, ConnectorBase

    @register_connector(kind="rest", driver="myhttp")
    class MyHttpConnector(ConnectorBase):

        def __init__(self, *, config, options):
            self.config = config
            self.options = options
            self._client = None

        def connect(self):
            if self._client is None:
                self._client = self._create_client()
            return self._client

        def _create_client(self):
            # use self.config and self.options only
            ...

---

## 3) MUST-HAVE Rules

- Deterministic initialization
- No `os.environ` reads
- No secret logging
- Clear error semantics
- Thread-safe if shared within run
- No hidden retries inside connector

---

## 4) NICE-TO-HAVE

- Context manager support
- Explicit timeout handling
- Minimal primitive wrappers
- Clean close()/cleanup behavior

Retries and orchestration belong in steps, not connectors.

---

# Part 4 — Advanced Reference

## 1) Registry Model

Connector key:

    (kind, driver)

At runtime:

    resource.kind + resource.driver → connector class

Built-ins register in:
aetherflow.core.builtins.connectors

Plugins register via:
register_connector decorator

---

## 2) Listing Connectors

You can inspect registry via:

    from aetherflow.core.api import list_connectors
    print(list_connectors())

Useful for debugging plugin discovery.

---

## 3) Built-in Connectors

Defined in:
aetherflow.core.builtins.connectors

Examples include:

- rest/httpx
- mail/smtp
- sftp/paramiko
- db/duckdb
- db/sqlite3
- db/postgres
- smb/* drivers
- archive/* drivers

See:
- 23-builtins-catalog.md

---

# 5) Summary

Connectors are:

- deterministic wrappers
- configured by resources
- resolved via strict templating
- instantiated via registry
- accessed via ctx.connectors

Keep them small.
Keep them predictable.
Keep orchestration in steps.
Keep global state out.
