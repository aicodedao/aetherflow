# 23 — Builtins Catalog (Backend Format)
Single Source of Truth

Source reviewed from:
- packages/aetherflow-core/src/aetherflow/core/builtins/connectors.py
- packages/aetherflow-core/src/aetherflow/core/builtins/steps.py

If it’s not in those files, it is not a builtin.

---

## Runtime Introspection

Always trust runtime over docs.

```python
from aetherflow.core.api import list_steps, list_connectors

print(list_steps())
print(list_connectors())
````

---

## Contract Guarantee

Public runtime registry:

* list_steps()
* list_connectors()

Everything else is internal.

This document reflects exactly what ships in builtins today.

---

# Built-in Connectors (Core)

This document describes the built-in connectors shipped with **aetherflow-core**.

AetherFlow connectors are lightweight client wrappers created from a `resource` definition.
They expose small, explicit primitives that steps can call (read/write/list/execute/etc.).

> Rule of thumb: built-in connectors should be **boring**, **predictable**, **thin**, and **safe-by-default**.
> If you need complex orchestration, use steps or `external.process`.

---

## 1) Resource model refresher

A connector instance is created from a resource entry:

- `kind`: connector category (e.g. `db`, `sftp`, `archive`)
- `driver`: concrete implementation (e.g. `sqlite3`, `paramiko`, `pyzipper`)
- `config`: connection credentials / endpoints
- `options`: operational behavior (timeouts, retries, pool sizes, etc.)

Example (illustrative YAML):

```yaml
resources:
  - id: api
    kind: rest
    driver: httpx
    config:
      base_url: "https://example.com"
      headers:
        X-App: "aetherflow"
      bearer_token: "{{secrets.api_token}}"
    options:
      timeout: 30
      retry:
        max_attempts: 3
````

---

## 2) Connector lifecycle

All built-in connectors implement a small lifecycle pattern:

* They are context-manager friendly (`__enter__` / `__exit__`)
* They provide a `close()` method
* `close()` is best-effort: failures are logged as warnings and do not crash the run

This allows steps to safely use connectors without leaking sessions or sockets.

---

## 3) REST connector: `rest:httpx` (HttpxREST)

**Driver:** `httpx` (optional dependency)

### Purpose

A thin wrapper around `httpx.Client` / `httpx.AsyncClient` providing:

* consistent client initialization
* default base URL + headers
* predictable timeout behavior
* optional retry support

### Resource config

`resource.config` keys:

* `base_url` (string, optional)

    * Base URL used by the client. Trailing `/` is stripped.
* `headers` (dict, optional)

    * Default headers merged into all requests.
* `bearer_token` (string, optional)

    * If present, injects `Authorization: Bearer <token>` unless already provided.

### Resource options

`resource.options` keys:

* `timeout` (seconds, default 30)

    * Alias: `timeouts.total`
* `verify_ssl` (bool, default true)
* `retry.max_attempts` (int, default 0)

    * `0` means no retry loop.

### Primary API

* `client()` → sync `httpx.Client`
* `async_client()` → async `httpx.AsyncClient`
* `request(method, url, ...)` → sync request primitive
* Convenience methods:

    * `get(url, **kw)`
    * `post(url, **kw)`
    * `put(url, **kw)`
    * `delete(url, **kw)`

### Retry behavior

If retries are enabled:

* Prefer `tenacity` if installed (exponential backoff)
* Otherwise fall back to a small built-in loop (sleep up to 5s)

Only `httpx.HTTPError`-style failures are retried.

### Notes

* `close()` attempts to close both sync and async clients.

    * Async close is best-effort (may use `anyio.run` internally).
    * In event-loop heavy apps, prefer managing async lifecycle explicitly.

---

## 4) Mail connector: `mail:smtp` (SMTPMail)

**Driver:** stdlib `smtplib`

### Purpose

Send email via SMTP using predictable primitives.

### Resource config

* `host` (required)
* `port` (default 587)
* `username` (optional)
* `password` (optional)
* `starttls` (optional)

    * If not set: defaults to `true` when `port == 587`
* `from_addr` (optional)

    * Defaults to `username` if present

### Resource options

* `timeout` (seconds, default 30)
* `retry.max_attempts` (default 1)

### Primary API

* `client()` → connected SMTP client (login performed if configured)
* `send_plaintext(to, subject, body, from_addr=None, cc=None, bcc=None)`
* `send_html(to, subject, html, text=None, from_addr=None, cc=None, bcc=None)`

### Recipient behavior

* `To` and `Cc` are set as headers
* `Bcc` is **not** added as a header, but its addresses are still used as recipients
* The connector builds the full recipient list as:
  `to + cc + bcc`

### Retry behavior

On send failure:

* resets the SMTP client (close + reconnect)
* retries with exponential-ish backoff (capped)

---

## 5) SFTP connector: `sftp:paramiko` (ParamikoSFTP)

**Driver:** `paramiko` (optional dependency)

### Purpose

Provide SFTP filesystem operations:

* read/write file bytes
* upload/download local files
* list directory metadata
* delete paths
* mkdir helpers (including recursive mkdir)
* best-effort recursive delete

### Resource config

* `host` (required)
* `port` (default 22)
* `user` (required)
* `password` (optional)
* `pkey_path` (optional)

    * RSA private key path (if set, used instead of password)

