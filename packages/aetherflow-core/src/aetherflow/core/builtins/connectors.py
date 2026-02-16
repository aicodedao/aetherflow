from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import shutil
import subprocess
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Tuple

from aetherflow.core.connectors.base import ConnectorInit
from aetherflow.core.exception import ConnectorError
from aetherflow.core.registry.connectors import register_connector
from aetherflow.core.spec import RemoteFileMeta

_DRIVE_RE = re.compile(r"^[A-Za-z]:(?:[\\/].*)?$")
_UNC_RE = re.compile(r"^\\\\[^\\\/]+\\[^\\\/]+(?:[\\\/].*)?$")  # \\host\share\...
_SHARE_OVERRIDE_RE = re.compile(r"^([A-Za-z0-9_.-]+):[\\/](.*)$")

log = logging.getLogger("aetherflow.core.builtin.connectors")


def _opt(options: dict, *keys: str, default=None):
    cur = options
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


class _Base:
    """Small concrete base for built-in connectors (keeps init consistent)."""

    def __init__(self, init: ConnectorInit):
        self.name = init.name
        self.kind = init.kind
        self.driver = init.driver
        self.config = init.config or {}
        self.options = init.options or {}
        self.ctx = init.ctx

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.close()
        except Exception as e:
            log.warning("non-critical connector operation failed; continuing", exc_info=True)


@register_connector("rest", "httpx")
class HttpxREST(_Base):
    """
    REST connector backed by httpx.

    MUST-HAVE:
      - client()/async_client() + lifecycle
      - request primitives supporting json/data/files/content
      - timeout/retry config from resource options
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._sync = None
        self._async = None

    def _timeout(self) -> float:
        return float(_opt(self.options, "timeout", default=_opt(self.options, "timeouts", "total", default=30)) or 30)

    def _verify_ssl(self) -> bool:
        return bool(_opt(self.options, "verify_ssl", default=True))

    def _retries(self) -> int:
        return int(_opt(self.options, "retry", "max_attempts", default=_opt(self.options, "retries", default=0)) or 0)

    def base_url(self) -> str:
        return (self.config.get("base_url") or "").rstrip("/")

    def headers(self) -> dict:
        h = dict(self.config.get("headers") or {})
        token = self.config.get("bearer_token")
        if token:
            h.setdefault("Authorization", f"Bearer {token}")
        return h

    def client(self):
        import httpx
        if self._sync is None:
            self._sync = httpx.Client(
                base_url=self.base_url(),
                headers=self.headers(),
                timeout=self._timeout(),
                verify=self._verify_ssl(),
            )
        return self._sync

    def async_client(self):
        import httpx
        if self._async is None:
            self._async = httpx.AsyncClient(
                base_url=self.base_url(),
                headers=self.headers(),
                timeout=self._timeout(),
                verify=self._verify_ssl(),
            )
        return self._async

    def close(self) -> None:
        try:
            if self._sync is not None:
                self._sync.close()
        finally:
            self._sync = None
        try:
            if self._async is not None:
                import anyio
                # best-effort close (sync context); allow event loop users to manage their own
                try:
                    anyio.run(self._async.aclose)
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)
        finally:
            self._async = None

    def request(self, method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                json: Any | None = None, data: Any | None = None, files: Any | None = None, content: bytes | None = None,
                timeout: float | None = None):
        """
        Sync request primitive.
        """
        import time
        import httpx

        attempts = max(1, 1 + self._retries())

        def _do_request():
            return self.client().request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                json=json,
                data=data,
                files=files,
                content=content,
                timeout=timeout or self._timeout(),
            )

        # Prefer tenacity when available for predictable retry/backoff.
        if attempts > 1:
            try:
                from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type  # type: ignore

                @retry(
                    stop=stop_after_attempt(attempts),
                    wait=wait_exponential(multiplier=1, min=1, max=5),
                    retry=retry_if_exception_type(httpx.HTTPError),
                    reraise=True,
                )
                def _wrapped():
                    return _do_request()

                return _wrapped()
            except Exception:
                # Fall back to a small local loop if tenacity isn't installed.
                pass

        last_exc = None
        for i in range(attempts):
            try:
                return _do_request()
            except httpx.HTTPError as e:
                last_exc = e
                if i + 1 >= attempts:
                    break
                time.sleep(min(2 ** i, 5))
        raise ConnectorError(f"REST request failed after {attempts} attempt(s): {method} {url}") from last_exc

    # Convenience aliases
    def get(self, url: str, **kw): return self.request("GET", url, **kw)
    def post(self, url: str, **kw): return self.request("POST", url, **kw)
    def put(self, url: str, **kw): return self.request("PUT", url, **kw)
    def delete(self, url: str, **kw): return self.request("DELETE", url, **kw)


@register_connector("mail", "smtp")
class SMTPMail(_Base):
    """Mail connector backed by smtplib (stdlib).

    MUST-HAVE:
      - client() + lifecycle (close)
      - send_plaintext / send_html primitives
      - timeout/retry config from resource options

    Config keys (resource.config):
      - host (required)
      - port (default 587)
      - username (optional)
      - password (optional)
      - starttls (default true when port==587)
      - from_addr (default: username)
    Options (resource.options):
      - timeout (seconds, default 30)
      - retry.max_attempts (default 1)
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._smtp = None

    def _timeout(self) -> float:
        return float(_opt(self.options, "timeout", default=30) or 30)

    def _retries(self) -> int:
        return int(_opt(self.options, "retry", "max_attempts", default=1) or 1)

    def _starttls(self) -> bool:
        if "starttls" in self.config:
            return bool(self.config.get("starttls"))
        # sensible default
        return int(self.config.get("port", 587)) == 587

    def _from_addr(self) -> str:
        return str(self.config.get("from_addr") or self.config.get("username") or "")

    def client(self):
        import smtplib

        if self._smtp is not None:
            return self._smtp

        host = self.config.get("host")
        if not host:
            raise ConnectorError("mail.smtp requires config.host")
        port = int(self.config.get("port", 587))

        smtp = smtplib.SMTP(host=host, port=port, timeout=self._timeout())
        smtp.ehlo()
        if self._starttls():
            try:
                smtp.starttls()
                smtp.ehlo()
            except Exception as e:
                raise ConnectorError("SMTP STARTTLS failed") from e

        user = self.config.get("username")
        pwd = self.config.get("password")
        if user and pwd:
            try:
                smtp.login(user, pwd)
            except Exception as e:
                raise ConnectorError("SMTP login failed") from e

        self._smtp = smtp
        return self._smtp

    def close(self) -> None:
        if self._smtp is None:
            return
        try:
            try:
                self._smtp.quit()
            except Exception:
                self._smtp.close()
        finally:
            self._smtp = None

    def _send(self, msg, *, to_addrs: list[str] | None = None) -> None:
        import time
        attempts = max(1, self._retries())
        last_exc = None
        for i in range(attempts):
            try:
                if to_addrs:
                    self.client().send_message(msg, to_addrs=to_addrs)
                else:
                    self.client().send_message(msg)
                return
            except Exception as e:
                last_exc = e
                # reset client between attempts
                try:
                    self.close()
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)
                if i + 1 >= attempts:
                    break
                time.sleep(min(2 ** i, 5))
        raise ConnectorError(f"SMTP send failed after {attempts} attempt(s)") from last_exc

    def send_plaintext(self, *, to: list[str] | str, subject: str, body: str,
                       from_addr: str | None = None, cc: list[str] | str | None = None,
                       bcc: list[str] | str | None = None) -> None:
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr or self._from_addr()
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        if cc:
            msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
        # BCC is not set as header by default; still used as recipients
        msg.set_content(body)

        recipients: list[str] = []
        recipients += (to if isinstance(to, list) else [to])
        if cc:
            recipients += (cc if isinstance(cc, list) else [cc])
        if bcc:
            recipients += (bcc if isinstance(bcc, list) else [bcc])

        self._send(msg, to_addrs=recipients)

    def send_html(self, *, to: list[str] | str, subject: str, html: str,
                  text: str | None = None, from_addr: str | None = None,
                  cc: list[str] | str | None = None, bcc: list[str] | str | None = None) -> None:
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr or self._from_addr()
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        if cc:
            msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
        # Plaintext fallback
        msg.set_content(text or "")
        msg.add_alternative(html, subtype="html")

        recipients: list[str] = []
        recipients += (to if isinstance(to, list) else [to])
        if cc:
            recipients += (cc if isinstance(cc, list) else [cc])
        if bcc:
            recipients += (bcc if isinstance(bcc, list) else [bcc])

        self._send(msg, to_addrs=recipients)


