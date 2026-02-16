# 08 — Manifests & Bundles

Source:
- aetherflow.core.bundles
- Bundle integration in aetherflow.core.runner via --bundle-manifest
- Schema: BundleManifestSpec in aetherflow.core.spec

A bundle is AetherFlow’s reproducibility mechanism.

It allows you to:
- Sync assets from a remote source into a local cache
- Run flows with deterministic inputs
- Separate “source of truth” from the local disk

---

## 1) Why Bundles Exist

Bundles solve three production problems:

1. Asset synchronization  
   Flows, profiles, plugins, env files are synced into a controlled local cache.

2. Reproducibility  
   The run uses a fingerprinted, cached copy of inputs.

3. Isolation  
   Local disk is not treated as authoritative source of configuration.

---

## 2) How You Use a Bundle

Explicit sync:

aetherflow bundle sync --bundle-manifest bundle.yaml --print-local-root

Run with bundle:

aetherflow run flow.yaml --bundle-manifest bundle.yaml

Behavior:

- bundle sync pulls remote assets into local cache
- run --bundle-manifest ensures sync before execution
- runner activates a deterministic local bundle root

---

## 3) Manifest as the Contract

The manifest defines:

- mode (enterprise or internal_fast)
- bundle source (where assets come from)
- layout (how assets are structured locally)
- trusted plugin paths (mode: enterprise)
- trusted zip drivers (mode: enterprise)
- env_files

Schema is defined in BundleManifestSpec (aetherflow.core.spec).

If documentation and spec.py disagree, spec.py is authoritative.

---

## 4) Conceptual Manifest Structure

Exact fields are defined in BundleManifestSpec. Conceptually:

```yaml
version: 1
mode: enterprise | internal_fast

bundle:
  source:
    type: local                         # local | git | archive
    location: "..."
  layout:
    flows: "flows/"
    profiles: "profiles.yaml"
    plugins: "plugins/"
  entry_flow: flows/demo_local.yaml
  fetch_policy: cache_check

resources:
   
paths:                                  # mode: enterprise
  plugins: "..."

zip_drivers:                            # mode: enterprise - pyzipper| zipfile| os | external (Set rules, no order)
   - "pyzipper"
   - "zipfile" 
     
env_files:
   - "env/common.env"
   - "env/prod.env"

```

Additional fields may exist depending on implementation (e.g. entry_flow, resource mappings).

---

## 5) Fingerprinting & Cache

The core builds a fingerprint using RemoteFileMeta.

Priority:
1. sha256 (if provided by remote)
2. fallback: (rel_path, size, mtime)

This ensures:

- Deterministic runs
- Efficient incremental sync
- Traceable inputs for debugging

Bundles are cached under the configured work root.  
An “active bundle” directory is managed internally by the core.

---

## 6) Deterministic Wiring During Run

When a bundle is active, the runner rewires execution:

- Flow YAML may map to bundle.entry_flow (if defined)
- Profiles file is wired into AETHERFLOW_PROFILES_FILE
- Plugin directory may be mapped into AETHERFLOW_PLUGIN_PATHS (mode-dependent)
- Zip drivers (mode-dependent)
- Env files are loaded relative to the active bundle root

This guarantees that execution uses only the synced bundle content.

---

## 7) Enterprise vs internal_fast

mode controls runtime security behavior.

### internal_fast

- May map bundle plugins into AETHERFLOW_PLUGIN_PATHS
- More permissive for local/dev usage
- Intended for internal teams with trusted environments

### enterprise

- Denies inheriting plugin paths from ambient OS environment
- Only trusted paths.plugins from manifest are used
- Archive driver allowlists (trusted zip drivers) enforced in validation
- Designed for strict, auditable environments

Enterprise policies are enforced in aetherflow.core.validation.

---

## 8) Operational Guidance

- Version-control your bundle manifests
- Sync bundles in CI before deploy
- Prefer enterprise mode in shared or multi-tenant environments
- Do not rely on ambient env files or plugin paths
- Use strict templating in production

---

## 9) Related Documents

- 06-yaml-spec.md — BundleManifestSpec details
- 11-envs.md — environment snapshot & mode behavior
- 18-plugins.md — plugin loading rules
- 99-strict-templating.md — resolution contract
