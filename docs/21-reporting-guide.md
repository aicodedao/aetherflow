# 21 — Reporting Guide (Excel Templates + DB Extracts)

AetherFlow supports two Excel reporting patterns. Pick based on **data size** and **where you want the data to land**.

Built-in steps:

- `excel_fill_small` — fill a template region from *small* in-memory tables (JSON rows).
- `excel_fill_from_file` — stream CSV/TSV/Parquet exports from disk into Excel (bounded memory).

If your workbook starts lagging or exploding in size, that’s not “Excel being Excel” — that’s you choosing the wrong pattern.

---

## Mental model

You always have two things:

1. A **template workbook** (formatted, stable)
2. A **data payload** (small table in memory OR big file on disk)

AetherFlow writes **values**, not “Excel magic”. Formatting should live **in the template**, and you choose whether the step:

- preserves template header rows,
- overrides header text,
- inserts rows to avoid overwriting content below,
- copies styles from a style row,
- casts values into typed Excel cells (int/float/date/datetime).

---

# Pattern A — Small Data → Fill a Template Region

Use `excel_fill_small`.

## When to use

- Data fits comfortably in memory (typical source: `db_fetch_small`)
- You want values written directly into a **formatted report region**
- You care about style + layout *inside* the report sheet

## Why this works
- `db_fetch_small` loads guarded in-memory data
- Data passed between steps as JSON strings
- `excel_fill_small` writes directly into a preformatted anchor region

## What the step expects

`excel_fill_small` consumes:

- `rows_json`: JSON array of rows (list-of-lists)
- `columns_json` (optional): JSON list of column names
- optional guards: `max_rows`, `max_total_rows`, `max_cols`, `row_count`

## Targeting rules 

### anchor vs cell

Each target MUST set **exactly one**:

- `anchor`: named range OR an anchor text cell OR a cell reference
- `cell`: direct cell ref (`A1` with `sheet`, or `Sheet!A1`)

Anchor resolution order:

1. Named range (defined name)
2. If `anchor` looks like a cell ref (`A1` / `Sheet!A1`) → treat as cell
3. Otherwise → search for a cell whose text matches the anchor token (normalized)

### anchor_is_marker

After resolving the location we get `(sheet, r_anchor, c0)`.

Then `r0` depends on `anchor_is_marker`:

- `anchor_is_marker: true` → `r0 = r_anchor + 1`  
  Use when the anchor row is a marker-only row.
- `anchor_is_marker: false` → `r0 = r_anchor`  
  Use when the anchor sits on the header row.

### HARD-LOCKED semantics (template_has_header + insert)

Key flags:

- `template_has_header`: whether row `r0` is a **template header row that must stay**
- `insert`: how to avoid overwriting content below (`replace` or `below`)

Hard-lock rule:

- If `template_has_header: true`, then **data always starts at `r0 + 1`**, and if `insert: below`, rows are inserted at **data_start_row** (never at `r0`).  
  This preserves the template header row exactly where it is.

### Header writing modes

- `header_mode: template` → do **not** write header values (template header stays).
- `header_mode: override|append` + `columns_json` present → write header values at `r0`.
  - `header_clear: true` clears old header **values** (format stays).
  - `header_style: template` keeps template header formatting.
  - `header_style: style_row` can style header from a style row (requires `style_mode: copy_row`).

### Styling mode (copy_row)

- `style_mode: none` (default)
- `style_mode: copy_row` → copy style from a “style row” onto output cells
  - `style_row_offset` controls which row is used as style source
  - `style_apply: data|header|both`
  - `clear_style_row`: optionally clears style row values after copying

### Type casting

Optional, before writing:

- `type_cast: none|basic|schema`
- schema casting uses column names (needs `columns_json`)
- supported dtypes: `string`, `int`, `float`, `bool`, `date`, `datetime`

## Target Configuration Matrix - `targets[*]` Keys