@register_connector("sftp", "paramiko")
class ParamikoSFTP(_Base):
    """
    SFTP connector backed by paramiko.

    MUST-HAVE:
      - session() + lifecycle
      - read/write/list/delete/mkdir primitives
      - recursive helpers (mkdir_recursive, delete_recursive)
    """

    def _connect(self):
        import paramiko
        host = self.config["host"]
        port = int(self.config.get("port", 22))
        user = self.config["user"]
        password = self.config.get("password")
        pkey_path = self.config.get("pkey_path")
        timeout = int(_opt(self.options, "timeout", default=30) or 30)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if pkey_path:
            key = paramiko.RSAKey.from_private_key_file(pkey_path)
            ssh.connect(host, port=port, username=user, pkey=key, timeout=timeout)
        else:
            ssh.connect(host, port=port, username=user, password=password, timeout=timeout)
        return ssh, ssh.open_sftp()

    @contextmanager
    def session(self):
        ssh, sftp = self._connect()
        try:
            yield sftp
        finally:
            try:
                sftp.close()
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
            try:
                ssh.close()
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)

    def read_bytes(self, remote_path: str) -> bytes:
        with self.session() as sftp:
            with sftp.open(remote_path, "rb") as f:
                return f.read()

    def write_bytes(self, remote_path: str, data: bytes) -> None:
        import posixpath
        with self.session() as sftp:
            self.mkdir_recursive(posixpath.dirname(remote_path), sftp=sftp)
            with sftp.open(remote_path, "wb") as f:
                f.write(data)

    def download(self, remote_path: str, local_path: str) -> None:
        with self.session() as sftp:
            sftp.get(remote_path, local_path)

    def upload(self, local_path: str, remote_path: str) -> None:
        import posixpath
        with self.session() as sftp:
            self.mkdir_recursive(posixpath.dirname(remote_path), sftp=sftp)
            sftp.put(local_path, remote_path)

    def list(self, remote_dir: str) -> list[RemoteFileMeta]:
        """
            sftp: paramiko.SFTPClient
            remote_dir: "/path/on/server"
        """
        import stat
        out: list[RemoteFileMeta] = []
        with self.session() as sftp:
            for attr in sftp.listdir_attr(remote_dir):
                name = attr.filename
                if name in (".", ".."):
                    continue
                is_dir = stat.S_ISDIR(attr.st_mode)
                out.append(
                    RemoteFileMeta(
                        path=f"{remote_dir.rstrip('/')}/{name}",
                        name=name,
                        is_dir=is_dir,
                        size=None if is_dir else attr.st_size,
                        mtime=int(attr.st_mtime) if attr.st_mtime else None,
                    )
                )
        return out

    def delete(self, remote_path: str) -> None:
        with self.session() as sftp:
            try:
                sftp.remove(remote_path)
            except IOError:
                # might be dir
                sftp.rmdir(remote_path)

    def mkdir(self, remote_dir: str) -> None:
        with self.session() as sftp:
            sftp.mkdir(remote_dir)

    # NICE-TO-HAVE
    def mkdir_recursive(self, remote_dir: str, *, sftp=None) -> None:
        import posixpath
        close = False
        if sftp is None:
            close = True
            cm = self.session()
            sftp = cm.__enter__()
        try:
            if remote_dir in ("", "/"):
                return
            parts = []
            d = remote_dir
            while d not in ("", "/"):
                parts.append(d)
                d = posixpath.dirname(d)
            for p in reversed(parts):
                try:
                    sftp.stat(p)
                except Exception:
                    try:
                        sftp.mkdir(p)
                    except Exception as e:
                        log.warning("non-critical connector operation failed; continuing", exc_info=True)
        finally:
            if close:
                cm.__exit__(None, None, None)

    def delete_recursive(self, remote_path: str) -> None:
        # best-effort recursive delete
        import posixpath
        with self.session() as sftp:
            def _is_dir(p: str) -> bool:
                try:
                    return bool(getattr(sftp.stat(p), "st_mode", 0) & 0o040000)
                except Exception:
                    return False
            def _walk(p: str):
                try:
                    for name in sftp.listdir(p):
                        child = posixpath.join(p, name)
                        if _is_dir(child):
                            _walk(child)
                        else:
                            try:
                                sftp.remove(child)
                            except Exception as e:
                                log.warning("non-critical connector operation failed; continuing", exc_info=True)
                    try:
                        sftp.rmdir(p)
                    except Exception as e:
                        log.warning("non-critical connector operation failed; continuing", exc_info=True)
                except Exception:
                    try:
                        sftp.remove(p)
                    except Exception:
                        try:
                            sftp.rmdir(p)
                        except Exception as e:
                            log.warning("non-critical connector operation failed; continuing", exc_info=True)
            _walk(remote_path)


@dataclass(frozen=True)
class ColumnMeta:
    name: str
    # canonical python-ish type name
    dtype: str  # "bool"|"int"|"float"|"string"|"date"|"datetime"|"bytes"|"decimal" (optional)
    nullable: bool | None = None
    precision: int | None = None
    scale: int | None = None
    db_type: str | None = None  # raw db type name if known

@dataclass(frozen=True)
class FetchMeta:
    columns: list[ColumnMeta]
    # keep raw desc around for debugging if you want
    raw: Any | None = None

@dataclass(frozen=True)
class FetchResult:
    meta: FetchMeta
    rows: Iterator[tuple]


# ----------------------------
# Shared helpers (drop into core/utils)
# ----------------------------

def _pytype_from_decl(db_type: str | None, *, scale: int | None = None) -> type:
    """
    Best-effort mapping from DB type string -> python type.
    Keep it conservative. Unknown -> object.
    """
    t = (db_type or "").lower()

    # scale is the strongest hint for numerics
    if isinstance(scale, int):
        return int if scale == 0 else Decimal  # safer than float for money-like numerics

    if any(x in t for x in ("bool", "boolean")):
        return bool
    if "timestamp" in t or "datetime" in t:
        return _dt.datetime
    if "date" in t:
        return _dt.date
    if any(x in t for x in ("int", "integer", "bigint", "smallint")):
        return int
    if any(x in t for x in ("decimal", "number", "numeric")):
        return Decimal
    if any(x in t for x in ("float", "double", "real")):
        return float
    if any(x in t for x in ("binary", "blob", "bytea", "varbinary")):
        return bytes
    if any(x in t for x in ("char", "text", "string", "varchar")):
        return str

    return object


def _pytype_from_value(v: Any) -> Optional[type]:
    if v is None:
        return None
    if isinstance(v, bool):
        return bool
    if isinstance(v, int) and not isinstance(v, bool):
        return int
    if isinstance(v, float):
        return float
    if isinstance(v, Decimal):
        return Decimal
    if isinstance(v, _dt.datetime):
        return _dt.datetime
    if isinstance(v, _dt.date):
        return _dt.date
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes
    if isinstance(v, str):
        return str
    return object


def _iter_fetchmany(fetchmany_fn, size: int) -> Iterator[tuple]:
    while True:
        chunk = fetchmany_fn(size)
        if not chunk:
            break
        for r in chunk:
            yield r


