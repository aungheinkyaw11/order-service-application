import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": getattr(record, "service", self.service),
            "event": getattr(record, "event", record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        order_id = getattr(record, "order_id", None)
        if order_id:
            payload["order_id"] = str(order_id)
        error = getattr(record, "error", None)
        if error:
            payload["error"] = str(error)
        image_version = getattr(record, "image_version", None)
        if image_version:
            payload["image_version"] = str(image_version)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    request_id: str | None = None,
    order_id: Any | None = None,
    error: Any | None = None,
    image_version: str | None = None,
    exc_info: bool = False,
) -> None:
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "request_id": request_id,
            "order_id": order_id,
            "error": error,
            "image_version": image_version,
        },
        exc_info=exc_info,
    )