| Key | Type | Required | Default | Applies To | Description |
|------|------|----------|----------|-------------|-------------|
| `name` | str | No | `"target"` | all | Logical name for logging & overlap checks |
| `sheet` | str | No | — | anchor/cell resolution | Target sheet (required if using `cell: A1`) |
| `anchor` | str | XOR `cell` | — | region mode | Named range OR marker text OR cell ref |
| `cell` | str | XOR `anchor` | — | region mode | Direct cell reference (`A1` or `Sheet!A1`) |
| `rows_json` | str (JSON) | Yes | — | all | JSON array of row arrays |
| `columns_json` | str (JSON) | No | — | header/schema | JSON list of column names |
| `row_count` | int | No | — | guards | Optional row count for validation |
| `insert` | `below` \| `replace` | No | `replace` | write behavior | Row insertion strategy |
| `anchor_is_marker` | bool | No | `true` if anchor else `false` | region | Whether anchor row is marker-only |
| `template_has_header` | bool | No | `true` if anchor else `false` | region | Whether row `r0` is template header |
| `header_mode` | `template` \| `override` \| `append` | No | `template` | header | Header writing strategy |
| `header_style` | `template` \| `style_row` | No | `template` | header | Preserve template style or copy style row |
| `header_clear` | bool | No | `true` when header written | header | Clear old header values before writing |
| `header_clear_width` | int | No | auto | header | Width of header value clearing |
| `anchor_clear` | bool | No | `false` | anchor | Remove visible anchor marker |
| `anchor_clear_mode` | `cell` \| `row` | No | `cell` | anchor | How anchor cleanup behaves |
| `anchor_clear_width` | int | No | `1` | anchor | Width if clearing anchor row segment |
| `type_cast` | `none` \| `basic` \| `schema` | No | `schema` if dtypes else `none` | typing | Casting strategy |
| `dtypes` / `dtypes_json` | dict | No | — | typing | Column → dtype mapping |
| `style_mode` | `none` \| `copy_row` | No | `none` | styling | Enable row-style copy |
| `style_row_offset` | int | No | `2` | styling | Offset from anchor/r0 for style source |
| `style_apply` | `data` \| `header` \| `both` | No | `data` | styling | Which rows get style |
| `clear_style_row` | bool | No | `false` | styling | Clear style row values after copying |
| `max_rows` | int | No | — | guards | Max data rows allowed |
| `max_total_rows` | int | No | — | guards | Max header + data rows |
| `max_cols` | int | No | — | guards | Max width allowed |

## Use case: small (db_fetch_small → excel_fill_small)

Matches the current `render_small` demo.

```yaml
jobs:
  - id: report_small
    steps:
      - id: fetch_small
        type: db_fetch_small
        inputs:
          resource: exasol_main
          sql: "SELECT * FROM QIP limit 10"
          max_rows: 50000

      - id: validate_template_small
        type: excel_validate_template
        inputs:
          template_path: "{{env.AETHERFLOW_ACTIVE_DIR}}/templates/template.xlsx"
          required_names: ["QIP_ANCHOR", "QC_ANCHOR"]

      - id: render_small
        type: excel_fill_small
        inputs:
          template_path: "{{env.AETHERFLOW_ACTIVE_DIR}}/templates/template.xlsx"
          output: "out/report_{{run_id}}_small.xlsx"
          targets:
            - name: qip_region
              anchor: QIP_ANCHOR
              anchor_is_marker: true
              template_has_header: true

              columns_json: "{{ steps.fetch_small.columns_json }}"
              rows_json: "{{ steps.fetch_small.rows_json }}"
              row_count: "{{ steps.fetch_small.row_count }}"

              # guardrails
              max_rows: 5000
              max_cols: 20
              insert: below

              # header behavior
              header_mode: override
              header_style: template
              header_clear: true
              header_clear_width: 50

              # optional cleanup of visible marker text
              anchor_clear: true
              anchor_clear_mode: cell

              # typing + schema from db_fetch_small
              type_cast: schema
              dtypes_json: "{{ steps.fetch_small.dtypes_json }}"

              # style copy (data rows only)
              style_mode: copy_row
              style_row_offset: 2
              style_apply: data
````

What it does:

* finds `QIP_ANCHOR`, treats it as a marker row, writes below it
* preserves the template header row at `r0`
* inserts rows below header so downstream content doesn’t get overwritten
* overwrites header text but keeps header formatting
* copies styles from a style row onto data rows

---

# Pattern B — Big Data → Stream to File → Fill Workbook From File

Use `excel_fill_from_file`.

## When to use

* Data is large
* You want predictable memory usage
* You don’t want Excel to cry
* You care about production stability

## Architecture Flow

```
DB → stream → artifact file (csv/tsv/parquet)
        ↓