def _sample_and_chain(it: Iterator[tuple], sample_size: int) -> Tuple[List[tuple], Iterator[tuple]]:
    sample: List[tuple] = []
    base = it
    try:
        for _ in range(sample_size):
            sample.append(next(base))
    except StopIteration:
        pass

    def chained() -> Iterator[tuple]:
        for r in sample:
            yield r
        for r in base:
            yield r

    return sample, chained()


def _infer_pytypes_from_sample(cols: List[str], sample_rows: List[tuple]) -> List[type]:
    out: List[type] = [object for _ in cols]
    for i, _c in enumerate(cols):
        t0: Optional[type] = None
        for r in sample_rows:
            v = r[i] if i < len(r) else None
            tt = _pytype_from_value(v)
            if tt and tt is not object:
                t0 = tt
                break
        out[i] = t0 or object
    return out


def _dbapi_cols_types_from_description(desc: Any) -> Tuple[List[str], List[type]]:
    """
    DB-API cursor.description is usually:
      (name, type_code, display_size, internal_size, precision, scale, null_ok)
    BUT type_code varies wildly. We treat it as string-ish.
    """
    cols: List[str] = []
    pytypes: List[type] = []
    if not desc:
        return cols, pytypes

    for d in desc:
        try:
            name = str(d[0])
        except Exception:
            continue
        type_code = d[1] if len(d) > 1 else None
        scale = d[5] if len(d) > 5 else None

        # best-effort: many drivers put a class or int in type_code
        db_type = None
        try:
            db_type = type_code.__name__  # if class/type
        except Exception:
            db_type = str(type_code) if type_code is not None else None

        cols.append(name)
        pytypes.append(_pytype_from_decl(db_type, scale=scale if isinstance(scale, int) else None))

    return cols, pytypes


@register_connector("db", "sqlalchemy")
class SQLAlchemyDB(_Base):
    """
    Generic SQLAlchemy DB connector.

    MUST-HAVE:
      - engine()/connect() + lifecycle
      - execute()/read() primitives
      - pooling config from resource options
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._engine = None

    def engine(self):
        import sqlalchemy as sa
        if self._engine is None:
            pool_cfg = self.options.get("pool") or {}
            # allow legacy flat options too
            pool_size = int(pool_cfg.get("size", self.options.get("pool_size", 5)))
            max_overflow = int(pool_cfg.get("max_overflow", self.options.get("max_overflow", 10)))
            recycle = int(pool_cfg.get("recycle_seconds", self.options.get("pool_recycle", 1800)))
            pre_ping = bool(pool_cfg.get("pre_ping", self.options.get("pool_pre_ping", True)))
            connect_args = self.options.get("connect_args") or {}
            self._engine = sa.create_engine(
                self.config["url"],
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=pre_ping,
                pool_recycle=recycle,
                connect_args=connect_args,
            )
        return self._engine

    @contextmanager
    def connect(self):
        # transaction-aware connection (BEGIN/COMMIT)
        eng = self.engine()
        with eng.begin() as conn:
            yield conn

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.dispose()
            finally:
                self._engine = None

    def execute(self, sql: str, params: dict | None = None) -> int:
        import sqlalchemy as sa
        with self.connect() as conn:
            res = conn.execute(sa.text(sql), params or {})
            try:
                return int(res.rowcount or 0)
            except Exception:
                return 0

    def read(self, sql: str, params: dict | None = None) -> Tuple[list[str], list[tuple]]:
        import sqlalchemy as sa
        with self.engine().connect() as conn:
            res = conn.execute(sa.text(sql), params or {})
            cols = list(res.keys())
            rows = res.fetchall()
            return cols, rows

    # Back-compat
    def fetchall(self, sql: str, params: dict | None = None):
        return self.read(sql, params)

    def fetchmany(self, sql: str, params: Mapping[str, Any] | None, *, fetch_size: int, sample_size: int = 200):
        conn = self.connect()  # whatever you return: Engine/Connection wrapper
        # You REALLY want to do text(sql) in your connector, but keep generic:
        res = conn.execute(sql, params or {})  # if this fails, wrap in text(sql) in this connector
        try:
            cols = list(res.keys()) if hasattr(res, "keys") else []
        except Exception:
            cols = []

        # SQLAlchemy result usually supports fetchmany
        if hasattr(res, "fetchmany") and callable(getattr(res, "fetchmany")):
            it0 = _iter_fetchmany(res.fetchmany, int(fetch_size))
        else:
            it0 = iter(res)

        # SQLAlchemy type metadata is messy; sample for pytypes
        sample, it = _sample_and_chain(it0, sample_size)
        if not cols and sample:
            cols = [f"col_{i+1}" for i in range(len(sample[0]))]
        pytypes = _infer_pytypes_from_sample(cols, sample)

        def gen():
            try:
                yield from it
            finally:
                try:
                    if hasattr(res, "close"):
                        res.close()
                except Exception:
                    pass
                try:
                    if hasattr(conn, "close"):
                        conn.close()
                except Exception:
                    pass

        return cols, gen(), pytypes


@register_connector("db", "sqlite3")
class SQLiteDB(_Base):
    """Lightweight SQLite connector using the stdlib.

    This exists so aetherflow-core can support simple DB-backed assets and local
    workflows without pulling in SQLAlchemy as a hard dependency.

    Config:
      - path: /path/to/db.sqlite
      - or url: sqlite:///path/to/db.sqlite
    """

    def _path(self) -> str:
        url = (self.config.get("url") or "").strip()
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        p = self.config.get("path")
        if p:
            return str(p)
        if url == "sqlite:///:memory:" or url == ":memory:":
            return ":memory:"
        raise ConnectorError("SQLite connector requires config.path or config.url")

    def connect(self):
        import sqlite3
        # Allow use across threads if step implements its own concurrency.
        return sqlite3.connect(self._path(), check_same_thread=False)

    def read(self, sql: str, params: dict | None = None):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params or {})
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchall()

    def fetchall(self, sql: str, params: dict | None = None):
        return self.read(sql, params)

    def fetchmany(self, sql: str, params: Mapping[str, Any] | None, *, fetch_size: int, sample_size: int = 200):
        conn = self.connect()
        cur = conn.cursor()
        try:
            try:
                cur.arraysize = int(fetch_size)
            except Exception:
                pass

            cur.execute(sql, params or {})
            cols, pytypes = _dbapi_cols_types_from_description(getattr(cur, "description", None))

            it0 = _iter_fetchmany(cur.fetchmany, int(fetch_size))
            # if metadata weak -> sample
            if (not pytypes) or all(t is object or t is str for t in pytypes):
                sample, it = _sample_and_chain(it0, sample_size)
                if not cols and sample:
                    cols = [f"col_{i+1}" for i in range(len(sample[0]))]
                pytypes = _infer_pytypes_from_sample(cols, sample)
            else:
                it = it0

            def gen():
                try:
                    yield from it
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass

            return cols, gen(), pytypes
        except Exception:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            raise

@register_connector("db", "duckdb")
class DuckDB(SQLiteDB):
    """DuckDB connector (optional dependency).

    This connector is intentionally small and DB-API-like.

    Config:
      - path: /path/to/db.duckdb (default :memory:)
      - read_only: bool (default false)
    Options:
      - pragmas: dict[str, Any] (executed as PRAGMA key=value)
      - extensions: list[str] (duckdb extensions to INSTALL/LOAD)
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._conn = None

    def _require(self):
        try:
            import duckdb  # noqa: F401
        except Exception as e:
            raise ConnectorError("DuckDB connector requires optional dependency: duckdb") from e

    def connect(self):
        self._require()
        import duckdb
        if self._conn is None:
            path = str(self.config.get("path") or ":memory:")
            ro = bool(self.config.get("read_only", False))
            self._conn = duckdb.connect(database=path, read_only=ro)

            # Best-effort extensions.
            exts = self.options.get("extensions") or []
            for ext in exts:
                try:
                    self._conn.execute(f"INSTALL {ext}")
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)
                try:
                    self._conn.execute(f"LOAD {ext}")
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)

            pragmas = self.options.get("pragmas") or {}
            for k, v in pragmas.items():
                try:
                    self._conn.execute(f"PRAGMA {k}={json.dumps(v) if isinstance(v, (dict, list, str)) else v}")
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)

        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
            self._conn = None

    def execute(self, sql: str, params: dict | None = None) -> int:
        conn = self.connect()
        cur = conn.execute(sql, params or {})
        try:
            return int(cur.rowcount or 0)
        except Exception:
            return 0

    def read(self, sql: str, params: dict | None = None) -> Tuple[list[str], list[tuple]]:
        conn = self.connect()
        cur = conn.execute(sql, params or {})
        cols = [d[0] for d in (cur.description or [])]
        rows = cur.fetchall()
        return cols, rows

    def fetchall(self, sql: str, params: dict | None = None):
        return self.read(sql, params)


