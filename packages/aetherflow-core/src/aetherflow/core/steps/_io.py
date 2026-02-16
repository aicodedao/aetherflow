from __future__ import annotations

from pathlib import Path

from aetherflow.core.exception import ParquetSupportMissing


def _count_subsequence_in_stream(p: Path, needle: bytes) -> int:
    """Count occurrences of a byte subsequence in a file stream.

    This handles multi-byte linefeeds like CRLF (b"\r\n") without
    double-counting across chunk boundaries.
    """

    if not needle:
        raise ValueError("linefeed must be non-empty")

    n = 0
    tail = b""
    step = 64 * 1024
    with open(p, "rb") as f:
        while True:
            chunk = f.read(step)
            if not chunk:
                break
            buf = tail + chunk
            n += buf.count(needle)
            # keep last len(needle)-1 bytes to match boundary overlaps
            if len(needle) > 1:
                tail = buf[-(len(needle) - 1) :]
            else:
                tail = b""
    return n


def _csv_quoting(v: str | int | None) -> int:
    import csv

    if v is None:
        return csv.QUOTE_MINIMAL
    if isinstance(v, int):
        return v
    s = str(v).strip().lower()
    return {
        "minimal": csv.QUOTE_MINIMAL,
        "all": csv.QUOTE_ALL,
        "none": csv.QUOTE_NONE,
        "nonnumeric": csv.QUOTE_NONNUMERIC,
    }.get(s, csv.QUOTE_MINIMAL)


def fast_count_rows(
    path: str | Path,
    fmt: str,
    *,
    include_header: bool = True,
    count_mode: str = "fast",
    linefeed: str = "\n",
    encoding: str = "utf-8",
    delimiter: str | None = None,
    quotechar: str = '"',
    escapechar: str | None = None,
    doublequote: bool = True,
    quoting: str | int | None = None,
) -> int:
    """Return the number of *data rows* in a local artifact.

    - CSV/TSV:
      - count_mode=fast: counts a linefeed byte sequence in binary chunks (does not parse CSV)
      - count_mode=csv_parse: uses csv.reader to count records (handles multiline quoted fields)
    - Parquet: reads `num_rows` from file metadata (requires pyarrow)

    Notes:
      - The returned count excludes the header row when `include_header=True` for CSV/TSV.
      - `fast` mode assumes **one record per line** and may miscount multiline CSV.
    """

    p = Path(path)
    fmt = (fmt or p.suffix.lstrip(".") or "tsv").lower()
    count_mode = (count_mode or "fast").lower()

    if fmt in ("csv", "tsv"):
        if delimiter is None:
            delimiter = "\t" if fmt == "tsv" else ","

        if count_mode == "fast":
            # Fast path: count linefeed bytes. This assumes one record per line.
            if encoding.lower().replace("_", "-").startswith(("utf-16", "utf-32")):
                raise ValueError("fast row counting does not support utf-16/utf-32; use count_mode=csv_parse")
            needle = (linefeed or "\n").encode("utf-8", errors="strict")
            nl = _count_subsequence_in_stream(p, needle)

            # If file does not end with linefeed, count the last partial line.
            if p.stat().st_size > 0:
                with open(p, "rb") as f:
                    # check last bytes for the full needle
                    tail_len = min(len(needle), p.stat().st_size)
                    f.seek(-tail_len, 2)
                    last = f.read(tail_len)
                if not last.endswith(needle):
                    nl += 1

            if include_header and nl > 0:
                nl -= 1
            return max(0, int(nl))

        if count_mode == "csv_parse":
            import csv

            q = _csv_quoting(quoting)
            n = 0
            with open(p, "r", encoding=encoding, newline="") as f:
                reader = csv.reader(
                    f,
                    delimiter=delimiter,
                    quotechar=quotechar,
                    escapechar=escapechar,
                    doublequote=bool(doublequote),
                    quoting=q,
                )
                for _ in reader:
                    n += 1
            if include_header and n > 0:
                n -= 1
            return max(0, int(n))

        raise ValueError(f"Unsupported count_mode for CSV/TSV: {count_mode}")

    if fmt == "parquet":
        try:
            import pyarrow.parquet as pq
        except Exception as e:
            raise ParquetSupportMissing(
                "parquet format requires optional dependency: pyarrow (install aetherflow-core[parquet])"
            ) from e
        pf = pq.ParquetFile(p)
        md = pf.metadata
        return int(md.num_rows) if md is not None else 0

    raise ValueError(f"Unsupported format for fast_count_rows: {fmt}")