### Resource options

* `timeout` (seconds, default 30)

### Primary API

* `session()` → context manager yielding `paramiko.SFTPClient`
* `read_bytes(remote_path) -> bytes`
* `write_bytes(remote_path, data)`
* `download(remote_path, local_path)`
* `upload(local_path, remote_path)`
* `list(remote_dir) -> list[RemoteFileMeta]`
* `delete(remote_path)` (tries file remove, then dir rmdir)
* `mkdir(remote_dir)`

### Helpers

* `mkdir_recursive(remote_dir)`

    * Creates intermediate directories (best-effort; ignores already-exists failures)
* `delete_recursive(remote_path)`

    * Best-effort recursion via listdir + remove/rmdir

### RemoteFileMeta returned by `list()`

Each entry includes:

* `path`
* `name`
* `is_dir`
* `size` (files only)
* `mtime` (unix seconds)

---

## 6) Database connectors

AetherFlow ships multiple DB connectors. They share an intent:

* Provide small primitives (`execute`, `read`, `fetchall`, `fetchmany`)
* Keep metadata inference conservative
* Avoid forcing heavy deps when not needed

### 6.1) `db:sqlalchemy` (SQLAlchemyDB)

**Driver:** `sqlalchemy` (optional dependency)

#### Config

* `url` (required) SQLAlchemy URL string

#### Options

Pooling configuration:

* `pool.size` (default 5)
* `pool.max_overflow` (default 10)
* `pool.recycle_seconds` (default 1800)
* `pool.pre_ping` (default true)
* `connect_args` (dict, optional)

Legacy flat aliases may also be accepted:

* `pool_size`, `max_overflow`, `pool_recycle`, `pool_pre_ping`

#### API

* `engine()` → creates / caches SQLAlchemy engine
* `connect()` → context manager using `engine.begin()` (transaction-aware)
* `execute(sql, params=None) -> int`
* `read(sql, params=None) -> (cols, rows)`
* `fetchall(...)` alias of `read(...)`
* `fetchmany(sql, params, fetch_size, sample_size=200)`

    * returns `(cols, iterator[tuple], pytypes[list[type]])`

> Note: SQLAlchemy type metadata is inconsistent across drivers, so `fetchmany`
> uses sampling to infer reasonable python types when needed.

### 6.2) `db:sqlite3` (SQLiteDB)

**Driver:** stdlib `sqlite3`

#### Config

* `path` (preferred) OR
* `url` using `sqlite:///...`
* supports `:memory:` via `sqlite:///:memory:` or `:memory:`

#### API

* `connect()`
* `read(sql, params=None)`
* `fetchall(...)`
* `fetchmany(sql, params, fetch_size, sample_size=200)`

    * returns `(cols, iterator, pytypes)`

`fetchmany` reads cursor.description when possible, otherwise samples to infer types.

### 6.3) `db:duckdb` (DuckDB)

**Driver:** `duckdb` (optional dependency)

#### Config

* `path` (default `:memory:`)
* `read_only` (bool, default false)

#### Options

* `extensions` (list[str])

    * best-effort `INSTALL` + `LOAD`
* `pragmas` (dict)

    * best-effort `PRAGMA key=value`

#### API

* `connect()` caches a single connection
* `close()` closes cached connection
* `execute`, `read`, `fetchall` similar to sqlite-style behavior

### 6.4) Aliases

* `db:postgres` → alias of `SQLAlchemyDB` (use postgres URL)
* `db:mysql` → alias of `SQLAlchemyDB` (use mysql URL)

### 6.5) `db:oracledb` (OracleDB)

**Driver:** `python-oracledb` (optional dependency)

#### Config

* `user` (required)
* `password` (required)
* `dsn` (required)

#### Options

* `oracle.lib_dir` or `lib_dir`

    * passed to `oracledb.init_oracle_client` (best-effort)
* pooling:

    * `pool.enabled` (default true)
    * `pool.size` (default 4)
    * legacy: `pool_enabled`, `pool_size`
* `arraysize` (default 5000)

#### API

* `connect()` context manager

    * pooled if enabled, otherwise direct connection
* `execute()` commits best-effort
* `read()` uses cursor arraysize
* `fetchall(...)` alias of `read(...)`

### 6.6) `db:exasol` (ExasolDB)

**Driver:** `pyexasol` (optional dependency)

#### Notes

`pyexasol` is not strictly DB-API. This connector provides a consistent API by:

* using `conn.execute()` which returns a statement
* extracting columns from statement metadata where possible
* supporting `fetchall` and a unified `fetchmany` interface

#### Config

* `dsn` (required)
* `user` (required)
* `password` (required)
* `schema` (optional)

#### Options

* `timeout` (optional)

#### API

* `connect_raw()` caches a pyexasol connection
* `execute(sql, params=None) -> int`
* `read(sql, params=None) -> (cols, rows)`
* `fetchall(...)`
* `fetchmany(sql, params, fetch_size, sample_size=200) -> (cols, iterator, pytypes)`

If column names are not available, synthetic names `col_1..col_N` may be used.

---

## 7) SMB connectors (Windows shares)

AetherFlow provides two SMB drivers:

* `smb:smbclient` using `python-smbclient`
* `smb:pysmb` using `pysmb`

Choose one based on environment compatibility.

