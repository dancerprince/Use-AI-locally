"""Connector adapters. Each connector type validates its config and exposes tools.

To add a new connector type: subclass ``ConnectorAdapter``, define ``Config``,
``secret_fields``, ``tools()`` and ``call()``, then register it in ``CONNECTOR_TYPES``.
"""

from __future__ import annotations

import abc
import asyncio
import builtins
import re
import sqlite3
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..config import Settings
from ..errors import AppError
from ..providers import ToolSpec
from ..security import check_outbound_url, resolve_in_sandbox
from .tooling import exposed_name, to_text, truncate

READ_ONLY_SQL = re.compile(r"^\s*(select|with|explain|pragma\s+table_info|show)\b", re.IGNORECASE)
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|vacuum|grant|revoke|truncate|copy)\b",
    re.IGNORECASE,
)


def ensure_read_only_sql(sql: str) -> str:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise AppError("Only a single SQL statement is allowed", code="sql_forbidden", status=403)
    if not READ_ONLY_SQL.match(stripped) or _FORBIDDEN_SQL.search(stripped):
        raise AppError(
            "Only read-only SELECT queries are allowed", code="sql_forbidden", status=403
        )
    return stripped


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectorAdapter(abc.ABC):
    type: ClassVar[str]
    Config: ClassVar[builtins.type[_Cfg]]
    secret_fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str, config: dict[str, Any], settings: Settings) -> None:
        try:
            self.cfg = self.Config(**config)
        except ValidationError as exc:
            raise AppError(
                f"Invalid config for {self.type} connector",
                code="validation_error",
                status=422,
                details=exc.errors(include_url=False, include_context=False),
            ) from exc
        self.name = name
        self.settings = settings

    @abc.abstractmethod
    def local_tools(self) -> list[ToolSpec]:
        """Tools with *local* names; they are prefixed by ``tools()``."""

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=exposed_name("conn", self.name, t.name),
                description=f"[{self.type} connector '{self.name}'] {t.description}",
                parameters=t.parameters,
            )
            for t in self.local_tools()
        ]

    def resolve(self, exposed: str) -> str | None:
        for t in self.local_tools():
            if exposed_name("conn", self.name, t.name) == exposed:
                return t.name
        return None

    @abc.abstractmethod
    async def call(self, tool: str, args: dict[str, Any]) -> Any: ...

    @abc.abstractmethod
    async def test(self) -> str: ...

    async def run(self, tool: str, args: dict[str, Any]) -> str:
        result = await asyncio.wait_for(self.call(tool, args), self.settings.tool_timeout_s)
        return truncate(to_text(result), self.settings.tool_result_max_chars)


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


# ============================================================================ HTTP / REST
class HttpConnector(ConnectorAdapter):
    type = "http"
    secret_fields = ("headers",)

    class Config(_Cfg):
        base_url: str
        headers: dict[str, str] = Field(default_factory=dict)
        allowed_methods: list[str] = Field(default_factory=lambda: ["GET"])
        timeout_s: float = Field(20, gt=0, le=120)

        @field_validator("base_url")
        @classmethod
        def _u(cls, v: str) -> str:
            if not v.startswith(("http://", "https://")):
                raise ValueError("base_url must be http(s)")
            return v.rstrip("/")

        @field_validator("allowed_methods")
        @classmethod
        def _m(cls, v: list[str]) -> list[str]:
            ok = {"GET", "POST", "PUT", "PATCH", "DELETE"}
            out = [m.upper() for m in v]
            if not out or any(m not in ok for m in out):
                raise ValueError(f"allowed_methods must be a subset of {sorted(ok)}")
            return out

    cfg: Config

    def local_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "request",
                f"Call the REST API at {self.cfg.base_url}. Allowed methods: {', '.join(self.cfg.allowed_methods)}.",
                _obj(
                    {
                        "method": {"type": "string", "enum": self.cfg.allowed_methods},
                        "path": {
                            "type": "string",
                            "description": "Path relative to the base URL, e.g. /items?id=1",
                        },
                        "body": {"type": "object", "description": "Optional JSON body"},
                    },
                    ["method", "path"],
                ),
            )
        ]

    def _url(self, path: str) -> str:
        if "://" in path or path.startswith("//"):
            raise AppError(
                "path must be relative to the connector base_url", code="url_forbidden", status=403
            )
        url = f"{self.cfg.base_url}/{path.lstrip('/')}"
        return check_outbound_url(url, self.settings.http_allowed_hosts)

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        method = str(args.get("method", "GET")).upper()
        if method not in self.cfg.allowed_methods:
            raise AppError(
                f"Method {method} is not allowed for this connector",
                code="method_forbidden",
                status=403,
            )
        url = self._url(str(args.get("path", "/")))
        async with httpx.AsyncClient(timeout=self.cfg.timeout_s, follow_redirects=False) as client:
            resp = await client.request(
                method, url, headers=self.cfg.headers, json=args.get("body")
            )
        try:
            body: Any = resp.json()
        except ValueError:
            body = resp.text
        return {"status": resp.status_code, "body": body}

    async def test(self) -> str:
        check_outbound_url(self.cfg.base_url, self.settings.http_allowed_hosts)
        async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
            resp = await client.get(self.cfg.base_url, headers=self.cfg.headers)
        return f"HTTP {resp.status_code} from {self.cfg.base_url}"


