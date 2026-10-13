"""Application configuration, validated at startup (fail fast on bad values)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import app_paths

ProviderName = Literal["ollama", "openai"]


class Settings(BaseSettings):
    """Environment-driven settings. All variables use the ``OAI_`` prefix.

    List values must be given as JSON, e.g. ``OAI_HTTP_ALLOWED_HOSTS='["api.local"]'``.
    """

    # Later files win: the per-user config.env overrides a local .env.
    model_config = SettingsConfigDict(
        env_prefix="OAI_",
        env_file=(".env", str(app_paths().config_file)),
        extra="ignore",
    )

    # --- server -----------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    data_dir: Path = Field(default_factory=lambda: app_paths().data)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Host header allow-list protects against DNS-rebinding attacks on a local service.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    api_token: str | None = None
    secret_key: str | None = None
    frontend_dist: Path | None = None
    open_browser: bool = True
    auto_port: bool = True
    manage_runtime: bool = True
    models_dir: Path | None = None

    # --- model defaults (overridable at runtime from the UI) --------------------
    model_provider: ProviderName = "ollama"
    model_base_url: str = "http://localhost:11434"
    model_api_key: str | None = None
    default_model: str | None = None
    model_timeout_s: float = Field(180.0, gt=0)
    ping_timeout_s: float = Field(3.0, gt=0, le=30)
    max_tool_rounds: int = Field(6, ge=1, le=25)

    # --- tools / MCP / connectors ------------------------------------------------
    tool_timeout_s: float = Field(60.0, gt=0)
    tool_result_max_chars: int = Field(20_000, ge=1_000)
    mcp_connect_timeout_s: float = Field(20.0, gt=0)
    mcp_stdio_allowed_commands: list[str] = [
        "npx",
        "uvx",
        "uv",
        "node",
        "python",
        "python3",
        "docker",
        "deno",
        "bunx",
    ]
    http_allowed_hosts: list[str] = []
    max_message_chars: int = Field(32_000, ge=100)

    @field_validator("model_base_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("model_base_url must start with http:// or https://")
        return v.rstrip("/")

    @property
    def db_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'offline_ai.db').resolve()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
