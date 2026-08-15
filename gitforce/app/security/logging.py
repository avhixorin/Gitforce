from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class SecretFilter(logging.Filter):
    """Scrubs configured secret values from log records (section 44)."""

    def __init__(self, patterns: tuple[str, ...]) -> None:
        super().__init__()
        self._patterns = patterns

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._patterns:
            return True
        message = record.getMessage()
        for pattern in self._patterns:
            import re

            message = re.sub(pattern, "[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Structured JSON log records for machine parsing (Phase 12)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("task_id", "agent", "trace_id", "span_id", "outcome"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    *,
    structured: bool = True,
    secret_patterns: tuple[str, ...] = (),
) -> None:
    """Configure root logging with optional structured JSON output and a
    secret-scrubbing filter (Phase 12 / section 44)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if structured:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    if secret_patterns:
        handler.addFilter(SecretFilter(secret_patterns))
    root.handlers = [handler]


def get_task_logger(name: str, task_id: str | None = None, agent: str | None = None):
    """Logger bound to task/agent context for structured logs."""
    logger: logging.Logger | logging.LoggerAdapter = logging.getLogger(name)
    if task_id:
        logger = logging.LoggerAdapter(logger, {"task_id": task_id})
    if agent:
        logger = logging.LoggerAdapter(logger, {"agent": agent})
    return logger
