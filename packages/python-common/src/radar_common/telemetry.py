import json
import logging
import re
import time
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radar_common.tracing import span

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_valid_id = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def safe_id(value: str) -> str:
    return value if _valid_id.fullmatch(value) else uuid4().hex


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Allowlisted fields only: no raw exception, SQL, headers, URL credentials or task payload.
        payload: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.msg if record.name.startswith("radar") else "runtime_log",
            "correlation_id": getattr(record, "correlation_id", correlation_id.get()),
        }
        for key in ("service", "job_id", "status", "duration_ms", "error_type", "attempts"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        current = trace.get_current_span().get_span_context()
        if current.is_valid:
            payload["trace_id"] = format(current.trace_id, "032x")
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(handlers=[handler], level=logging.INFO, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "celery.task"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


class CorrelationMiddleware:
    def __init__(self, app: ASGIApp, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        request_id = safe_id(headers.get(b"x-request-id", b"").decode("ascii", errors="ignore"))
        token = correlation_id.set(request_id)
        started = time.monotonic()
        status = 0

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            if scope.get("path") == "/graphql":
                parent = headers.get(b"traceparent", b"").decode("ascii", errors="ignore")
                with span(self.service, "graphql." + scope["type"], parent):
                    await self.app(scope, receive, send_with_id)
            else:
                await self.app(scope, receive, send_with_id)
        finally:
            logging.getLogger("radar.http").info(
                "request_finished",
                extra={
                    "service": self.service,
                    "status": status,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            correlation_id.reset(token)


def task_headers(headers: Mapping[str, Any] | None) -> str:
    return safe_id(str((headers or {}).get("x-request-id", "")))
