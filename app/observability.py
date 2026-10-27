"""Structured JSON logging and request correlation identifiers."""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_CONFIGURED_MARKER = "_semiconductor_json_handler"

_STANDARD_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(request_id: str) -> Any:
    return _request_id.set(request_id)


def reset_request_id(token: Any) -> None:
    _request_id.reset(token)


def new_request_id() -> str:
    return uuid.uuid4().hex


def normalize_request_id(value: str | None) -> str:
    """Keep client-provided correlation IDs short and log-safe."""
    if not value:
        return new_request_id()

    cleaned = "".join(
        character
        for character in value.strip()
        if (
            character.isascii()
            and character.isalnum()
        ) or character in "-_."
    )
    return cleaned[:128] or new_request_id()


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            if key == "request_id":
                continue

            if isinstance(value, (bytes, Path)):
                value = str(value)
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


def configure_logging(level: str | None = None) -> None:
    root_logger = logging.getLogger()

    if getattr(root_logger, _CONFIGURED_MARKER, False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel((level or settings.log_level).upper())
    setattr(root_logger, _CONFIGURED_MARKER, True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