### 7.1) `smb:smbclient` (SMBClient)

**Driver:** `python-smbclient` (optional dependency)

#### Config

* `server` (required)
* `share` (optional default share)
* `username` / `user` (optional)
* `password` (optional)
* `port` (default 445)

#### Options

* `timeout` (default 30)

#### Path formats accepted

The connector normalizes multiple input path formats:

* Relative path inside share: `"dir/file.txt"`
* Absolute-ish inside share: `"/dir/file.txt"` or `"\\dir\\file.txt"`
* UNC full path: `"\\\\server\\share\\dir\\file.txt"` (passed through)
* Share override: `"SHARE:/dir/file.txt"` or `"SHARE:\\dir\\file.txt"`
* Windows drive path: `"C:\\dir\\file.txt"` (drive stripped; uses `config.share`)

If no share is available (neither `config.share` nor share override), operations fail.

#### API

* `read_bytes(remote_path)`
* `write_bytes(remote_path, data)`
* `upload(local_path, remote_path)`
* `download(remote_path, local_path)`
* `list(remote_dir) -> list[RemoteFileMeta]`
* `delete(remote_path)` (remove then rmdir)
* `mkdir(remote_dir)`
* `mkdir_recursive(remote_dir)`
* `delete_recursive(remote_path)`

### 7.2) `smb:pysmb` (SMBPySMB)

**Driver:** `pysmb` (optional dependency)

#### Config

* `server` (required)
* `server_name` (optional NetBIOS name; default `server`)
* `share` (optional default share)
* `username` / `user` (optional)
* `password` (optional)
* `domain` (optional)
* `port` (default 445)
* `client_name` (optional; default `"aetherflow"`)

#### Path formats accepted

Similar to smbclient driver, but internally it splits into:

* `(share, path_in_share)`

Supported:

* `"dir/file.txt"` / `"/dir/file.txt"` → uses `config.share`
* `"SHARE:/dir/file.txt"` overrides share
* `"C:\\dir\\file.txt"` drive stripped
* UNC: `"\\\\host\\SHARE\\dir\\file.txt"` share inferred when not set

#### API

* `read_bytes`
* `write_bytes`
* `upload`
* `download`
* `list`
* `delete`
* `mkdir`
* `mkdir_recursive`
* `delete_recursive`

---

## 8) Archive connectors (zip/unzip)

Archive connectors provide a unified interface:

* `create_zip(output, files, base_dir, password=None, compression="deflated", overwrite=True)`
* `extract_zip(archive, dest_dir, password=None, overwrite=True, members=None)`

### Safety note: base_dir boundary

When creating archives, file paths are validated to ensure every file is inside `base_dir`.
This prevents accidental inclusion of files outside the intended directory.

### 8.1) `archive:pyzipper` (PyZipperArchive)

**Driver:** `pyzipper` (optional dependency)

#### Supports

* create encrypted ZIPs using AES (when password provided)
* extract encrypted ZIPs

#### Config

* `encryption`: `"aes"` (default `"aes"`)

    * ZipCrypto is not supported for creating archives
* `aes_strength`: `128|192|256` (default 256)

#### Notes

If you need ZipCrypto for creation, use `archive:pyminizip` or OS/external tools.

### 8.2) `archive:zipfile` (StdZipfileArchive)

**Driver:** Python stdlib `zipfile`

#### Supports

* create ZIPs without encryption
* extract ZIPs, including ZipCrypto-encrypted archives (if password provided)

#### Limitations

* Cannot write encrypted ZIPs.

### 8.3) `archive:os` (OsZipArchive)

**Driver:** OS `zip` + `unzip` commands

#### Config

* `zip_cmd` (default `"zip"`)
* `unzip_cmd` (default `"unzip"`)
* `quiet` (default true)

#### Notes

* Password uses `zip -P` (ZipCrypto legacy).
* Requires tools to exist on `PATH`.

### 8.4) `archive:pyminizip` (PyMiniZipArchive)

**Driver:** `pyminizip` (optional dependency)

#### Supports

* create ZipCrypto encrypted ZIPs

#### Limitations

* Does **not** support extraction.

Use `archive:pyzipper`, `archive:os`, or `archive:external` to unzip.

### 8.5) `archive:external` (ExternalArchive)

**Driver:** external command runner (e.g. 7z / bsdtar)

#### Config

* `zip_cmd`: list[str] template
* `unzip_cmd`: list[str] template

#### Template variables

* `{archive}`: output archive path (or input archive for unzip)
* `{dest}`: destination directory (unzip only)
* `{password}`: password string (empty if none)
* `{base_dir}`: base directory path (zip only)
* `{files}`: placeholder expanded into the file list (already relative POSIX paths)

#### Example (7z)

```yaml
resources:
  - id: z
    kind: archive
    driver: external
    config:
      zip_cmd: ["7z", "a", "-tzip", "{archive}", "{files}"]
      unzip_cmd: ["7z", "x", "-y", "-o{dest}", "{archive}"]
```

#### Limitations

* `members` extraction is not supported in this driver (fails fast if provided).

---

## 9) RemoteFileMeta shape

Connectors that list remote directories return `RemoteFileMeta` objects.

Typical fields used:

* `path`: full path as understood by the connector
* `name`: entry name
* `is_dir`: bool
* `size`: file size or `None` for directories
* `mtime`: unix timestamp seconds or `None`