@register_connector("db", "postgres")
class PostgresDB(SQLAlchemyDB):
    """Alias for SQLAlchemyDB (use a postgres URL)."""
    pass


@register_connector("db", "mysql")
class MySQLDB(SQLAlchemyDB):
    """Alias for SQLAlchemyDB (use a mysql URL)."""
    pass


@register_connector("db", "oracledb")
class OracleDB(SQLiteDB):
    """
    Oracle connector backed by python-oracledb.

    MUST-HAVE:
      - connect() + lifecycle
      - execute()/read() primitives
      - pooling config from resource options
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._pool = None
        self._init_client()

    def _init_client(self):
        import oracledb
        lib_dir = _opt(self.options, "oracle", "lib_dir", default=self.options.get("lib_dir"))
        if lib_dir:
            try:
                oracledb.init_oracle_client(lib_dir=lib_dir)
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)

    def _pool_get(self):
        import oracledb
        pool_cfg = self.options.get("pool") or {}
        enabled = bool(pool_cfg.get("enabled", self.options.get("pool_enabled", True)))
        if not enabled:
            return None
        if self._pool is None:
            size = int(pool_cfg.get("size", self.options.get("pool_size", 4)))
            self._pool = oracledb.create_pool(
                user=self.config["user"],
                password=self.config["password"],
                dsn=self.config["dsn"],
                min=1,
                max=max(1, size),
                increment=1,
                getmode=oracledb.POOL_GETMODE_WAIT,
            )
        return self._pool

    @contextmanager
    def connect(self):
        import oracledb
        pool = self._pool_get()
        if pool:
            conn = pool.acquire()
            try:
                yield conn
            finally:
                try:
                    pool.release(conn)
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)
        else:
            conn = oracledb.connect(user=self.config["user"], password=self.config["password"], dsn=self.config["dsn"])
            try:
                yield conn
            finally:
                try:
                    conn.close()
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._pool.close()
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
            self._pool = None

    def execute(self, sql: str, params: dict | None = None) -> int:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params or {})
            try:
                rc = int(cur.rowcount or 0)
            except Exception:
                rc = 0
            try:
                conn.commit()
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
            return rc

    def read(self, sql: str, params: dict | None = None) -> Tuple[list[str], list[tuple]]:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.arraysize = int(_opt(self.options, "arraysize", default=5000) or 5000)
            cur.execute(sql, params or {})
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchall()

    # Back-compat
    def fetchall(self, sql: str, params: dict | None = None):
        return self.read(sql, params)


@register_connector("db", "exasol")
class ExasolDB(_Base):
    """
    Exasol connector backed by pyexasol (optional dependency).

    Notes:
      - pyexasol is NOT DB-API: no cursor()
      - use conn.execute() -> statement
      - statement can fetchmany/fetchall/iter depending on version
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._conn = None

    def _require(self):
        try:
            import pyexasol  # noqa: F401
        except Exception as e:
            raise ConnectorError("Exasol connector requires optional dependency: pyexasol") from e

    def connect_raw(self):
        self._require()
        import pyexasol

        if self._conn is None:
            kwargs = {}
            timeout = _opt(self.options, "timeout", default=None)
            if timeout is not None:
                kwargs["timeout"] = int(timeout)

            schema = self.config.get("schema") or None  # avoid schema=None

            if schema:
                self._conn = pyexasol.connect(
                    dsn=self.config["dsn"],
                    user=self.config["user"],
                    password=self.config["password"],
                    schema=schema,
                    **kwargs,
                )
            else:
                self._conn = pyexasol.connect(
                    dsn=self.config["dsn"],
                    user=self.config["user"],
                    password=self.config["password"],
                    **kwargs,
                )
        return self._conn

    @contextmanager
    def connect(self):
        conn = self.connect_raw()
        try:
            yield conn
        finally:
            # keep for reuse; caller may call close()
            pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
            self._conn = None

    def _stmt_close(self, stmt) -> None:
        for m in ("close", "free", "drop"):
            if hasattr(stmt, m) and callable(getattr(stmt, m)):
                try:
                    getattr(stmt, m)()
                except Exception:
                    pass
                return

    def _stmt_cols_meta(self, stmt) -> Tuple[List[str], List[type]] | None:
        """
        Try to extract (cols, pytypes) from stmt.columns() if it returns list[dict].
        """
        if not (hasattr(stmt, "columns") and callable(getattr(stmt, "columns"))):
            return None
        try:
            meta = stmt.columns()
        except Exception:
            return None
        if not (meta and isinstance(meta, list) and isinstance(meta[0], dict)):
            return None

        cols: List[str] = []
        pytypes: List[type] = []
        for c in meta:
            name = c.get("name")
            if not name:
                continue

            db_type = None
            for k in ("type_name", "type", "sql_type", "data_type"):
                if k in c and c[k] is not None:
                    db_type = str(c[k])
                    break

            scale = c.get("scale") if isinstance(c.get("scale"), int) else None

            cols.append(str(name))
            pytypes.append(_pytype_from_decl(db_type, scale=scale))

        return (cols, pytypes) if cols else None

    def _stmt_cols_only(self, stmt) -> List[str]:
        # 1) stmt.columns() common
        if hasattr(stmt, "columns") and callable(getattr(stmt, "columns")):
            try:
                meta = stmt.columns()
                if meta and isinstance(meta, list):
                    if isinstance(meta[0], dict) and "name" in meta[0]:
                        cols = [str(c["name"]) for c in meta if c.get("name")]
                        if cols:
                            return cols
                    if isinstance(meta[0], str):
                        cols = [str(x) for x in meta]
                        if cols:
                            return cols
            except Exception:
                pass
        # 2) direct attributes
        for attr in ("colnames", "column_names", "columns_names", "names"):
            if hasattr(stmt, attr):
                try:
                    v = getattr(stmt, attr)
                    # could be list, tuple, or property
                    cols = list(v) if not callable(v) else list(v())
                    cols = [str(x) for x in cols if x is not None]
                    if cols:
                        return cols
                except Exception:
                    pass
        # 3) DB-API-like: stmt.description
        if hasattr(stmt, "description"):
            try:
                desc = getattr(stmt, "description")
                if desc:
                    cols = [str(d[0]) for d in desc if d and len(d) > 0]
                    if cols:
                        return cols
            except Exception:
                pass
        # 4) some versions keep metadata under .meta / .metadata / .query_meta
        for attr in ("meta", "metadata", "query_meta"):
            if hasattr(stmt, attr):
                try:
                    m = getattr(stmt, attr)
                    if isinstance(m, dict):
                        # try common keys
                        for k in ("columns", "cols", "column_names"):
                            if k in m and isinstance(m[k], list):
                                cols = [str(x.get("name") if isinstance(x, dict) else x) for x in m[k]]
                                cols = [c for c in cols if c and c != "None"]
                                if cols:
                                    return cols
                except Exception:
                    pass
        return []

    def execute(self, sql: str, params: dict | None = None) -> int:
        with self.connect() as conn:
            stmt = conn.execute(sql, params or {})
            try:
                rc = getattr(stmt, "rowcount", None)
                return int(rc or 0)
            except Exception:
                return 0
            finally:
                self._stmt_close(stmt)

    def read(self, sql: str, params: dict | None = None) -> Tuple[list[str], list[tuple]]:
        with self.connect() as conn:
            stmt = conn.execute(sql, params or {})
            try:
                cols = self._stmt_cols_only(stmt)
                if hasattr(stmt, "fetchall") and callable(getattr(stmt, "fetchall")):
                    rows = stmt.fetchall() or []
                else:
                    rows = list(stmt)  # last resort
                rows = [tuple(r) for r in rows]
                if not cols and rows:
                    cols = [f"col_{i+1}" for i in range(len(rows[0]))]
                return cols, rows
            finally:
                self._stmt_close(stmt)

    def fetchall(self, sql: str, params: dict | None = None):
        return self.read(sql, params)

    def fetchmany(
            self,
            sql: str,
            params: Mapping[str, Any] | None,
            *,
            fetch_size: int,
            sample_size: int = 200,
    ):
        """
        Return (cols, iterator, pytypes) for unified step consumption.
        """
        # Need manual enter/exit because we return a generator that outlives this frame
        cm = self.connect()
        conn = cm.__enter__()
        try:
            stmt = conn.execute(sql, dict(params or {}))

            cols: List[str] = []
            pytypes: List[type] = []

            meta = self._stmt_cols_meta(stmt)
            if meta:
                cols, pytypes = meta
            else:
                cols = self._stmt_cols_only(stmt)

            # Build base iterator
            if hasattr(stmt, "fetchmany") and callable(getattr(stmt, "fetchmany")):
                it0 = _iter_fetchmany(stmt.fetchmany, int(fetch_size))
            elif hasattr(stmt, "__iter__"):
                it0 = (tuple(r) for r in stmt)
            elif hasattr(stmt, "fetchall") and callable(getattr(stmt, "fetchall")):
                def _it_all():
                    for r in (stmt.fetchall() or []):
                        yield tuple(r)
                it0 = _it_all()
            else:
                raise ConnectorError("pyexasol statement does not support fetchmany/fetchall/iteration")

            # If no pytypes from metadata, sample for inference and re-chain iterator
            if not pytypes:
                sample, it = _sample_and_chain(it0, int(sample_size))
                if not cols and sample:
                    cols = [f"col_{i+1}" for i in range(len(sample[0]))]
                    log.warning("Exasol statement did not expose column names; using synthetic col_1..col_N")
                pytypes = _infer_pytypes_from_sample(cols, sample)
            else:
                it = it0

            # Clamp pytypes to cols
            if cols and len(pytypes) != len(cols):
                pytypes = (pytypes + [object] * len(cols))[: len(cols)]

            def gen():
                try:
                    for r in it:
                        yield tuple(r)
                finally:
                    self._stmt_close(stmt)
                    try:
                        cm.__exit__(None, None, None)
                    except Exception:
                        pass

            return cols, gen(), pytypes

        except Exception:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass
            raise