# ============================================================================ Webhook
class WebhookConnector(ConnectorAdapter):
    type = "webhook"
    secret_fields = ("headers",)

    class Config(_Cfg):
        url: str
        headers: dict[str, str] = Field(default_factory=dict)
        description: str = "Send a JSON payload to a webhook."

        @field_validator("url")
        @classmethod
        def _u(cls, v: str) -> str:
            if not v.startswith(("http://", "https://")):
                raise ValueError("url must be http(s)")
            return v

    cfg: Config

    def local_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "send",
                self.cfg.description,
                _obj({"payload": {"type": "object", "description": "JSON payload"}}, ["payload"]),
            )
        ]

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        url = check_outbound_url(self.cfg.url, self.settings.http_allowed_hosts)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=args.get("payload", {}), headers=self.cfg.headers)
        return {"status": resp.status_code, "body": resp.text[:2000]}

    async def test(self) -> str:
        check_outbound_url(self.cfg.url, self.settings.http_allowed_hosts)
        return f"Webhook URL {self.cfg.url} is valid (no request sent)"


# ============================================================================ Filesystem
class FilesystemConnector(ConnectorAdapter):
    type = "filesystem"

    class Config(_Cfg):
        root: str
        allow_write: bool = False
        max_file_bytes: int = Field(1_000_000, ge=1, le=50_000_000)

        @field_validator("root")
        @classmethod
        def _r(cls, v: str) -> str:
            p = Path(v).expanduser()
            if not p.is_absolute():
                raise ValueError("root must be an absolute path")
            if p.resolve() == Path("/"):
                raise ValueError("root must not be the filesystem root")
            return str(p)

    cfg: Config

    @property
    def root(self) -> Path:
        p = Path(self.cfg.root)
        if not p.is_dir():
            raise AppError(f"Connector root '{p}' does not exist", code="not_found", status=404)
        return p

    def local_tools(self) -> list[ToolSpec]:
        path = {"path": {"type": "string", "description": "Path relative to the connector root"}}
        tools = [
            ToolSpec(
                "list_dir", f"List entries of a directory inside {self.cfg.root}.", _obj(path, [])
            ),
            ToolSpec(
                "read_file", f"Read a UTF-8 text file inside {self.cfg.root}.", _obj(path, ["path"])
            ),
        ]
        if self.cfg.allow_write:
            tools.append(
                ToolSpec(
                    "write_file",
                    f"Create or overwrite a text file inside {self.cfg.root}.",
                    _obj({**path, "content": {"type": "string"}}, ["path", "content"]),
                )
            )
        return tools

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        return await asyncio.to_thread(self._call_sync, tool, args)

    def _call_sync(self, tool: str, args: dict[str, Any]) -> Any:
        root = self.root
        target = resolve_in_sandbox(root, str(args.get("path") or "."))
        if tool == "list_dir":
            if not target.is_dir():
                raise AppError("Not a directory", code="not_found", status=404)
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:500]
            return [
                {
                    "name": e.name,
                    "type": "dir" if e.is_dir() else "file",
                    "size": e.stat().st_size if e.is_file() else None,
                }
                for e in entries
            ]
        if tool == "read_file":
            if not target.is_file():
                raise AppError("File not found", code="not_found", status=404)
            if target.stat().st_size > self.cfg.max_file_bytes:
                raise AppError("File exceeds max_file_bytes", code="too_large", status=413)
            return target.read_text(encoding="utf-8", errors="replace")
        if tool == "write_file" and self.cfg.allow_write:
            content = str(args.get("content", ""))
            if len(content.encode()) > self.cfg.max_file_bytes:
                raise AppError("Content exceeds max_file_bytes", code="too_large", status=413)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} chars to {target.relative_to(root.resolve())}"
        raise AppError(f"Unknown tool '{tool}'", code="not_found", status=404)

    async def test(self) -> str:
        n = len(list(self.root.iterdir()))
        return f"Root {self.cfg.root} is accessible ({n} entries)"