---

## 10) Optional dependencies matrix

Some built-in connectors require optional installs:

* `rest:httpx` → `httpx` (and optionally `tenacity`)
* `sftp:paramiko` → `paramiko`
* `db:sqlalchemy` → `sqlalchemy`
* `db:duckdb` → `duckdb`
* `db:oracledb` → `python-oracledb`
* `db:exasol` → `pyexasol`
* `smb:smbclient` → `python-smbclient` (import name: `smbclient`)
* `smb:pysmb` → `pysmb`
* `archive:pyzipper` → `pyzipper`
* `archive:pyminizip` → `pyminizip`

If a dependency is missing, the connector raises a `ConnectorError` explaining what to install.

---

## 11) Design constraints (what we intentionally do NOT support)

* No “magical” auto-retry everywhere (only where explicitly specified)
* No implicit concurrency
* No hidden credential discovery
* No opinionated schema inference beyond conservative sampling in `fetchmany`
* Archive creation does not allow escaping `base_dir`

---

# Built-in Steps (Canonical)

This document is generated from the **actual built-in step implementations** you pasted (the `@register_step(...)` classes in `aetherflow.core.builtin.steps`).

It covers:

- Database export steps: `db_extract`, `db_fetch_small`, `db_extract_stream`
- Excel steps: `excel_validate_template`, `excel_fill_small`, `excel_fill_from_file`
- Concurrency / gating: `with_lock`, `check_items`
- File transfer: SMB (`smb_*`) and SFTP (`sftp_*`)
- Email: `mail_send`
- External execution: `external.process`
- Archiving: `zip`, `unzip`

---

## How steps are referenced in YAML

```yaml
type: step_name
inputs:
  ...
````

Notes:

* Steps validate `required_inputs` and raise on missing required fields.
* Some steps return a `StepResult` with `status`:

    * `STEP_SUCCESS`
    * `STEP_SKIPPED`
* Others return a plain dictionary output.
* Paths passed to steps are often resolved through a sandbox resolver:

    * relative paths are resolved under the job artifacts directory
    * in enterprise mode, paths are restricted more aggressively

---

# 1) Database Steps

## db_extract

### Purpose

Run a query and write the full result set to a file in the job artifacts area.

### Required Inputs

* `resource` (string) — DB connector resource name
* `sql` (string) — query text
* `output` (string) — output file path

### Optional Inputs

* `params` (object | null) — query parameters passed to the connector
* `format` (string, default `"tsv"`) — output format:

    * `tsv`
    * `jsonl`

### Outputs

* `output` (string) — resolved artifact path
* `format` (string)
* `rows` (int) — number of rows written

### Behavior

* Writes to a temporary file (`.tmp`) and then atomically replaces the target (`os.replace`).
* `tsv` output:

    * header line with column names (if any)
    * rows written with tab delimiter
* `jsonl` output:

    * one JSON object per row, keyed by column names
* Any other `format` raises `ValueError("Unsupported format: ...")`.

### Example

```yaml
- id: export_users
  type: db_extract
  inputs:
    resource: db_main
    sql: "select * from users where active = 1"
    output: exports/users.tsv
    format: tsv
```

---

## db_fetch_small

### Purpose

Fetch a **bounded** result set into memory (guarded). Intended for small datasets and chaining into steps that accept JSON strings.

### Required Inputs

* `resource` (string)
* `sql` (string)

### Optional Inputs

* `params` (object | null)
* `max_rows` (int, default `50000`)
* `fetch_size` (int, default `5000`)

### Outputs

* `columns` (array[string])
* `rows` (array[array]) — raw in-memory rows (Python values)
* `row_count` (int)
* `columns_json` (string) — JSON encoded list of columns
* `rows_json` (string) — JSON encoded rows (JSON-safe conversions applied)
* `dtypes` (object) — mapping column -> inferred dtype string
* `dtypes_json` (string)

Supported dtype labels emitted:

* `bool`
* `int`
* `float` (includes `Decimal` downgraded to float)
* `date`
* `datetime`
* `string`

### Behavior

* Requires the DB connector to implement `fetchmany(sql, params, fetch_size, sample_size)`; otherwise raises `ConnectorError`.

* Iterates the connector iterator; if `count > max_rows`, raises:

  `ValueError("db_fetch_small exceeded max_rows=... Use db_extract_stream for large results.")`

* `rows_json` converts non-JSON-safe types:

    * `Decimal` -> float
    * date/datetime -> ISO string

### Example

```yaml
- id: fetch_top
  type: db_fetch_small
  inputs:
    resource: db_main
    sql: "select id, email from users order by created_at desc limit 1000"
    max_rows: 5000
    fetch_size: 2000
```

---

## db_extract_stream

### Purpose

Stream a DB query to a file without loading everything into memory.

### Required Inputs

* `resource` (string)
* `sql` (string)
* `output` (string)

### Optional Inputs

* `params` (object | null)
* `format` (string, default `"tsv"`) — supported:

    * `tsv`
    * `csv`
    * `parquet`
* `fetch_size` (int, default `5000`) — also used as the parquet write batch size
* `include_header` (bool, default `true`) — applies to `csv/tsv`
* `emit_dtypes` (bool, default `false`)
* `dtypes` / `dtypes_json` (object | string) — optional dict mapping column -> dtype (for parquet typing)
* `file` (object) or top-level file options (for `csv/tsv`):

    * `encoding` (default `"utf-8"`)
    * `delimiter` (default `"\t"` for tsv, `","` for csv)
    * `quotechar` (default `"`)
    * `escapechar` (default null)
    * `doublequote` (default `true`)
    * `quoting` (default `"minimal"`)
    * `linefeed` (default `"\n"`)

