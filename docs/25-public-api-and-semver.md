# 25 — Public API & SemVer (Backend Format)

This page defines:
- what is considered **Public API**
- what is **internal**
- how versioning and deprecation are handled

Source reviewed from repository layout:
- `aetherflow.core.api` (public registry surface)
- `aetherflow.core.builtins.*`
- runner, connectors, steps implementation modules

---

# Public API Boundary

## The Only Stable Import Surface

If you are:
- writing a plugin
- embedding AetherFlow inside another Python app
- building tooling on top of AetherFlow

You must import exclusively from:

```python
from aetherflow.core.api import ...
````

Examples:

```python
from aetherflow.core.api import (
    list_steps,
    list_connectors,
    register_step,
    register_connector,
)
```

This module defines the stable extension boundary.

---

## Everything Else Is Internal

Anything outside `aetherflow.core.api` is considered internal implementation.

Examples of internal modules:

```text
aetherflow.core.builtins.*
aetherflow.core.runner.*
aetherflow.core.state.*
aetherflow.core.templating.*
aetherflow.core.execution.*
```

Internal modules:

* may change structure
* may refactor classes
* may rename functions
* may change constructor signatures
* may reorganize files

These changes are allowed in minor releases.

If you import from internal modules, you accept break risk.

---

# What Is Guaranteed Stable?

Within `aetherflow.core.api`:

* step and connector registration functions
* runtime discovery (`list_steps`, `list_connectors`)
* stable base classes exposed intentionally (if exported there)
* documented extension contracts

The rule is simple:

If it is not exported through `aetherflow.core.api`, it is not public.

---

# Deprecation Policy (Practical)

## Internal Changes

Allowed in:

* Patch releases
* Minor releases

No deprecation ceremony required.

---

## Public API Changes

If a change affects `aetherflow.core.api` surface:

1. Add deprecation warning.
2. Document it clearly.
3. Keep backward compatibility for at least one minor release.
4. Remove only in next major release.

Example pattern:

```python
import warnings

def old_function(...):
    warnings.warn(
        "old_function is deprecated and will be removed in v3.0",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_function(...)
```

---

# Semantic Versioning Rules

AetherFlow follows SemVer:

`MAJOR.MINOR.PATCH`

---

## PATCH (x.y.Z)

Allowed:

* bug fixes
* performance improvements
* internal refactors
* logging improvements
* test fixes

Not allowed:

* public API signature changes
* behavior changes of documented public contracts

Patch must not break public integrations.

---

## MINOR (x.Y.z)

Allowed:

* new backward-compatible features
* new built-in steps/connectors
* new optional inputs with safe defaults
* internal refactors
* performance changes

Not allowed:

* breaking public API
* changing behavior in a way that violates documented contracts

Minor must remain backward-compatible for public API consumers.

---

## MAJOR (X.y.z)

Required when:

* breaking change to `aetherflow.core.api`
* change to extension contract (plugin API)
* change to public step/connector interface contract
* removal of previously deprecated public API

Major version is the only place where breaking public API is allowed.

---

# Builtins and Public API

Important distinction:

Built-in steps/connectors are part of runtime registry,
but their internal class implementations are not public API.

What is public:

* Their registered names
* Their YAML schema (documented contract)
* Their behavior as documented

What is not public:

* Their internal class structure
* Their private helper functions
* Their module path

---

# Extension Author Guidance

If you build a plugin:

Do:

```python
from aetherflow.core.api import register_step

@register_step("my.custom_step")
class MyStep:
    ...
```

Do not:

```python
from aetherflow.core.runner.execution import StepContext
```

Unless explicitly exported in `core.api`.

---

# Stability Contract Summary

Public API = only what is exported via:

```python
aetherflow.core.api
```

Everything else:

* implementation detail
* subject to refactor
* not covered by backward compatibility guarantees

SemVer enforcement:

* Patch = safe bugfix
* Minor = backward-compatible feature
* Major = breaking public contract

If you treat `core.api` as the only boundary, you will not get surprised by upgrades.

