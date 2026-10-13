"""Structured logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_REDACT = re.compile(
    r"(?i)(authorization|api[_-]?key|token|password|secret)(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]+)"
)


class RedactingFormatter(logging.Formatter):
    def __init__(self, as_json: bool) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        msg = _REDACT.sub(r"\1\2***", record.getMessage())
        if not self.as_json:
            record.msg, record.args = msg, None
            return super().format(record)
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str, as_json: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter(as_json))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