excel_fill_from_file → DATA_* sheet
        ↓
REPORT sheet references DATA_* via formulas/pivots
```

## Why this is better for large data

* Avoids passing huge payload between steps
* Avoids string templating bottleneck
* Bounded memory
* Workbook stays manageable
* Clean separation: raw vs presentation

## Source formats

* `csv`, `tsv` (Python csv reader)
* `parquet` (requires optional dependency `pyarrow`)

## Mode

This step supports two modes per target:

* `mode: data_sheet` — write raw export tables into `DATA_*` sheets (recommended default)
* `mode: report_region` — write into formatted report areas (guarded by thresholds)

### data_sheet (recommended)

Defaults:

* sheet auto-created if missing
* if no anchor/cell provided → starts at `A1`
* `header_mode` defaults to `append`
* `template_has_header` defaults to `false`
* `insert` defaults to `replace`

Niceties (optional):

* `freeze_panes`
* `autofilter`
* `header_bold` (only toggles `bold=True` on existing fonts; never replaces template fonts)

### report_region (use only when you must)

Defaults:

* `insert` defaults to `below`
* `template_has_header` defaults to `true`
* `header_mode` defaults to `template`

Guardrails:

* row count is computed (unless you provide `row_count`)
* if `fail_on_threshold: true` and `row_count > rows_threshold` → raises:

`ReportTooLargeError(target_name, source_path, row_count, rows_threshold)`

Row counting modes:

* `count_mode: fast` — line based, very fast
* `count_mode: csv_parse` — correct for multiline quoted CSV, slower

## CSV / TSV Compatibility Options

Only override when needed.

```yaml
delimiter: ","
encoding: utf-8
quotechar: '"'
quoting: minimal
escapechar: "\\"
doublequote: true
linefeed: "\n"
count_mode: csv_parse
```

## Row Counting Modes

Used before writing large regions.

### Fast mode (default)

* Counts line breaks
* Assumes 1 record per line
* Very fast

### csv_parse mode

* Proper CSV parsing
* Handles multiline quoted fields
* Slower but accurate

If your CSV has embedded newlines → use `count_mode: csv_parse`.

## Target Configuration Matrix - `targets[*]` Keys

This step supports two modes: `mode: data_sheet` and `mode: report_region`.

### Common Keys (Both Modes)

| Key | Type | Required | Default | Description |
|------|------|----------|----------|-------------|
| `name` | str | No | `"target"` | Logical name |
| `mode` | `data_sheet` \| `report_region` | No | `data_sheet` | Writing mode |
| `sheet` | str | Sometimes | auto or required | Sheet name |
| `anchor` | str | XOR `cell` | — | Named range / marker |
| `cell` | str | XOR `anchor` | — | Direct cell ref |
| `source_path` | str | Yes | — | File path |
| `source_format` | `csv` \| `tsv` \| `parquet` | No | inferred | Source format |
| `insert` | `below` \| `replace` | No | mode-dependent | Insert strategy |
| `anchor_is_marker` | bool | No | mode-dependent | Anchor layout rule |
| `template_has_header` | bool | No | mode-dependent | Template header preservation |
| `read_header` | bool | No | `true` | Read file header row |
| `header_mode` | `template` \| `override` \| `append` | No | mode-dependent | Header behavior |
| `header_style` | `template` \| `style_row` | No | `template` | Header formatting |
| `header_clear` | bool | No | `true` if writing header | Clear header values |
| `header_clear_width` | int | No | auto | Header clear width |
| `anchor_clear` | bool | No | `false` | Remove anchor marker |
| `anchor_clear_mode` | `cell` \| `row` | No | `cell` | Anchor cleanup behavior |
| `type_cast` | `none` \| `basic` \| `schema` | No | auto | Type casting mode |
| `dtypes` / `dtypes_json` | dict | No | — | Column → dtype map |
| `columns_json` | list | No | — | Explicit columns (if no header) |
| `style_mode` | `none` \| `copy_row` | No | `none` | Style copy |
| `style_row_offset` | int | No | `2` | Style source offset |
| `style_apply` | `data` \| `header` \| `both` | No | `data` | Style target |
| `clear_style_row` | bool | No | `false` | Clear style row after copy |

### Additional Keys — `report_region` Mode Only

| Key | Type | Default | Description |
|------|------|----------|-------------|
| `rows_threshold` | int | step-level default | Max rows allowed before failure |
| `fail_on_threshold` | bool | `true` | Raise `ReportTooLargeError` |
| `count_mode` | `fast` \| `csv_parse` | `fast` | Row counting strategy |
| `row_count` | int | — | Provided row count override |

### Additional Keys — `data_sheet` Mode Only

| Key | Type | Default | Description |
|------|------|----------|-------------|
| `data_sheet_prefix` | str | `"DATA_"` | Auto sheet naming prefix |
| `freeze_panes` | bool | `true` | Freeze header row |
| `autofilter` | bool | `true` | Apply Excel filter |
| `header_bold` | bool | `true` | Bold header font (non-destructive) |

## Use case: large2region (stream → report_region targets)

Matches the `qip_region` + `qc_region` demo.

```yaml
jobs:
  - id: report_large2region
    steps:
      - id: q_ip
        type: db_extract_stream
        inputs:
          resource: exasol_main
          sql: "SELECT * FROM QIPlimit 10"
          output: "data/qip.csv"
          format: "csv"
          include_header: true
          emit_dtypes: true
          delimiter: ","
          encoding: "utf-8"
          linefeed: "\n"

      - id: q_c
        type: db_extract_stream
        inputs:
          resource: exasol_main
          sql: "SELECT * FROM QC limit 10"
          output: "data/qc.csv"
          format: "csv"
          include_header: true
          emit_dtypes: true
          delimiter: ","
          encoding: "utf-8"
          linefeed: "\n"

      - id: validate_template
        type: excel_validate_template
        inputs:
          template_path: "{{env.AETHERFLOW_ACTIVE_DIR}}/templates/template_both_modes.xlsx"
          sheet: "Report"
          required_names: ["QIP_ANCHOR", "QC_ANCHOR"]

      - id: render_regions
        type: excel_fill_from_file
        inputs:
          template_path: "{{env.AETHERFLOW_ACTIVE_DIR}}/templates/template_both_modes.xlsx"
          output: "out/report_{{run_id}}_large2region.xlsx"
          rows_threshold: 20000
          targets:
            - name: qip_region
              mode: report_region
              sheet: "Report"
              anchor: "QIP_ANCHOR"
              anchor_is_marker: true
              template_has_header: true
              insert: below

              source_path: "{{steps.q_ip.artifact_path}}"
              source_format: "csv"

              read_header: true
              header_mode: override
              header_style: template
              header_clear: true
              header_clear_width: 50
              anchor_clear: true
              anchor_clear_mode: cell

              type_cast: schema
              dtypes_json: "{{steps.q_ip.dtypes_json}}"

              style_mode: copy_row
              style_row_offset: 2
              style_apply: data

              fail_on_threshold: true
              count_mode: csv_parse

            - name: qc_region
              mode: report_region
              sheet: "Report"
              anchor: "QC_ANCHOR"
              anchor_is_marker: true
              template_has_header: true
              insert: below

              source_path: "{{steps.q_c.artifact_path}}"
              source_format: "csv"

              read_header: true
              header_mode: override
              header_style: template
              header_clear: true
              header_clear_width: 50
              anchor_clear: true
              anchor_clear_mode: cell

              type_cast: schema
              dtypes_json: "{{steps.q_c.dtypes_json}}"

              style_mode: copy_row
              style_row_offset: 2
              style_apply: data

              fail_on_threshold: true
              count_mode: csv_parse