### Outputs

* `artifact_path` (string)
* `format` (string)
* `columns` (array[string])
* `row_count` (int)
* `sha256` (string)
* When `emit_dtypes=true` and dtypes exist:

    * `dtypes` (object)
    * `dtypes_json` (string)

### Behavior

* Requires connector `fetchmany()` support (same as `db_fetch_small`).

* Writes to `.tmp` then atomically replaces.

* Computes SHA256 of the final output file.

* Parquet support requires optional dependency `pyarrow`:

  If missing: raises ValueError instructing to install `aetherflow-core[parquet]`.

* Parquet types:

    * `int` -> int64
    * `float` -> float64
    * `bool` -> bool
    * `date` -> date32
    * `datetime` -> timestamp(ms)
    * default -> string

### Example (CSV)

```yaml
- id: export_csv
  type: db_extract_stream
  inputs:
    resource: db_main
    sql: "select * from events"
    output: exports/events.csv
    format: csv
    include_header: true
    fetch_size: 10000
    file:
      encoding: utf-8
      delimiter: ","
```

### Example (Parquet)

```yaml
- id: export_parquet
  type: db_extract_stream
  inputs:
    resource: db_main
    sql: "select id, amount, created_at from payments"
    output: exports/payments.parquet
    format: parquet
    emit_dtypes: true
```

---

# 2) Excel Steps

## excel_validate_template

### Purpose

Validate that an Excel template contains required named ranges or anchor text cells.

### Required Inputs

* `template_path` (string)
* `required_names` (array[string] | string)

### Optional Inputs

* `sheet` (string) — limit anchor text search to one sheet (otherwise scans all sheets)

### Outputs

* `template_ok` (bool)
* `found_named_ranges` (array[string])
* `found_anchor_cells` (array[string])

### Behavior

* Requires optional dependency `openpyxl`:

  If missing: raises ValueError instructing to install `aetherflow-core[excel]`.

* Loads workbook `data_only=True`.

* Collects:

    * workbook defined names
    * all string cell values (normalized) from either the given sheet or all sheets

* `required_names` can be:

    * a JSON string -> parsed as list
    * a plain string -> treated as a single required item

* Raises `ValueError` if any required token is missing.

---

## excel_fill_small

### Purpose

Fill an Excel template using **small in-memory tables**, typically from `db_fetch_small.rows_json`.

Designed for “report-like” templates with anchors, markers, headers, styling, and guarded insertion.

### Required Inputs

* `template_path` (string)
* `output` (string)
* `targets` (array[object])

### Output

* `output` (string)
* `written` (array[object]) — per-target summary:

    * `name`, `sheet`, `rows`, `cols`, `insert`, `header_mode`, `header_style`,
      `type_cast`, `style_mode`, `start_cell`, `template_has_header`

### Target Schema (targets[*])

Each target MUST set exactly one of:

* `anchor` (string) OR
* `cell` (string)

And MUST provide:

* `rows_json` (string) — JSON array of rows

Common optional fields:

* `name` (string)
* `sheet` (string)

Header controls:

* `columns_json` (string) — JSON array of column names (optional)
* `header_mode` (string: `template|override|append`, default `template`)
* `header_style` (string: `template|style_row`, default `template`)
* `header_clear` (bool, default true when header is written)
* `header_clear_width` (int, optional)

Insertion controls:

* `insert` (string: `below|replace`, default `replace`)
* `anchor_is_marker` (bool, default depends on anchor type)
* `template_has_header` (bool, default depends on anchor)

Anchor cleanup:

* `anchor_clear` (bool, default false)
* `anchor_clear_mode` (`cell|row`, default `cell`)
* `anchor_clear_width` (int, only for `row`)

Casting:

* `type_cast` (`none|basic|schema`, default `schema` if dtypes exist else `none`)
* `dtypes` / `dtypes_json` (object)

Styling:

* `style_mode` (`none|copy_row`, default `none`)
* `style_row_offset` (int, default `2`)
* `style_apply` (`data|header|both`, default `data`)
* `clear_style_row` (bool, default false)

Guards:

* `max_rows` (int) — guard for data rows
* `max_total_rows` (int) — guard for header+data
* `max_cols` (int)

### Anchor Resolution

`anchor` supports:

1. Named range
2. Direct cell-like reference (`Sheet!A1` or `A1`)
3. Anchor text search (normalized exact match)

Enterprise mode restriction:

* Anchor text search requires a pinned sheet (to avoid scanning all sheets).

### Template Header “Hard-Lock” Behavior

When `template_has_header=true`, AetherFlow:

* never inserts at the header row position
* always writes data starting below the header row
* prevents the classic “insert pushes header down and breaks formatting” bug

### Example

