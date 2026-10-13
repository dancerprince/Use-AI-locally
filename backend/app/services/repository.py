"""CRUD for MCP servers, connectors and skills, handling secret encryption/masking."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..config import Settings
from ..errors import ConflictError, NotFoundError
from ..models import Connector, McpServer, Skill, utcnow
from ..schemas import ConnectorIn, McpServerIn, SkillIn
from ..security import MASK, Crypto, merge_masked
from .connectors import CONNECTOR_TYPES, ConnectorAdapter, build_connector
from .mcp_manager import McpConfig


class Repository:
    def __init__(self, session: Session, crypto: Crypto, settings: Settings) -> None:
        self.s = session
        self.crypto = crypto
        self.settings = settings

    def _commit(self, obj: Any, what: str) -> None:
        self.s.add(obj)
        try:
            self.s.commit()
        except IntegrityError as exc:
            self.s.rollback()
            raise ConflictError(f"A {what} with that name already exists") from exc
        self.s.refresh(obj)

    # ------------------------------------------------------------ MCP servers
    def list_mcp(self) -> list[McpServer]:
        return list(self.s.exec(select(McpServer).order_by(McpServer.name)))

    def get_mcp(self, sid: int) -> McpServer:
        row = self.s.get(McpServer, sid)
        if not row:
            raise NotFoundError("MCP server")
        return row

    def mcp_secrets(self, row: McpServer) -> dict[str, dict[str, str]]:
        data = self.crypto.decrypt_json(row.secrets_enc)
        return {"env": data.get("env", {}), "headers": data.get("headers", {})}

    def save_mcp(self, data: McpServerIn, row: McpServer | None = None) -> McpServer:
        old = self.mcp_secrets(row) if row else {"env": {}, "headers": {}}
        row = row or McpServer(name=data.name, transport=data.transport)
        row.name, row.transport, row.enabled = data.name, data.transport, data.enabled
        row.command = data.command if data.transport == "stdio" else None
        row.args = list(data.args) if data.transport == "stdio" else []
        row.url = data.url if data.transport != "stdio" else None
        row.secrets_enc = self.crypto.encrypt_json(
            {
                "env": merge_masked(dict(data.env), old["env"]),
                "headers": merge_masked(dict(data.headers), old["headers"]),
            }
        )
        row.updated_at = utcnow()
        self._commit(row, "MCP server")
        return row

    def delete(self, row: Any) -> None:
        self.s.delete(row)
        self.s.commit()

    def mcp_config(self, row: McpServer) -> McpConfig:
        sec = self.mcp_secrets(row)
        assert row.id is not None
        return McpConfig(
            id=row.id,
            name=row.name,
            transport=row.transport,
            command=row.command,
            args=list(row.args or []),
            env=sec["env"],
            url=row.url,
            headers=sec["headers"],
        )

    # ------------------------------------------------------------ connectors
    def list_connectors(self) -> list[Connector]:
        return list(self.s.exec(select(Connector).order_by(Connector.name)))

    def get_connector(self, cid: int) -> Connector:
        row = self.s.get(Connector, cid)
        if not row:
            raise NotFoundError("Connector")
        return row

    def connector_config(self, row: Connector) -> dict[str, Any]:
        return self.crypto.decrypt_json(row.config_enc)

    def masked_connector_config(self, row: Connector) -> dict[str, Any]:
        cfg = dict(self.connector_config(row))
        for f in CONNECTOR_TYPES[row.type].secret_fields:
            if f in cfg:
                cfg[f] = {k: MASK for k in cfg[f]} if isinstance(cfg[f], dict) else MASK
        return cfg

    def save_connector(self, data: ConnectorIn, row: Connector | None = None) -> Connector:
        cfg = dict(data.config)
        if row is not None and row.type == data.type:
            old = self.connector_config(row)
            for f in CONNECTOR_TYPES[data.type].secret_fields:
                if isinstance(cfg.get(f), dict) and isinstance(old.get(f), dict):
                    cfg[f] = merge_masked(cfg[f], old[f])
                elif cfg.get(f) == MASK:
                    cfg[f] = old.get(f)
        adapter = build_connector(data.type, data.name, cfg, self.settings)  # validates
        row = row or Connector(name=data.name, type=data.type, config_enc="")
        row.name, row.type, row.enabled = data.name, data.type, data.enabled
        row.config_enc = self.crypto.encrypt_json(adapter.cfg.model_dump())
        row.updated_at = utcnow()
        self._commit(row, "connector")
        return row

    def adapter(self, row: Connector) -> ConnectorAdapter:
        return build_connector(row.type, row.name, self.connector_config(row), self.settings)

    # ------------------------------------------------------------ skills
    def list_skills(self) -> list[Skill]:
        return list(self.s.exec(select(Skill).order_by(Skill.name)))

    def get_skill(self, sid: int) -> Skill:
        row = self.s.get(Skill, sid)
        if not row:
            raise NotFoundError("Skill")
        return row

    def save_skill(self, data: SkillIn, row: Skill | None = None) -> Skill:
        row = row or Skill(name=data.name)
        for k, v in data.model_dump().items():
            setattr(row, k, v)
        row.updated_at = utcnow()
        self._commit(row, "skill")
        return row