```

## Use case: large2data_ (stream → DATA_* sheets)

Matches the `data_qip`, `data_qc`, `demo`, `raw_data` style targets.

```yaml
jobs:
  - id: report_large2data
    steps:
      - id: q_ip
        type: db_extract_stream
        inputs:
          resource: exasol_main
          sql: "SELECT * FROM QIP limit 10"
          output: "data/qip.csv"
          format: "csv"
          include_header: true
          emit_dtypes: true

      - id: q_c
        type: db_extract_stream
        inputs:
          resource: exasol_main
          sql: "SELECT * FROM QC limit 10"
          output: "data/qc.csv"
          format: "csv"
          include_header: true
          emit_dtypes: true

      - id: render_data_sheets
        type: excel_fill_from_file
        inputs:
          template_path: "{{env.AETHERFLOW_ACTIVE_DIR}}/templates/template_both_modes.xlsx"
          output: "out/report_{{run_id}}_large2data.xlsx"
          targets:
            - name: data_qip
              mode: data_sheet
              sheet: "DATA_qip"
              cell: "A4"
              source_path: "{{steps.q_ip.artifact_path}}"
              source_format: "csv"

              read_header: true
              header_mode: append
              header_style: template

              type_cast: schema
              dtypes_json: "{{steps.q_ip.dtypes_json}}"

              insert: replace
              freeze_panes: true
              autofilter: true
              header_bold: true

            - name: data_qc
              mode: data_sheet
              sheet: "DATA_qc"
              cell: "A4"
              source_path: "{{steps.q_c.artifact_path}}"
              source_format: "csv"

              read_header: true
              header_mode: append
              header_style: template

              type_cast: schema
              dtypes_json: "{{steps.q_c.dtypes_json}}"

              insert: replace
              freeze_panes: true
              autofilter: true
              header_bold: true

            # auto-sheet naming via data_sheet_prefix + name
            - name: demo
              mode: data_sheet
              data_sheet_prefix: "DATA_"
              source_path: "{{steps.q_ip.artifact_path}}"
              source_format: "csv"
              read_header: true
              header_mode: append
              insert: replace
              freeze_panes: true
              autofilter: true
              header_bold: true