```yaml
- id: fill_report
  type: excel_fill_small
  inputs:
    template_path: templates/report.xlsx
    output: out/report.xlsx
    targets:
      - name: main_table
        sheet: Report
        anchor: QIP_ANCHOR
        anchor_is_marker: true
        template_has_header: true
        insert: below
        header_mode: template
        rows_json: "{{steps.fetch_top.rows_json}}"
        columns_json: "{{steps.fetch_top.columns_json}}"
        dtypes_json: "{{steps.fetch_top.dtypes_json}}"
        type_cast: schema
        style_mode: copy_row
        style_apply: data
```

---

## excel_fill_from_file

### Purpose

Stream data from CSV/TSV/Parquet into an Excel template.

Supports two modes:

* `data_sheet`: write a raw table into a dedicated sheet
* `report_region`: write into a pre-formatted report region using anchor/cell (guarded)

### Required Inputs

* `template_path` (string)
* `output` (string)
* `targets` (array[object])

### Step-level Optional Inputs

* `rows_threshold` (int, default `50000`) — default threshold used by targets

### Output

* `output` (string)
* `written` (array[object]) — per-target summary similar to `excel_fill_small`

### Target Schema (targets[*])

Required:

* `source_path` (string)
* `source_format` (string: `csv|tsv|parquet`) — default inferred from extension if omitted
* `mode` (string: `data_sheet|report_region`, default `data_sheet`)

Anchor / position:

* `sheet` (string) — required in many cases unless anchor/cell includes sheet
* `anchor` XOR `cell` (optional; for data_sheet default is cell `A1`)

Header read and header write:

* `read_header` (bool, default true)
* Legacy: `include_header` supported (maps to read_header + header_mode)
* `header_mode` (`template|override|append`)

    * default: `template` for report_region
    * default: `append` for data_sheet
* `header_style` (`template|style_row`, default `template`)

Insertion:

* `insert` (`below|replace`)

    * default: `below` for report_region
    * default: `replace` for data_sheet
* `anchor_is_marker` (bool)
* `template_has_header` (bool)

    * default: `true` for typical report_region marker templates
    * default: `false` for data_sheet

Guards (report_region):

* `rows_threshold` (int, default from step-level)
* `fail_on_threshold` (bool, default true)
* `count_mode` (`fast` by default) — used by fast row counting
* `row_count` (int, optional) — if provided, avoids counting

Type casting:

* `type_cast` (`none|basic|schema`)
* `dtypes` / `dtypes_json`
* `columns` / `columns_json` (optional list, needed for schema casting if file has no header)

File read options (csv/tsv):

* `encoding`, `delimiter`, `quotechar`, `escapechar`, `doublequote`, `quoting`, `linefeed`

data_sheet niceties:

* `data_sheet_prefix` (default `"DATA_"`)
* `freeze_panes` (default true)
* `autofilter` (default true; only applied when header is written)
* `header_bold` (default true; does not replace template fonts, only toggles bold)

### Behavior

* If report_region + `fail_on_threshold=true` and row_count exceeds threshold, raises `ReportTooLargeError`.
* Parquet requires `pyarrow` (same optional dependency behavior as DB parquet export).

### Example (report_region)

```yaml
- id: fill_region_from_csv
  type: excel_fill_from_file
  inputs:
    template_path: templates/report.xlsx
    output: out/report.xlsx
    rows_threshold: 20000
    targets:
      - name: region1
        mode: report_region
        sheet: Report
        anchor: QIP_ANCHOR
        anchor_is_marker: true
        template_has_header: true
        insert: below
        source_path: exports/events.csv
        source_format: csv
        read_header: true
        header_mode: template
        rows_threshold: 20000
        fail_on_threshold: true
```

### Example (data_sheet)

```yaml
- id: dump_data_sheet
  type: excel_fill_from_file
  inputs:
    template_path: templates/report.xlsx
    output: out/report.xlsx
    targets:
      - name: raw_events
        mode: data_sheet
        source_path: exports/events.tsv
        source_format: tsv
        data_sheet_prefix: DATA_
        read_header: true
        header_mode: append
        insert: replace
```

---

# 3) Locking / Guards

## with_lock

### Purpose

Execute an embedded inner step under a TTL lock.

### Required Inputs

* `lock_key` (string)
* `step` (object) — embedded step spec:

    * `type` (required)
    * `id` (optional)
    * `inputs` (optional)

### Optional Inputs

* `ttl_seconds` (int, default `600`)

### Output

* Returns the inner step output directly.

### Behavior

* If lock cannot be acquired: raises `RuntimeError("Lock not acquired: ...")`
* Always releases lock in a `finally` block.

### Example

```yaml
- id: guarded_export
  type: with_lock
  inputs:
    lock_key: "daily_export_lock"
    ttl_seconds: 900
    step:
      type: db_extract_stream
      id: inner_export
      inputs:
        resource: db_main
        sql: "select * from events"
        output: exports/events.tsv
        format: tsv
```

---

## check_items

### Purpose

Gate step: check that an item list is non-empty (or meets `min_count`).

### Required Inputs

* `items` (list | string)

### Optional Inputs

* `min_count` (int, default `1`)

### Output (SUCCESS)

* `has_data` (bool) -> true
* `count` (int)

### Output (SKIPPED)

* `has_data` (bool) -> false
* `count` (int)
* `reason` present in StepResult

### Behavior

* If `items` is a string: treated as comma-separated list.
* If count < min_count: returns `STEP_SKIPPED`.