@register_connector("smb", "smbclient")
class SMBClient(_Base):
    """
    SMB connector using smbclient (python-smbclient). Optional dependency.

    Config example:
      server: "fileserver"
      share: "DATA"
      username: "u"
      password: "p"
      port: 445
    """

    def _require(self):
        try:
            import smbclient  # noqa: F401
        except Exception as e:
            raise ConnectorError("SMB connector requires optional dependency: smbclient (python-smbclient)") from e

    def _register(self):
        self._require()
        import smbclient
        server = self.config["server"]
        username = self.config.get("username") or self.config.get("user")
        password = self.config.get("password")
        port = int(self.config.get("port", 445))
        timeout = int(_opt(self.options, "timeout", default=30) or 30)
        smbclient.register_session(server, username=username, password=password, port=port, connection_timeout=timeout)


    def _path(self, p: str) -> str:
        """Build a UNC path for smbclient.

        Supported input forms:
          - Relative path inside a share: "dir/file.txt"
          - Absolute-ish path inside a share: "/dir/file.txt" or "\\dir\\file.txt"
          - UNC path: r"\\server\\share\\dir\\file.txt" (passed through)
          - Share-prefixed path: "SHARE:/dir/file.txt" or "SHARE:\\dir\\file.txt" (overrides config.share)
          - Drive path: "A:\\B\\C\\D\\E.txt" (drive prefix stripped; uses config.share)
        """
        raw = str(p).strip()

        # 1) UNC path full: \\server\share\...
        if _UNC_RE.match(raw):
            return raw

        share = self.config.get("share")

        # 2) SHARE:/path or SHARE:\path (override share, avoid drive letter)
        m = _SHARE_OVERRIDE_RE.match(raw)
        if m and len(m.group(1)) != 1:  # avoid "C:/..." likeas share
            share = m.group(1)
            raw = m.group(2)

        # 3) Drive letter: C:\dir\file or C:/dir/file
        if _DRIVE_RE.match(raw):
            raw = raw[2:]            # remove "C:"
            raw = raw.lstrip("\\/")  # remove slash after drive

        if not share:
            raise ConnectorError(
                "SMB path requires a share (set config.share or use 'SHARE:/path' form)"
            )

        # 4) Normalize: slash → backslash, remove leading slash/backslash
        rel = raw.lstrip("\\/").replace("/", "\\")

        server = self.config["server"]
        if rel:
            return f"\\\\{server}\\{share}\\{rel}"
        # nếu p -> root share
        return f"\\\\{server}\\{share}"

    def read_bytes(self, remote_path: str) -> bytes:
        self._register()
        import smbclient
        with smbclient.open_file(self._path(remote_path), mode="rb") as f:
            return f.read()

    def write_bytes(self, remote_path: str, data: bytes) -> None:
        self._register()
        import smbclient
        self.mkdir_recursive(self._dirname(remote_path))
        with smbclient.open_file(self._path(remote_path), mode="wb") as f:
            f.write(data)

    def upload(self, local_path: str, remote_path: str) -> None:
        self._register()
        import smbclient
        import shutil
        self.mkdir_recursive(self._dirname(remote_path))
        with open(local_path, "rb") as src, smbclient.open_file(self._path(remote_path), mode="wb") as dst:
            shutil.copyfileobj(src, dst)

    def download(self, remote_path: str, local_path: str) -> None:
        self._register()
        import smbclient
        import shutil
        with smbclient.open_file(self._path(remote_path), mode="rb") as src, open(local_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    def list(self, remote_dir: str) -> list[RemoteFileMeta]:
        """
        remote_dir: e.g. r"\\server\\share\\folder"
        """
        self._register()
        import smbclient
        p = self._path(remote_dir)
        # pysmb expects leading slash
        out: list[RemoteFileMeta] = []
        for entry in smbclient.scandir(p):
            if entry.name in (".", ".."):
                continue
            is_dir = entry.is_dir()
            stat_info = entry.stat()
            out.append(
                RemoteFileMeta(
                    path=entry.path,
                    name=entry.name,
                    is_dir=is_dir,
                    size=None if is_dir else stat_info.st_size,
                    mtime=int(stat_info.st_mtime) if stat_info else None,
                )
            )
        return out

    def delete(self, remote_path: str) -> None:
        self._register()
        import smbclient
        p = self._path(remote_path)
        try:
            smbclient.remove(p)
        except Exception:
            smbclient.rmdir(p)

    def mkdir(self, remote_dir: str) -> None:
        self._register()
        import smbclient
        smbclient.mkdir(self._path(remote_dir))

    # NICE-TO-HAVE
    def _dirname(self, p: str) -> str:
        p = p.replace("\\\\", "/").replace("\\", "/")
        if "/" not in p:
            return ""
        return p.rsplit("/", 1)[0]

    def mkdir_recursive(self, remote_dir: str) -> None:
        if not remote_dir:
            return
        self._register()
        import smbclient
        parts = [x for x in remote_dir.replace("\\\\", "/").replace("\\", "/").split("/") if x]
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}" if cur else part
            try:
                smbclient.mkdir(self._path(cur))
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)

    def delete_recursive(self, remote_path: str) -> None:
        self._register()
        import smbclient
        p = self._path(remote_path)
        # best-effort recursion
        try:
            for entry in smbclient.scandir(p):
                child = entry.path
                try:
                    if entry.is_dir():
                        self.delete_recursive(child)
                    else:
                        smbclient.remove(child)
                except Exception as e:
                    log.warning("non-critical connector operation failed; continuing", exc_info=True)
            try:
                smbclient.rmdir(p)
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
        except Exception:
            # maybe file
            try:
                smbclient.remove(p)
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)


