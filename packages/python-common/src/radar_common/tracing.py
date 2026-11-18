"""Allowlisted span names and events. Never export request bodies, headers or exceptions."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

propagator = TraceContextTextMapPropagator()


@lru_cache
def providers(pid: int, service: str) -> tuple[TracerProvider, LoggerProvider]:
    resource = Resource.create({"service.name": service})
    tracer = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(0.1)))
    logger = LoggerProvider(resource=resource)
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        tracer.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(timeout=2)))
        logger.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(timeout=2)))
    return tracer, logger


def trace_headers() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagator.inject(carrier)
    return carrier


@contextmanager
def span(service: str, name: str, parent: str | None = None) -> Iterator[None]:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        yield
        return
    provider, logs = providers(os.getpid(), service)
    context = propagator.extract({"traceparent": parent}) if parent else None
    with provider.get_tracer("radar").start_as_current_span(
        name, context=context, record_exception=False, set_status_on_exception=False
    ) as active:
        try:
            yield
        except BaseException:
            active.set_status(trace.StatusCode.ERROR)
            raise
        finally:
            if active.is_recording():
                logs.get_logger("radar").emit(body=name, attributes={"radar.event": "finished"})
