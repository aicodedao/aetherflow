# 16 — Observability (Logging, Metrics, Failure Snapshots)

Source of truth:
- `aetherflow.core.observability`
- settings integration: `aetherflow.core.runtime.settings`
- step execution boundaries: `aetherflow.core.runner` and built-in steps (for failure context)

This document defines AetherFlow’s observability contract:
- how logs are emitted
- which fields are guaranteed
- how correlation works
- how run/job/step summaries are produced
- how metrics hooks are plugged in
- what AetherFlow considers a failure

---

## 1) Logging Contract

AetherFlow emits structured event logs using the same primitive everywhere:

log_event(logger, settings, level, event, **fields)

Key properties:
- One log line per event
- Events carry explicit fields rather than relying on free-form text
- Formatting is controlled by settings (text vs JSON)

### 1.1 Text format (default)

Text format is optimized for humans.

One event per line:

<event> key=value key=value ...

Example shape (illustrative):

run_start flow_id=demo run_id=... mode=internal_fast

### 1.2 JSON format

Enable:

AETHERFLOW_LOG_FORMAT=json

In JSON mode, each log line is a single JSON object.

Minimum fields:
- ts_ms
- event

Plus any additional fields passed to `log_event(...)`.

This format is designed for:
- log shipping (ELK / Loki / Datadog / Splunk)
- structured queries
- building dashboards without parsing arbitrary text

---

## 2) Correlation and Required IDs

AetherFlow’s observer always attaches correlation fields.

### 2.1 Run-level correlation

Every run-scoped event includes:
- flow_id
- run_id

### 2.2 Job-level correlation

Within a job, events include:
- job_id

### 2.3 Step-level correlation

Within a step, events include:
- step_id
- step_type

This allows you to:
- filter logs for a single run
- isolate a single job
- trace failures to a single step

Best practice:
- treat (flow_id, run_id) as your primary correlation key
- treat (job_id, step_id) as secondary keys

---

## 3) RunObserver and Summary Events

AetherFlow uses a `RunObserver` to collect execution timings and status counts.

It tracks:
- run_start / run_end
- job_start / job_end
- step_start / step_end

At the end of a run, it emits a summary event including:

- duration_ms
- status_counts (jobs and/or steps)
- per-job summaries
- per-step durations (if enabled/collected)

The goal:
- a run’s health can be understood from a small number of structured events
- detailed logs remain available, but summary gives fast signal

---

## 4) Failure Snapshots (What You Can Expect)

AetherFlow’s contract is:
- failures must be visible
- failures must be attributable to a specific boundary (validation / resolution / step execution)
- failures must contain correlation fields (flow_id/run_id/job_id/step_id where applicable)

When failures occur, the observer emits events that allow:

- locating the failing step
- identifying what phase failed (validate vs resolve vs execute)
- measuring time-to-failure

Implementation details of “artifact snapshot layout” live across runner/workspace logic, but observability guarantees that the failure is logged as an event with context fields.

---

## 5) Metrics Hook (Optional)

AetherFlow supports a plug-in metrics sink.

Configure:

AETHERFLOW_METRICS_MODULE=<module>

The module must expose:

METRICS: MetricsSink

The sink receives lifecycle callbacks:

- on_run_start / on_run_end
- on_job_start / on_job_end
- on_step_start / on_step_end

This allows teams to emit metrics to:
- Prometheus
- StatsD
- OpenTelemetry bridges
- custom internal collectors

The metrics hook is intentionally minimal:
- no forced dependency
- no global metric implementation baked into core

---

## 6) What Counts as Failure?

AetherFlow distinguishes between:
- “valid outcomes” like SKIPPED
- failures that should stop or fail the run

### 6.1 Execution failures

If an exception occurs during step execution:

- step fails
- job becomes FAILED
- the failure propagates to the run

This is the most common operational failure type.

### 6.2 Spec validation failures (fail fast)

If schema/spec validation fails (Pydantic or semantic validation):

- run fails before execution begins
- error is raised as a spec/validation error

These failures are “configuration correctness” failures.

### 6.3 Resolution failures (strict templating)

If strict templating is enabled (default):

- invalid template syntax → ResolverSyntaxError
- missing variable → ResolverMissingKeyError (or equivalent)

These are deterministic, fail-fast errors.

They are not runtime “flakiness”; they are contract violations.

---

## 7) Recommended Operational Practices

1) Use JSON log format in production
    - AETHERFLOW_LOG_FORMAT=json
    - makes dashboards and queries sane

2) Always track flow_id + run_id
    - treat as correlation ID
    - propagate into external processes when needed

3) Keep SKIPPED as signal, not noise
    - SKIPPED is a valid outcome (no data, gating false)
    - do not alert on SKIPPED by default

4) Alert on:
    - FAILED runs
    - repeated validation failures
    - repeated resolution failures

5) Use metrics hook for durable operational SLOs
    - count runs, failures, durations
    - per job/step timing percentiles

---

## 8) Summary

Observability in AetherFlow is built on a boring contract:

- event logs are structured
- correlation is always present
- summaries exist for quick signal
- metrics are pluggable
- failures are explicit and attributable

This keeps the core small while allowing production-grade monitoring.
