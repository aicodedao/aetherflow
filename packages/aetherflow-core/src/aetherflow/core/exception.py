"""Centralized customized exceptions for AetherFlow.

Historically, AetherFlow defined project-specific exceptions in multiple
modules. To standardize imports and avoid duplicate class definitions, all
customized exceptions live in this module.

Internal code should prefer explicit imports:

    from aetherflow.core.exception import SpecError

All internal imports should reference this module directly.
for backward compatibility.
"""

from __future__ import annotations

__all__ = [
    "SpecError",
    "ResolverSyntaxError",
    "ResolverMissingKeyError",
    "ConnectorError",
    "ReportTooLargeError",
    "ParquetSupportMissing",
]


class SpecError(ValueError):
    """Raised when a flow/manifest/profile spec is invalid (schema or semantic)."""


class ResolverSyntaxError(ValueError):
    """Raised when a template expression is syntactically invalid."""


class ResolverMissingKeyError(KeyError):
    """Raised when a template references a missing variable/key in strict mode."""


class ConnectorError(RuntimeError):
    """Base error for connector failures."""


class ReportTooLargeError(ValueError):
    """Raised when a report_region fill would exceed rows_threshold."""

    def __init__(self, *, target_name: str, source_path: str, row_count: int, rows_threshold: int):
        msg = (
            f"excel_fill_from_file target={target_name}: row_count={row_count} exceeds rows_threshold={rows_threshold}. "
            "Use mode=data_sheet (DATA_*) instead of report_region, or raise rows_threshold."
        )
        super().__init__(msg)
        self.target_name = target_name
        self.source_path = source_path
        self.row_count = int(row_count)
        self.rows_threshold = int(rows_threshold)


class ParquetSupportMissing(ValueError):
    """Raised when Parquet support (pyarrow) is required but not installed."""
