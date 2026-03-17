"""OpenTelemetry SDK setup. All symbols are safe to import/call when OTel is not installed."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

try:
    from opentelemetry import trace as _trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import SpanKind

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

    class SpanKind:  # type: ignore[no-redef]
        CLIENT = None


logger = logging.getLogger(__name__)
_initialized = False


class _TracerProtocol(Protocol):
    """Minimal tracer interface satisfied by both OTel Tracer and _NoOpTracer."""

    def start_as_current_span(
        self, name: str, **kwargs: object
    ) -> AbstractContextManager[object]: ...


def configure_otel() -> bool:
    """Init OTel SDK. Returns True if configured, False (no-op) otherwise."""
    global _initialized
    if _initialized or not _OTEL_AVAILABLE:
        return _initialized
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    from mcp_paradex import __version__

    resource = Resource.create(
        {
            SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "mcp-paradex"),
            SERVICE_VERSION: os.getenv("OTEL_SERVICE_VERSION", __version__),
            "deployment.environment": os.getenv("PARADEX_ENVIRONMENT", "prod"),
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
    )
    _trace.set_tracer_provider(provider)
    _initialized = True
    logger.info(
        "OTel configured service=%s endpoint=%s",
        os.getenv("OTEL_SERVICE_NAME", "mcp-paradex"),
        endpoint,
    )
    return True


def get_tracer(name: str = "mcp_paradex") -> _TracerProtocol:
    """Return a tracer (no-op when OTel not available/configured)."""
    if not _OTEL_AVAILABLE:
        return _NoOpTracer()
    from mcp_paradex import __version__

    return _trace.get_tracer(name, __version__)  # type: ignore[return-value]


class TraceContextLogFilter(logging.Filter):
    """Injects trace_id and span_id from the active OTel span into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _OTEL_AVAILABLE:
            span = _trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                record.trace_id = format(ctx.trace_id, "032x")  # type: ignore[attr-defined]
                record.span_id = format(ctx.span_id, "016x")  # type: ignore[attr-defined]
                return True
        record.trace_id = "0" * 32  # type: ignore[attr-defined]
        record.span_id = "0" * 16  # type: ignore[attr-defined]
        return True


class _NoOpTracer:
    """Stand-in when opentelemetry is not installed."""

    @contextmanager  # type: ignore[misc]
    def start_as_current_span(self, *_: object, **__: object) -> Iterator[None]:
        yield None