@register_connector("smb", "pysmb")
class SMBPySMB(_Base):
    """SMB connector using pysmb. Optional dependency.

    This is useful in environments where `python-smbclient` is not available
    (or does not behave well), while still keeping SMB support in core.

    Config example:
      server: "fileserver"            # hostname or IP
      server_name: "FILESERVER"       # optional NetBIOS name (defaults to server)
      share: "DATA"                   # default share
      username: "u"
      password: "p"
      domain: ""                      # optional
      port: 445
      client_name: "aetherflow"       # optional (defaults to 'aetherflow')
    """

    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self._conn = None

    def _require(self) -> None:
        try:
            from smb.SMBConnection import SMBConnection  # noqa: F401
        except Exception as e:
            raise ConnectorError("SMB pysmb driver requires optional dependency: pysmb") from e

    def _connect(self):
        self._require()
        from smb.SMBConnection import SMBConnection

        if self._conn is not None:
            return self._conn

        server = str(self.config.get("server") or "").strip()
        if not server:
            raise ConnectorError("SMB pysmb requires config.server")
        server_name = str(self.config.get("server_name") or server)
        username = self.config.get("username") or self.config.get("user") or ""
        password = self.config.get("password") or ""
        domain = self.config.get("domain") or ""
        client_name = str(self.config.get("client_name") or "aetherflow")
        port = int(self.config.get("port", 445))

        conn = SMBConnection(
            username,
            password,
            client_name,
            server_name,
            domain=domain,
            use_ntlm_v2=True,
            is_direct_tcp=True,
        )
        ok = conn.connect(server, port)
        if not ok:
            raise ConnectorError(f"SMB pysmb failed to connect to {server}:{port}")
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
            self._conn = None

    def _split_share_path(self, p: str) -> tuple[str, str]:
        """Return (share, path_in_share).
        Supported input forms:
          - "dir/file.txt" (uses config.share)
          - "/dir/file.txt" (uses config.share)
          - "SHARE:/dir/file.txt" (overrides share)
          - "A:\\dir\\file.txt" or "A:/dir/file.txt" (drive prefix stripped; uses config.share)
          - "\\\\host\\SHARE\\dir\\file.txt" (UNC; share inferred from path, unless overridden)
        """
        share = self.config.get("share")
        raw = str(p).strip()

        # 1) UNC full path: \\host\SHARE\dir\file
        if _UNC_RE.match(raw):
            # \\host\SHARE\rest...
            parts = raw.lstrip("\\").split("\\", 2)  # host, share, rest
            if len(parts) >= 2:
                unc_share = parts[1]
                rest = parts[2] if len(parts) == 3 else ""
                # If caller didn't specify share explicitly, infer from UNC
                if not share:
                    share = unc_share
                raw = rest

        # 2) Explicit share override: SHARE:/path or SHARE:\path
        # Accept both ":/" and ":\"
        if ":/" in raw or ":\\" in raw:
            if ":/" in raw:
                prefix, rest = raw.split(":/", 1)
                sep = "/"
            else:
                prefix, rest = raw.split(":\\", 1)
                sep = "\\"
            # Only treat as share override if prefix looks like a share name,
            # AND prefix is not a Windows drive letter (C, D, ...)
            if prefix and all(ch.isalnum() or ch in "_.-" for ch in prefix) and len(prefix) != 1:
                share = prefix
                raw = rest
            else:
                # drive letter case handled below
                raw = prefix + ":" + (sep + rest if rest else "")

        # 3) Drive letter path: A:\dir\file or A:/dir/file -> strip "A:\"
        if _DRIVE_RE.match(raw):
            raw = raw[2:]  # drop "A:"
            raw = raw.lstrip("/\\")  # drop leading slash after drive

        if not share:
            raise ConnectorError(
                f"smb-pysmb path requires a share (set config.share or use 'SHARE:/path') {p}"
            )

        path_in_share = raw.lstrip("/\\").replace("\\", "/")
        return str(share), path_in_share

    def read_bytes(self, remote_path: str) -> bytes:
        conn = self._connect()
        from io import BytesIO

        share, p = self._split_share_path(remote_path)
        bio = BytesIO()
        conn.retrieveFile(share, f"/{p}", bio)
        return bio.getvalue()

    def write_bytes(self, remote_path: str, data: bytes) -> None:
        conn = self._connect()
        from io import BytesIO

        share, p = self._split_share_path(remote_path)
        self.mkdir_recursive(self._dirname(p, share_prefix=share))
        bio = BytesIO(data)
        conn.storeFile(share, f"/{p}", bio)

    def upload(self, local_path: str, remote_path: str) -> None:
        conn = self._connect()
        share, p = self._split_share_path(remote_path)
        self.mkdir_recursive(self._dirname(p, share_prefix=share))
        with open(local_path, "rb") as f:
            conn.storeFile(share, f"/{p}", f)

    def download(self, remote_path: str, local_path: str) -> None:
        conn = self._connect()
        share, p = self._split_share_path(remote_path)
        with open(local_path, "wb") as f:
            conn.retrieveFile(share, f"/{p}", f)

    def list(self, remote_dir: str) -> list[RemoteFileMeta]:
        conn = self._connect()
        share, p = self._split_share_path(remote_dir)
        # pysmb expects leading slash
        entries = conn.listPath(share, f"/{p}" if p else "/")
        out: list[RemoteFileMeta] = []
        for e in entries:
            name = getattr(e, "filename", None)
            if not name or name in {".", ".."}:
                continue
            is_dir = bool(getattr(e, "isDirectory", False))
            out.append(
                RemoteFileMeta(
                    path=f"{remote_dir.rstrip('/')}/{name}",
                    name=name,
                    is_dir=bool(getattr(e, "isDirectory", False)),
                    size=None if is_dir else getattr(e, "file_size", None),
                    mtime=getattr(e, "last_write_time", None),
                )
            )
        return out

    def delete(self, remote_path: str) -> None:
        conn = self._connect()
        share, p = self._split_share_path(remote_path)
        try:
            conn.deleteFiles(share, f"/{p}")
        except Exception:
            try:
                conn.deleteDirectory(share, f"/{p}")
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)

    def mkdir(self, remote_dir: str) -> None:
        conn = self._connect()
        share, p = self._split_share_path(remote_dir)
        conn.createDirectory(share, f"/{p}")

    def _dirname(self, p: str, *, share_prefix: str | None = None) -> str:
        p = str(p).replace("\\", "/").lstrip("/")
        if "/" not in p:
            return f"{share_prefix}:/" if share_prefix else ""
        d = p.rsplit("/", 1)[0]
        return f"{share_prefix}:/{d}" if share_prefix else d

    def mkdir_recursive(self, remote_dir: str) -> None:
        if not remote_dir:
            return
        conn = self._connect()
        share, p = self._split_share_path(remote_dir)
        parts = [x for x in p.replace("\\", "/").split("/") if x]
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}" if cur else part
            try:
                conn.createDirectory(share, f"/{cur}")
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)

    def delete_recursive(self, remote_path: str) -> None:
        conn = self._connect()
        share, p = self._split_share_path(remote_path)
        # Best-effort recursion by listing.
        try:
            entries = conn.listPath(share, f"/{p}" if p else "/")
            for e in entries:
                name = getattr(e, "filename", None)
                if not name or name in {".", ".."}:
                    continue
                child = f"{p}/{name}" if p else str(name)
                if getattr(e, "isDirectory", False):
                    self.delete_recursive(f"{share}:/{child}")
                else:
                    try:
                        conn.deleteFiles(share, f"/{child}")
                    except Exception as e:
                        log.warning("non-critical connector operation failed; continuing", exc_info=True)
            try:
                conn.deleteDirectory(share, f"/{p}")
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)
        except Exception:
            # maybe file
            try:
                conn.deleteFiles(share, f"/{p}")
            except Exception as e:
                log.warning("non-critical connector operation failed; continuing", exc_info=True)


