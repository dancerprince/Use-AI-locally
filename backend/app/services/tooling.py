"""Shared helpers for exposing tools to the model."""

from __future__ import annotations

import json
import re
from typing import Any

_INVALID = re.compile(r"[^a-zA-Z0-9_-]")


def exposed_name(prefix: str, owner: str, tool: str) -> str:
    """Build an OpenAI/Ollama-safe function name: ``^[a-zA-Z0-9_-]{1,64}$``."""
    name = f"{prefix}__{_INVALID.sub('_', owner)}__{_INVALID.sub('_', tool)}"
    return name[:64]


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"


def to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except (TypeError, ValueError):
        return str(value)
