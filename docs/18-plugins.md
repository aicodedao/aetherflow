# 18 — Plugins

Sources:
- aetherflow.core.plugins
- public API in aetherflow.core.api
- plugin discovery via AETHERFLOW_PLUGIN_PATHS
- runtime wiring in aetherflow.core.runner

Plugins let you extend AetherFlow without modifying core.

You can:
- register new step types
- register new connector drivers

Core remains small and stable. Extensions live outside.

If this document and the code disagree, the public API is authoritative.

---

# 1) Golden Rule — Public API Only

Plugins must import only from:

    aetherflow.core.api

Example:

    from aetherflow.core.api import (
        register_step,
        register_connector,
        Step,
        StepResult,
        STEP_SUCCESS,
        STEP_SKIPPED,
    )

Do NOT import internal modules such as:

- aetherflow.core.runner
- aetherflow.core.builtins.*
- aetherflow.core.connectors.manager
- aetherflow.core.resolution

Internal modules may change at any time.

Public API is the only SemVer-stable surface.

See:
25-public-api-and-semver.md

---

# 2) Plugin Discovery

Plugins are discovered via:

    AETHERFLOW_PLUGIN_PATHS

Value:
- comma-separated list of filesystem paths

Example:

    export AETHERFLOW_PLUGIN_PATHS="/tmp/plugins,./vendor/plugins"

Each path is imported as a Python module root.
All modules inside that path that execute registration logic will register steps/connectors.

---

# 3) Recommended Folder Structures

Two common patterns.

---

## 3.1 Simple Folder (Internal Project)

For internal use:

    project-root/
      plugins/
        my_steps.py
        my_connectors.py

Set:

    export AETHERFLOW_PLUGIN_PATHS="/tmp/plugins"

Example my_steps.py:

    from aetherflow.core.api import register_step, Step, StepResult, STEP_SUCCESS

    @register_step("my_step")
    class MyStep(Step):
        def run(self, ctx, inputs):
            return StepResult(status=STEP_SUCCESS, outputs={"ok": True})

This is the simplest setup.

---

## 3.2 Proper Python Package (Recommended)

For production-grade plugins:

    my-org-aetherflow-plugin/
      pyproject.toml
      src/
        my_org_aetherflow_plugin/
          __init__.py
          steps.py
          connectors.py

Install:

    pip install my-org-aetherflow-plugin

Then expose its module directory via:

    export AETHERFLOW_PLUGIN_PATHS="/path/to/site-packages/my_org_aetherflow_plugin"

Inside __init__.py:

    from .steps import *
    from .connectors import *

Registration must happen at import time.

---

# 4) Registering a Step

Minimal template:

    from aetherflow.core.api import register_step, Step, StepResult, STEP_SUCCESS, STEP_SKIPPED

    @register_step("my_step")
    class MyStep(Step):
        def run(self, ctx, inputs):
            # ctx.env -> immutable environment snapshot
            # ctx.connectors -> resolved connectors

            value = inputs.get("value")

            if not value:
                return StepResult(status=STEP_SKIPPED, outputs={"reason": "empty"})

            # deterministic work here
            return StepResult(status=STEP_SUCCESS, outputs={"echo": value})

Step constraints:

- must be idempotent or resume-friendly
- must not mutate os.environ
- must not rely on global mutable state
- must write outputs atomically
- must treat SKIPPED as valid outcome when appropriate

See:
20-steps.md
03-execution-model.md

---

# 5) Registering a Connector

Minimal template:

    from aetherflow.core.api import register_connector, ConnectorBase

    @register_connector(kind="db", driver="mydb")
    class MyDbConnector(ConnectorBase):
        def __init__(self, *, config, options):
            self.config = config
            self.options = options
            self._client = None

        def connect(self):
            if self._client is None:
                self._client = self._create_client()
            return self._client

        def _create_client(self):
            # use resolved config/options only
            ...

Connector rules:

- thin wrapper around a driver
- no orchestration logic inside connector
- no global singletons unless you accept process-wide coupling
- do not read os.environ directly

See:
19-connectors.md
09-profiles-and-resources.md

---

# 6) Strictness

    AETHERFLOW_PLUGIN_STRICT=true   (default)

If true:
- plugin import/registration errors fail the run immediately

Keep strict mode enabled in production.

---

# 7) Enterprise vs internal_fast

Mode affects plugin trust.

internal_fast:
- may inherit ambient AETHERFLOW_PLUGIN_PATHS
- may map bundle plugins_dir into plugin paths

enterprise:
- strips inherited plugin paths
- only allows trusted manifest paths.plugins
- reduces attack surface

See:
08-manifest-and-bundles.md
11-envs.md

---

# 8) Do Not Break the Contract

Do NOT:

- import internal modules
- mutate os.environ
- bypass the resolver pipeline
- hide shared side effects without locks

If your step writes to shared targets:
- require with_lock
- document the lock key contract

See:
05-locking-guide.md

---

# 9) Testing Your Plugin

1. Install plugin (editable or package).
2. Set AETHERFLOW_PLUGIN_PATHS.
3. Write minimal flow YAML using your step.
4. Run:

   aetherflow validate flow.yaml
   aetherflow run flow.yaml

Fix validation errors first. Then fix runtime logic.

---

# 10) Design Philosophy

Plugins are extension points, not forks.

Good plugins:

- respect public API boundary
- remain deterministic
- keep side effects explicit
- survive core upgrades

Core is stable.
Internals are not.
Respect the boundary.