```

---

# Choosing Pattern A vs Pattern B

Use Pattern A (`excel_fill_small`) for:

* KPI summaries
* small lookup tables
* compact dashboards
* “pretty table directly in REPORT” with controlled row count

Use Pattern B (`excel_fill_from_file`) for:

* anything big
* anything recurring in production
* anything where you care about predictable memory + speed

**Default recommendation:** Pattern B + `mode: data_sheet`.

## Quick Reference — Excel Reporting (Side-by-side, Decision Matrix, Presets)

This page gives you three copy-paste-ready artifacts:

1. Side-by-side feature comparison: `excel_fill_small` vs `excel_fill_from_file`  
2. Decision matrix: choose the right step by data size, formatting need, and stability requirement  
3. Safe production preset configs (YAML snippets) you can drop in and use

### 1) Side-by-side comparison

| Topic / Behavior | `excel_fill_small` | `excel_fill_from_file` |
|---|---:|---|
| Primary use | Small in-memory tables (JSON rows) | Large exports streamed from disk (CSV/TSV/Parquet) |
| Typical source step | `db_fetch_small` | `db_extract_stream`, `db_export` |
| Memory footprint | In-memory (must fit comfortably) | Streamed; bounded memory |
| Modes supported | Single mode (region write) | Two modes: `data_sheet` and `report_region` |
| Anchor/cell targeting | Yes — anchor or cell | Yes — anchor or cell (data_sheet can auto-create sheet) |
| Header model defaults | `header_mode: template` | `data_sheet` → `append` / `report_region` → `template` |
| Insert semantics | `replace` (default) or `below` | `data_sheet`: `replace`; `report_region`: `below` (default) |
| Template header handling | `template_has_header` controls behavior; hard-locked semantics apply | Same model but mode affects defaults (`report_region` expects template header) |
| Row-count guards | `max_rows`, `max_total_rows`, `max_cols` | `rows_threshold` + `fail_on_threshold` (report_region only) |
| Row counting modes | N/A (you pass rows_json) | `fast` or `csv_parse` for accurate pre-checks |
| Style copying | `style_mode: copy_row` supported | `style_mode: copy_row` supported |
| Type casting | `type_cast: none|basic|schema` | `type_cast: none|basic|schema` (works with file headers or provided columns) |
| Overlap guard | Per-sheet rectangle overlap checked | Per-sheet rectangle overlap checked (except `data_sheet + replace` allowed) |
| Failure mode when too big | You must check externally (row_count) or set guards | `ReportTooLargeError` if threshold exceeded and `fail_on_threshold: true` |
| Best when | You want pretty formatted table directly in REPORT for small datasets | You need predictable memory and production stability for large datasets |
| Recommended default | For small KPI tables only | Default for production: `data_sheet` mode |


### 2) Decision matrix — which step to pick

Use this quick decision grid. Pick the row that matches your situation.

| Data size | Formatting required in REPORT | Stability requirement | Recommended step & why |
|---|---:|---:|---|
| Small (< 5k rows) | Full formatting in REPORT (styled header, per-row styles) | Low ↔ Medium | `excel_fill_small` — fits in memory, writes directly into preformatted region, supports style copy and header rules. |
| Small (~5k–50k) | Light formatting in REPORT (simple table) | Medium | `excel_fill_small` **only if** you control size & guards (`max_rows`); otherwise prefer `excel_fill_from_file mode=data_sheet`. |
| Medium (50k–200k) | Minimal formatting in REPORT, heavy formulas in REPORT that reference raw data | High | `excel_fill_from_file` → `mode: data_sheet` + `DATA_*` sheets. Keep REPORT pretty by referencing DATA_* sheets. |
| Large (>200k) | Any formatting | High | `excel_fill_from_file` → `mode: data_sheet`. Never write huge blocks into formatted regions. |
| Any | Small summary table in REPORT + big raw dataset | High | Hybrid: `excel_fill_from_file` for DATA_* + `excel_fill_small` for small KPI summary region. |
| Any | Need deterministic, low-memory, stable runs | High | `excel_fill_from_file` (prefer Parquet for typed preservation). |

**Rule of thumb:** If row_count > 50k → prefer `excel_fill_from_file` (data_sheet).

### 3) Default Behavior Matrix

| Mode | insert default | template_has_header default | header_mode default |
|-------|---------------|-----------------------------|---------------------|
| `excel_fill_small` | `replace` | `true` if anchor else `false` | `template` |
| `report_region` | `below` | `true` | `template` |
| `data_sheet` | `replace` | `false` | `append` |

### 4) Safe production preset configs

Three ready-to-use YAML presets. Tweak `rows_threshold`, `max_rows`, and paths to match your infra.

#### Preset A — Small KPI (safe default for quick reports)

```yaml
# preset: small_kpi
# use excel_fill_small with strict guards
steps:
  - id: fetch_kpi
    type: db_fetch_small
    inputs:
      resource: db_main
      sql: "SELECT region, total, date FROM sales_kpi LIMIT 1000"
      max_rows: 2000

  - id: render_kpi
    type: excel_fill_small
    inputs:
      template_path: "templates/report_kpi.xlsx"
      output: "out/report_kpi_{{run_id}}.xlsx"
      targets:
        - name: kpi_table
          anchor: KPI_ANCHOR
          anchor_is_marker: true
          template_has_header: true
          columns_json: "{{ steps.fetch_kpi.columns_json }}"
          rows_json: "{{ steps.fetch_kpi.rows_json }}"
          row_count: "{{ steps.fetch_kpi.row_count }}"
          type_cast: schema
          dtypes_json: "{{ steps.fetch_kpi.dtypes_json }}"
          insert: below
          header_mode: override
          header_style: template
          max_rows: 5000
          max_cols: 50
          style_mode: copy_row
          style_row_offset: 2
          style_apply: data