# ---------------------------------------------------------------------------
# Archive connectors (zip/unzip)
# ---------------------------------------------------------------------------


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _norm_base_dir(base_dir: str | Path) -> Path:
    return Path(base_dir).resolve()


def _safe_relpath(fp: Path, base_dir: Path) -> str:
    fp = fp.resolve()
    try:
        rel = fp.relative_to(base_dir)
    except Exception as e:
        raise ConnectorError(f"File '{fp}' is outside base_dir '{base_dir}'") from e
    # ZIP format expects forward slashes
    return rel.as_posix()


class ArchiveBase(_Base):
    """Common helpers for archive connectors."""

    def create_zip(
        self,
        *,
        output: str | Path,
        files: list[Path],
        base_dir: str | Path,
        password: str | None = None,
        compression: str = "deflated",
        overwrite: bool = True,
    ) -> dict:
        raise NotImplementedError

    def extract_zip(
        self,
        *,
        archive: str | Path,
        dest_dir: str | Path,
        password: str | None = None,
        overwrite: bool = True,
        members: list[str] | None = None,
    ) -> dict:
        raise NotImplementedError


@register_connector("archive", "pyzipper")
class PyZipperArchive(ArchiveBase):
    """Archive connector powered by `pyzipper`.

    Supports:
      - create_zip (AES encryption when password is provided)
      - extract_zip (AES + many standard zips)

    Config keys:
      - encryption: "aes" (default: "aes")
        NOTE: pyzipper does NOT support ZipCrypto. For ZipCrypto create, use
        archive:pyminizip or archive:os / archive:external (7z).
      - aes_strength: 128|192|256 (default: 256)
    """

    def _import(self):
        try:
            import pyzipper  # type: ignore

            return pyzipper
        except Exception as e:
            raise ConnectorError(
                "archive.pyzipper requires optional dependency 'pyzipper'. "
                "Install aetherflow-core[zip] (or aetherflow[zip]) to enable it."
            ) from e

    def _encryption(self):
        enc = str(self.config.get("encryption") or "aes").strip().lower()
        if enc in ("", "aes"):
            return "aes"
        if enc == "zipcrypto":
            raise ConnectorError(
                "archive.pyzipper does not support ZipCrypto encryption. "
                "Use archive.pyminizip (ZipCrypto create), archive.os (zip/unzip), "
                "or archive.external / external.process (7z) instead."
            )
        raise ConnectorError("archive.pyzipper config.encryption must be 'aes'")

    def create_zip(
        self,
        *,
        output: str | Path,
        files: list[Path],
        base_dir: str | Path,
        password: str | None = None,
        compression: str = "deflated",
        overwrite: bool = True,
    ) -> dict:
        pyzipper = self._import()
        out_path = Path(output)
        _ensure_parent(out_path)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        if overwrite and out_path.exists():
            out_path.unlink()

        base = _norm_base_dir(base_dir)
        comp = pyzipper.ZIP_DEFLATED if str(compression).lower() == "deflated" else pyzipper.ZIP_STORED

        if password:
            # pyzipper: AES-only when encrypting
            strength = int(self.config.get("aes_strength") or 256)
            if strength not in (128, 192, 256):
                raise ConnectorError("archive.pyzipper config.aes_strength must be 128/192/256")
            # self._encryption() will fail-fast for ZipCrypto
            with pyzipper.AESZipFile(str(tmp), "w", compression=comp, encryption=pyzipper.WZ_AES) as zf:
                zf.setpassword(str(password).encode("utf-8"))
                zf.setencryption(pyzipper.WZ_AES, nbits=strength)
                for fp in files:
                    zf.write(fp, arcname=_safe_relpath(fp, base))
        else:
            with pyzipper.ZipFile(str(tmp), "w", compression=comp) as zf:
                for fp in files:
                    zf.write(fp, arcname=_safe_relpath(fp, base))

        os.replace(tmp, out_path)
        return {"output": str(out_path), "count": len(files), "password": bool(password), "driver": "pyzipper"}

    def extract_zip(
        self,
        *,
        archive: str | Path,
        dest_dir: str | Path,
        password: str | None = None,
        overwrite: bool = True,
        members: list[str] | None = None,
    ) -> dict:
        pyzipper = self._import()
        archive = Path(archive)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        extracted: list[str] = []
        with pyzipper.AESZipFile(str(archive), "r") as zf:
            if password:
                zf.setpassword(str(password).encode("utf-8"))
            names = members if members is not None else zf.namelist()
            for name in names:
                # best-effort overwrite behavior: pyzipper delegates to zipfile
                if not overwrite:
                    target = dest / Path(name)
                    if target.exists():
                        continue
                zf.extract(name, path=str(dest))
                extracted.append(str(name))
        return {"dest_dir": str(dest), "files": extracted, "password": bool(password), "driver": "pyzipper"}


@register_connector("archive", "zipfile")
class StdZipfileArchive(ArchiveBase):
    """Archive connector backed by Python stdlib `zipfile`.

    Notes:
      - create_zip supports NO encryption.
      - extract_zip can read ZipCrypto-encrypted archives if password provided.
    """

    def create_zip(
        self,
        *,
        output: str | Path,
        files: list[Path],
        base_dir: str | Path,
        password: str | None = None,
        compression: str = "deflated",
        overwrite: bool = True,
    ) -> dict:
        if password:
            raise ConnectorError(
                "archive.zipfile does not support writing encrypted ZIPs. "
                "Use archive.pyzipper, archive.pyminizip, archive.os, or external.process (7z) instead."
            )
        out_path = Path(output)
        _ensure_parent(out_path)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        if overwrite and out_path.exists():
            out_path.unlink()

        base = _norm_base_dir(base_dir)
        comp = zipfile.ZIP_DEFLATED if str(compression).lower() == "deflated" else zipfile.ZIP_STORED
        with zipfile.ZipFile(tmp, "w", compression=comp) as zf:
            for fp in files:
                zf.write(fp, arcname=_safe_relpath(fp, base))
        os.replace(tmp, out_path)
        return {"output": str(out_path), "count": len(files), "password": False, "driver": "zipfile"}

    def extract_zip(
        self,
        *,
        archive: str | Path,
        dest_dir: str | Path,
        password: str | None = None,
        overwrite: bool = True,
        members: list[str] | None = None,
    ) -> dict:
        archive = Path(archive)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        extracted: list[str] = []
        with zipfile.ZipFile(str(archive), "r") as zf:
            if password:
                zf.setpassword(str(password).encode("utf-8"))
            names = members if members is not None else zf.namelist()
            for name in names:
                if not overwrite:
                    target = dest / Path(name)
                    if target.exists():
                        continue
                zf.extract(name, path=str(dest))
                extracted.append(str(name))
        return {"dest_dir": str(dest), "files": extracted, "password": bool(password), "driver": "zipfile"}