---

# 4) File Transfer (SMB / SFTP)

All SMB/SFTP list steps implement a similar guard pattern:

* list remote entries
* apply glob on `name`
* compute `rel_path`
* if `count < min_count` -> `STEP_SKIPPED` with `has_data=false`

All download steps:

* create `dest_dir` under job artifacts
* build safe destination path using `rel_path`
* download each file
* return local paths + dest_dir

All delete steps:

* delete each remote path
* return `{ "is_deleted": true }`

---

## smb_list_files

### Required Inputs

* `resource` (string)
* `remote_dir` (string)

### Optional Inputs

* `pattern` (string, default `"*"`)
* `recursive` (bool, default `false`)
* `min_count` (int, default `1`)

### Output

Returns `StepResult`:

* SUCCESS output: `{ has_data: true, count, files: [...] }`
* SKIPPED output: `{ has_data: false, count, files: [] }`

### Connector Contract Assumptions

SMB connector must expose:

* `list(remote_dir) -> list[RemoteFileMeta]`

The step intentionally does not assume deeper filesystem APIs.

---

## smb_download_files

### Required Inputs

* `resource`
* `files`
* `dest_dir`

### Output

* `local_files`
* `dest_dir`

Accepts `files` as either dict objects or `RemoteFileMeta` objects.

---

## smb_delete_files

### Required Inputs

* `resource`
* `files`

### Output

* `is_deleted` (true)

---

## smb_upload_files

### Required Inputs

* `resource`
* `local_files` (array[string])
* `remote_dir` (string)

### Output

* `uploaded` (array[string]) — local absolute paths
* `remote_dir` (string)

Behavior:

* relative `local_files` are resolved under job artifacts
* uploaded path is `remote_dir/<filename>`

---

## sftp_list_files

### Required Inputs

* `resource`
* `remote_dir`

### Optional Inputs

* `pattern` (default `"*"`)
* `recursive` (default `false`)
* `min_count` (default `1`)

### Output

Returns `StepResult`:

* SUCCESS: `{ has_data: true, count, files: [...] }`
* SKIPPED: `{ has_data: false, count, files: [] }`

---

## sftp_download_files

### Required Inputs

* `resource`
* `files`
* `dest_dir`

### Output

* `local_files`
* `dest_dir`

Accepts `files` as dict objects or `RemoteFileMeta` objects.

---

## sftp_delete_files

### Required Inputs

* `resource`
* `files`

### Output

* `is_deleted` (true)

---

## sftp_upload_files

### Purpose

Upload multiple local files/items to an SFTP directory with optional parallelism and manifest tracking.

### Required Inputs

* `resource` (string)
* `items` (array) — each item can be:

    * string path
    * object `{ file, id?, remote_name? }`
* `remote_dir` (string)

### Optional Inputs

* `parallelism` (object)

    * `enabled` (bool, default true)
    * `workers` (int, default 8)
    * `fail_fast` (bool, default true)

### Output

* `manifest` (string) — path to a manifest JSON written under `ctx.manifests_dir(job_id)`
* `count` (int) — number of attempted uploads (including skipped)

### Behavior

* Uses a manifest file per step id:

    * `<manifests_dir>/<step_id>.manifest.json`
* If an item id already exists in the manifest, it is marked skipped and not uploaded again.
* Upload function contract used:

  `sftp.upload(local_path, remote_path)`

---

# 5) Email

## mail_send

### Purpose

Send an email via a configured mail connector/resource.

### Required Inputs

* `resource` (string)
* `to` (string | array[string])
* `subject` (string)
* `body` (string)

### Optional Inputs

* `html` (bool, default false)
* `text` (string) — plaintext fallback when html=true
* `cc` (string | array[string])
* `bcc` (string | array[string])
* `from_addr` (string) — override sender address

### Output

* `sent` (bool) -> true
* `to` (array[string])
* `subject` (string)
* `html` (bool)

### Behavior

* If `html=true`: uses `send_html(to, subject, html=body, text=..., cc, bcc, from_addr)`
* Else: uses `send_plaintext(to, subject, body, cc, bcc, from_addr)`
* `to/cc/bcc` accept either list or scalar and are normalized to lists.

---

# 6) external.process

## Purpose

Run an OS-level process in a controlled, observable, retryable way.

This is the “ops-grade bridge” step for tools outside Python.

### Required Inputs

* `command` (string | array[string])

### Common Optional Inputs

Process invocation:

* `args` (array[string]) — appended to command
* `shell` (bool, default false) — discouraged; logs a warning about platform differences
* `cwd` (string) — working directory (resolved via sandbox path rules)
* `timeout_seconds` (number | null)
* `kill_grace_seconds` (int, default 15)

Environment:

* `inherit_env` (bool, default true)
* `env` (object) — additional env vars
* Always sets:

    * `AETHERFLOW_FLOW_ID`
    * `AETHERFLOW_RUN_ID`
    * and if `atomic_dir` is used: `AETHERFLOW_OUTPUT_DIR`

Logging (`log` object):

* `stdout` mode: `inherit|capture|file|discard` (default `inherit`)
* `stderr` mode: `inherit|capture|file|discard` (default `inherit`)
* `file_path` (string) — required if any stream uses `file`
* `max_capture_kb` (int, default 1024)

Idempotency (`idempotency` object):