````

#### Preset B — Large production (DATA_* pattern, safe and stable)

```yaml
# preset: production_data_sheet
# stream to files → fill DATA_* sheets → REPORT references DATA_*
steps:
  - id: extract_main
    type: db_extract_stream
    inputs:
      resource: db_main
      sql: "SELECT * FROM sales_detail"
      output: "exports/sales_detail.csv"
      format: csv
      include_header: true
      fetch_size: 5000
      emit_dtypes: true

  - id: render_data_sheet
    type: excel_fill_from_file
    inputs:
      template_path: "templates/report_master.xlsx"
      output: "out/report_prod_{{run_id}}.xlsx"
      targets:
        - name: sales
          mode: data_sheet
          data_sheet_prefix: "DATA_"
          source_path: "{{ steps.extract_main.artifact_path }}"
          source_format: csv
          read_header: true
          header_mode: append
          header_style: template
          type_cast: schema
          dtypes_json: "{{ steps.extract_main.dtypes_json }}"
          insert: replace
          freeze_panes: true
          autofilter: true
```

#### Preset C — Region report with threshold check (safe for large-ish regions)

```yaml
# preset: region_guarded
# stream to file → attempt to fill report region with threshold guard
steps:
  - id: extract_region
    type: db_extract_stream
    inputs:
      resource: db_main
      sql: "SELECT * FROM regional_report"
      output: "exports/regional_report.tsv"
      format: tsv
      include_header: true
      emit_dtypes: true
      delimiter: "\t"

  - id: render_region
    type: excel_fill_from_file
    inputs:
      template_path: "templates/report_regions.xlsx"
      output: "out/report_region_{{run_id}}.xlsx"
      rows_threshold: 20000
      targets:
        - name: region_table
          mode: report_region
          sheet: "Report"
          anchor: REGION_ANCHOR
          anchor_is_marker: true
          template_has_header: true
          source_path: "{{ steps.extract_region.artifact_path }}"
          source_format: tsv
          read_header: true
          header_mode: override
          header_style: template
          type_cast: schema
          dtypes_json: "{{ steps.extract_region.dtypes_json }}"
          insert: below
          fail_on_threshold: true
          count_mode: csv_parse
```