# ============================================================================ SQLite
class SqliteConnector(ConnectorAdapter):
    type = "sqlite"

    class Config(_Cfg):
        path: str
        max_rows: int = Field(200, ge=1, le=10_000)
        timeout_s: float = Field(10, gt=0, le=120)

    cfg: Config

    def local_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec("list_tables", "List tables and their columns.", _obj({}, [])),
            ToolSpec(
                "query",
                f"Run a read-only SQL SELECT (max {self.cfg.max_rows} rows).",
                _obj({"sql": {"type": "string"}}, ["sql"]),
            ),
        ]

    def _connect(self) -> sqlite3.Connection:
        p = Path(self.cfg.path).expanduser().resolve()
        if not p.is_file():
            raise AppError(f"SQLite file '{p}' not found", code="not_found", status=404)
        # mode=ro at the driver level -> writes are impossible regardless of SQL text.
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=self.cfg.timeout_s)
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, tool: str, args: dict[str, Any]) -> Any:
        conn = self._connect()
        try:
            if tool == "list_tables":
                names = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                ]
                return {n: [c[1] for c in conn.execute(f'PRAGMA table_info("{n}")')] for n in names}
            if tool == "query":
                sql = ensure_read_only_sql(str(args.get("sql", "")))
                cur = conn.execute(sql)
                rows = cur.fetchmany(self.cfg.max_rows)
                return {
                    "columns": [d[0] for d in cur.description or []],
                    "rows": [list(r) for r in rows],
                }
        finally:
            conn.close()
        raise AppError(f"Unknown tool '{tool}'", code="not_found", status=404)

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        return await asyncio.to_thread(self._run, tool, args)

    async def test(self) -> str:
        tables = await asyncio.to_thread(self._run, "list_tables", {})
        return f"Connected; {len(tables)} tables"


# ============================================================================ Postgres
class PostgresConnector(ConnectorAdapter):
    type = "postgres"
    secret_fields = ("dsn",)

    class Config(_Cfg):
        dsn: str
        max_rows: int = Field(200, ge=1, le=10_000)
        statement_timeout_ms: int = Field(10_000, ge=100, le=300_000)

    cfg: Config

    def local_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec("list_tables", "List tables in the public schema.", _obj({}, [])),
            ToolSpec(
                "query",
                f"Run a read-only SQL SELECT (max {self.cfg.max_rows} rows).",
                _obj({"sql": {"type": "string"}}, ["sql"]),
            ),
        ]

    async def _query(self, sql: str) -> dict[str, Any]:
        try:
            import asyncpg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AppError("Install the 'postgres' extra (asyncpg) to use this connector") from exc
        conn = await asyncpg.connect(self.cfg.dsn, timeout=10)
        try:
            async with conn.transaction(readonly=True):
                await conn.execute(
                    f"SET LOCAL statement_timeout = {int(self.cfg.statement_timeout_ms)}"
                )
                rows = await conn.fetch(
                    f"SELECT * FROM ({sql}) AS q LIMIT {int(self.cfg.max_rows)}"
                )
        finally:
            await conn.close()
        cols = list(rows[0].keys()) if rows else []
        return {"columns": cols, "rows": [list(r.values()) for r in rows]}

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        if tool == "list_tables":
            return await self._query(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        if tool == "query":
            sql = ensure_read_only_sql(str(args.get("sql", "")))
            if not sql.lower().startswith(("select", "with")):
                raise AppError(
                    "Only SELECT/WITH queries are supported", code="sql_forbidden", status=403
                )
            return await self._query(sql)
        raise AppError(f"Unknown tool '{tool}'", code="not_found", status=404)

    async def test(self) -> str:
        res = await self.call("list_tables", {})
        return f"Connected; {len(res['rows'])} tables"


CONNECTOR_TYPES: dict[str, builtins.type[ConnectorAdapter]] = {
    c.type: c
    for c in (
        HttpConnector,
        WebhookConnector,
        FilesystemConnector,
        SqliteConnector,
        PostgresConnector,
    )
}


def build_connector(
    type_: str, name: str, config: dict[str, Any], settings: Settings
) -> ConnectorAdapter:
    cls = CONNECTOR_TYPES.get(type_)
    if cls is None:
        raise AppError(f"Unknown connector type '{type_}'", code="validation_error", status=422)
    return cls(name, config, settings)