@register_connector("archive", "os")
class OsZipArchive(ArchiveBase):
    """Archive connector using OS tools: `zip` + `unzip`.

    Config keys:
      - zip_cmd: command name/path (default: "zip")
      - unzip_cmd: command name/path (default: "unzip")
      - quiet: bool (default true)

    Notes:
      - Password uses ZipCrypto via `zip -P` (legacy).
    """

    def _zip_cmd(self) -> str:
        return str(self.config.get("zip_cmd") or "zip")

    def _unzip_cmd(self) -> str:
        return str(self.config.get("unzip_cmd") or "unzip")

    def _ensure_tools(self) -> None:
        if shutil.which(self._zip_cmd()) is None:
            raise ConnectorError(f"archive.os requires '{self._zip_cmd()}' on PATH")
        if shutil.which(self._unzip_cmd()) is None:
            raise ConnectorError(f"archive.os requires '{self._unzip_cmd()}' on PATH")

    def create_zip(
        self,
        *,
        output: str | Path,
        files: list[Path],
        base_dir: str | Path,
        password: str | None = None,
        compression: str = "deflated",
        overwrite: bool = True,
    ) -> dict:
        self._ensure_tools()
        out_path = Path(output)
        _ensure_parent(out_path)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        if overwrite and out_path.exists():
            out_path.unlink()

        base = _norm_base_dir(base_dir)
        rels = [_safe_relpath(fp, base) for fp in files]

        cmd = [self._zip_cmd()]
        if bool(self.config.get("quiet", True)):
            cmd.append("-q")
        cmd.extend(["-r", str(tmp)])
        if password:
            cmd.extend(["-P", str(password)])
        cmd.extend(rels)
        subprocess.run(cmd, cwd=str(base), check=True)
        os.replace(tmp, out_path)
        return {"output": str(out_path), "count": len(files), "password": bool(password), "driver": "os"}

    def extract_zip(
        self,
        *,
        archive: str | Path,
        dest_dir: str | Path,
        password: str | None = None,
        overwrite: bool = True,
        members: list[str] | None = None,
    ) -> dict:
        self._ensure_tools()
        archive = Path(archive)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        cmd = [self._unzip_cmd()]
        if bool(self.config.get("quiet", True)):
            cmd.append("-q")
        cmd.append("-o" if overwrite else "-n")
        if password:
            cmd.extend(["-P", str(password)])
        cmd.append(str(archive))
        if members:
            cmd.extend([str(m) for m in members])
        cmd.extend(["-d", str(dest)])
        subprocess.run(cmd, check=True)
        return {"dest_dir": str(dest), "password": bool(password), "driver": "os"}


@register_connector("archive", "pyminizip")
class PyMiniZipArchive(ArchiveBase):
    """Archive connector using `pyminizip`.

    Supports:
      - create_zip with password (ZipCrypto)

    Limitations:
      - extract_zip is NOT supported (use pyzipper/os/external for unzip)
    """

    def _import(self):
        try:
            import pyminizip  # type: ignore

            return pyminizip
        except Exception as e:
            raise ConnectorError(
                "archive.pyminizip requires optional dependency 'pyminizip'. "
                "Install it and register a resource with kind=archive driver=pyminizip."
            ) from e

    def create_zip(
        self,
        *,
        output: str | Path,
        files: list[Path],
        base_dir: str | Path,
        password: str | None = None,
        compression: str = "deflated",
        overwrite: bool = True,
    ) -> dict:
        if not password:
            raise ConnectorError("archive.pyminizip is intended for encrypted zips; set inputs.password")
        pyminizip = self._import()
        out_path = Path(output)
        _ensure_parent(out_path)
        if overwrite and out_path.exists():
            out_path.unlink()
        base = _norm_base_dir(base_dir)
        # pyminizip takes absolute paths and relative dir names separately
        abs_files = [str(Path(fp).resolve()) for fp in files]
        rel_dirs = [str(Path(fp).resolve().parent.relative_to(base)).replace("\\", "/") for fp in files]
        level = int(self.config.get("level") or 5)
        pyminizip.compress_multiple(abs_files, rel_dirs, str(out_path), str(password), level)
        return {"output": str(out_path), "count": len(files), "password": True, "driver": "pyminizip"}

    def extract_zip(
        self,
        *,
        archive: str | Path,
        dest_dir: str | Path,
        password: str | None = None,
        overwrite: bool = True,
        members: list[str] | None = None,
    ) -> dict:
        raise ConnectorError(
            "archive.pyminizip does not support unzip; use archive.pyzipper, archive.os, or archive.external instead."
        )


@register_connector("archive", "external")
class ExternalArchive(ArchiveBase):
    """Archive connector that shells out to external tools (7z, bsdtar, etc.).

    You control the exact commands via config templates.

    Config keys:
      - zip_cmd: list[str] template
      - unzip_cmd: list[str] template

    Template variables available:
      - {archive} {dest} {password} {base_dir}
      - {files} expands to file list (already relative POSIX paths)

    Example for 7z:
      zip_cmd: ["7z", "a", "-tzip", "{archive}", "{files}"]
      unzip_cmd: ["7z", "x", "-y", "-o{dest}", "{archive}"]
    """

    def _render(self, tmpl: list[str], mapping: dict[str, str]) -> list[str]:
        out: list[str] = []
        for token in tmpl:
            if token == "{files}":
                # Special placeholder; caller should pre-join or expand
                out.append("{files}")
            else:
                out.append(token.format(**mapping))
        return out

    def create_zip(
        self,
        *,
        output: str | Path,
        files: list[Path],
        base_dir: str | Path,
        password: str | None = None,
        compression: str = "deflated",
        overwrite: bool = True,
    ) -> dict:
        out_path = Path(output)
        _ensure_parent(out_path)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        if overwrite and out_path.exists():
            out_path.unlink()

        base = _norm_base_dir(base_dir)
        rels = [_safe_relpath(fp, base) for fp in files]
        tmpl = self.config.get("zip_cmd")
        if not isinstance(tmpl, list) or not tmpl:
            raise ConnectorError("archive.external requires config.zip_cmd (list[str])")
        mapping = {
            "archive": str(tmp),
            "dest": "",
            "password": "" if password is None else str(password),
            "base_dir": str(base),
            "files": " ".join(rels),
        }
        cmd = []
        rendered = self._render([str(x) for x in tmpl], mapping)
        for t in rendered:
            if t == "{files}":
                cmd.extend(rels)
            else:
                cmd.append(t)
        subprocess.run(cmd, cwd=str(base), check=True)
        os.replace(tmp, out_path)
        return {"output": str(out_path), "count": len(files), "password": bool(password), "driver": "external"}

    def extract_zip(
        self,
        *,
        archive: str | Path,
        dest_dir: str | Path,
        password: str | None = None,
        overwrite: bool = True,
        members: list[str] | None = None,
    ) -> dict:
        if members:
            raise ConnectorError("archive.external currently does not support 'members' extraction")
        archive = Path(archive)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        tmpl = self.config.get("unzip_cmd")
        if not isinstance(tmpl, list) or not tmpl:
            raise ConnectorError("archive.external requires config.unzip_cmd (list[str])")
        mapping = {
            "archive": str(archive),
            "dest": str(dest),
            "password": "" if password is None else str(password),
            "base_dir": "",
            "files": "",
        }
        cmd = [str(x) for x in tmpl]
        cmd = [t.format(**mapping) for t in cmd]
        subprocess.run(cmd, check=True)
        return {"dest_dir": str(dest), "password": bool(password), "driver": "external"}