## Cheatsheet / TL;DR

* Small, pretty, controlled → `excel_fill_small` (but set `max_rows`).
* Anything medium/large or production-critical → `excel_fill_from_file` + `data_sheet`.
* Need both? Do a hybrid: `data_sheet` for raw + `excel_fill_small` for tiny KPIs.
* Always use type casting or Parquet if you care about numeric/date types.

---

# Guardrails

## excel_fill_small

* `max_rows` guards *data rows*
* `max_total_rows` guards header+data if needed
* `max_cols` guards width
* per-sheet overlap guard: targets cannot write overlapping rectangles in the same sheet

## excel_fill_from_file (report_region)

* row counting + thresholds
* `ReportTooLargeError` when exceeding threshold (if `fail_on_threshold: true`)
* overlap guard per-sheet (except `data_sheet + insert=replace`, which intentionally allows repeated writes)

---

# Template conventions

## Anchor naming

Use consistent tokens:

* `QIP_ANCHOR`, `QC_ANCHOR`
* `KPI_TOTAL_ANCHOR`
* `tbl_sales_anchor`, etc.

## Marker-row layout (recommended)

```text
[QIP_ANCHOR]           <- marker row (anchor_is_marker: true)
[header cells ...]     <- template header row (template_has_header: true)
[data rows ...]
```

## Sheet naming (recommended)

* `Report` (pretty)
* `DATA_qip`, `DATA_qc`, `DATA_raw` (raw exports)

## Typed Cells (Numbers, Dates, Datetimes)

CSV/TSV are text. Excel will treat them as strings unless you cast.

### Best Option → Parquet

* Preserves types natively
* No guessing
* Cleanest pipeline

### Schema-based Casting (Recommended for CSV/TSV)

```yaml
type_cast: schema
dtypes:
  amount: int
  total: float
  active: bool
  day: date
  created_at: datetime
```

Supported:

* string
* int
* float
* bool
* date (YYYY-MM-DD)
* datetime (ISO format)

This avoids heavy inference and keeps memory stable.

---

# Common mistakes

* Excel huge / slow
  Cause: dumping large data into a formatted region.
  Fix: `excel_fill_from_file` → `mode: data_sheet`.

* Header duplicated / shifted down
  Cause: inserting at the wrong row.
  Fix: for report regions, set `template_has_header: true` and `insert: below` so insertion happens at **data_start_row**, not `r0`.

* Dates are strings
  Cause: CSV/TSV are text by default.
  Fix: `type_cast: schema` + `dtypes_json` (or use Parquet).

* Wrong row count on CSV
  Cause: multiline quoted fields.
  Fix: `count_mode: csv_parse`.

---

# Final rule

If you’re fighting Excel, you’re probably forcing Pattern A to do Pattern B’s job.

Keep:

* `DATA_*` raw
* `Report` pretty
* thresholds explicit
* memory bounded

That’s the whole reporting philosophy in AetherFlow.

