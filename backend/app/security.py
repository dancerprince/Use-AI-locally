"""Secret encryption, masking, path sandboxing and outbound URL checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .errors import AppError

MASK = "••••••••"


class Crypto:
    """Symmetric encryption for secrets at rest (Fernet / AES-128-CBC + HMAC)."""

    def __init__(self, settings: Settings) -> None:
        key = (
            settings.secret_key.encode()
            if settings.secret_key
            else self._load_or_create(settings.data_dir / "secret.key")
        )
        try:
            self._fernet = Fernet(key)
        except ValueError as exc:  # pragma: no cover - config error
            raise RuntimeError("OAI_SECRET_KEY must be a valid Fernet key") from exc

    @staticmethod
    def _load_or_create(path: Path) -> bytes:
        if path.exists():
            return path.read_bytes().strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        return key

    def encrypt_json(self, data: Any) -> str:
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt_json(self, token: str | None, default: Any = None) -> Any:
        if not token:
            return {} if default is None else default
        try:
            return json.loads(self._fernet.decrypt(token.encode()))
        except InvalidToken as exc:
            raise AppError(
                "Stored secrets could not be decrypted (was the secret key changed?)",
                code="secret_decrypt_failed",
                status=500,
            ) from exc


def mask_values(values: dict[str, str]) -> dict[str, str]:
    return {k: MASK for k in values}


def merge_masked(new: dict[str, str], old: dict[str, str]) -> dict[str, str]:
    """Keep the previously stored value where the client sent back the mask."""
    return {k: (old.get(k, "") if v == MASK else v) for k, v in new.items()}


def resolve_in_sandbox(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``; reject traversal and symlink escapes."""
    if "\x00" in relative:
        raise AppError("Invalid path", code="path_forbidden", status=403)
    root_r = root.resolve(strict=True)
    candidate = (root_r / relative).resolve()
    if candidate != root_r and root_r not in candidate.parents:
        raise AppError("Path escapes the connector root", code="path_forbidden", status=403)
    return candidate


def check_outbound_url(url: str, allowed_hosts: list[str]) -> str:
    """Validate scheme and (optionally) host against the global allow-list."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise AppError("Only absolute http(s) URLs are allowed", code="url_forbidden", status=400)
    if allowed_hosts and parts.hostname.lower() not in {h.lower() for h in allowed_hosts}:
        raise AppError(
            f"Host '{parts.hostname}' is not in OAI_HTTP_ALLOWED_HOSTS",
            code="url_forbidden",
            status=403,
        )
    return url