* `strategy`: `none|marker|atomic_dir`
* marker mode:

    * `marker_path` (string) or use `success.marker_file`
* atomic_dir mode:

    * `temp_output_dir` (string, required)
    * `final_output_dir` (string, required)
    * `atomic_rename` (bool, default true)

Success criteria (`success` object):

* `exit_codes` (array[int], default `[0]`)
* `require_files` (array[string] | string)
* `require_glob` (array[string] | string)
* `forbid_files` (array[string] | string)
* `marker_file` (string)

Retry (`retry` object):

* `max_attempts` (int, default 1)
* `backoff_seconds` (number, default 0)
* `backoff_multiplier` (number, default 1.0)
* `max_backoff_seconds` (number, default 0)
* `retry_on_exit_codes` (array[int])
* `retry_on_timeout` (bool, default false)

Outputs mapping:

* `outputs` (object) — key/value pairs copied verbatim into step output

### Outputs

At minimum:

* `exit_code` (int)
* `attempts` (int)

Additional fields depending on log modes:

* `stdout` (string) if stdout is `capture`
* `stderr` (string) if stderr is `capture`
* `log_file` (string) if any stream logs to file

Plus any user-provided `outputs` entries.

### Behavior

* If `idempotency.strategy=marker` and marker exists:

    * validates success conditions
    * returns `STEP_SKIPPED` with `{ skipped: true, marker: ... }`
* Timeout:

    * SIGTERM then kill after grace period
    * may retry if `retry_on_timeout=true`
* Non-allowed exit code:

    * may retry if exit code in `retry_on_exit_codes`
* After process finishes successfully:

    * validates success rules (required files/globs, forbidden files, marker)
    * returns output dict

### Example

```yaml
- id: run_spark_job
  type: external.process
  inputs:
    command: ["bash", "-lc"]
    args:
      - "spark-submit --class com.acme.Job app.jar"
    cwd: jobs
    timeout_seconds: 3600
    log:
      stdout: capture
      stderr: capture
      max_capture_kb: 2048
    retry:
      max_attempts: 3
      backoff_seconds: 5
      backoff_multiplier: 2
      retry_on_exit_codes: [1, 2]
    success:
      exit_codes: [0]
      require_files:
        - "out/result.json"
```

---

# 7) Archiving

## zip

### Purpose

Create a `.zip` archive from a list of files/directories/globs.

### Required Inputs

* `dest_path` (string)
* `items` (array)

### Optional Inputs

* `src_dir` (string | null) — base directory for archive names (default: job artifacts dir)
* `recursive` (bool, default true) — when items include directories
* `overwrite` (bool, default true)
* `password` (string | null)
* `compression` (string, default `"deflated"`)
* `resource` / `connector` (string | null) — archive resource name (kind=archive)

### Outputs

If no input files matched: returns `STEP_SKIPPED`:

* `output` (string)
* `count` (0)

Otherwise output depends on the archive connector driver, but the step always adds:

* `src_dir` (string)

### Behavior

* Builds input file list from `items`:

    * string paths or glob patterns
    * dict items: `{ path: ... }` or `{ glob: ... }`
* Ensures deterministic order and de-duplication.
* Enforces that all archived files are under `src_dir`.
* Archive connector resolution:

    1. `inputs.resource` / `inputs.connector`
    2. convention `archive_default` if present
    3. if enterprise mode and no resource: hard fail
    4. otherwise creates an ad-hoc archive connector:

        * password provided:

            * prefer `pyzipper`
            * else use OS `zip/unzip` if available
            * else fail with instructions
        * no password:

            * uses stdlib `zipfile`

### Example

```yaml
- id: pack_bundle
  type: zip
  inputs:
    dest_path: bundles/run.zip
    src_dir: .
    items:
      - "exports/*.csv"
      - path: "out/report.xlsx"
    password: "{{ZIP_PASSWORD}}"
    overwrite: true
```

---

## unzip

### Purpose

Extract one or more zip archives into a destination directory.

### Required Inputs

* `archives` (string | array[string])
* `dest_dir` (string)

### Optional Inputs

* `src_dir` (string | null) — base for relative layout calculation (default: job artifacts dir)
* `resource` / `connector` (string | null) — archive resource name (kind=archive)
* `password` (string | null)
* `overwrite` (bool, default true)
* `members` (array[string] | null) — extract only specific entries
* `private_zip_folder` (bool, default false)

### Outputs

* `unzipped` (array) — per-archive extraction results from connector
* `dest_dir` (string)

### Behavior

* If `archives` is a string: treated as single archive.
* Skips archives that do not exist or are directories.
* Determines output folder per archive:

    * if archive is under `src_dir`:

        * normally extracts under `dest_dir/<archive_parent_dir>/...`
        * if `private_zip_folder=true`: extracts under `dest_dir/<archive_name_without_ext>/...`
    * else extracts under `dest_dir/<archive_filename>/...` (fallback)
* Archive connector resolution matches `zip` step rules:

    * enterprise mode requires declared archive resource
    * non-enterprise may create ad-hoc driver

### Example

```yaml
- id: extract_bundle
  type: unzip
  inputs:
    archives:
      - bundles/run.zip
    dest_dir: extracted
    password: "{{ZIP_PASSWORD}}"
    overwrite: true
    private_zip_folder: true
```

