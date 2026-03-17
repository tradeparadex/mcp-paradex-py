"""
Unit tests for the OpenTelemetry telemetry module.
"""

import logging
import os
from unittest.mock import MagicMock, patch


def test_configure_otel_noop_without_endpoint():
    """No OTEL_EXPORTER_OTLP_ENDPOINT → configure_otel() returns False."""
    import mcp_paradex.utils.telemetry as tel

    # Reset module state so we can re-test initialization.
    original = tel._initialized
    tel._initialized = False
    try:
        env = {k: v for k, v in os.environ.items() if k != "OTEL_EXPORTER_OTLP_ENDPOINT"}
        with patch.dict(os.environ, env, clear=True):
            result = tel.configure_otel()
        assert result is False
    finally:
        tel._initialized = original


def test_configure_otel_noop_when_already_initialized():
    """configure_otel() returns _initialized without touching OTel when already run."""
    import mcp_paradex.utils.telemetry as tel

    original = tel._initialized
    tel._initialized = True
    try:
        result = tel.configure_otel()
        assert result is True
    finally:
        tel._initialized = original


def test_trace_context_log_filter_zeros_without_span():
    """TraceContextLogFilter emits zero IDs when no active span is present."""
    from mcp_paradex.utils.telemetry import TraceContextLogFilter

    f = TraceContextLogFilter()
    r = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
    f.filter(r)
    assert r.trace_id == "0" * 32  # type: ignore[attr-defined]
    assert r.span_id == "0" * 16  # type: ignore[attr-defined]


def test_trace_context_log_filter_injects_ids_with_active_span():
    """TraceContextLogFilter injects hex trace/span IDs when a valid span context exists."""
    from mcp_paradex.utils.telemetry import _OTEL_AVAILABLE, TraceContextLogFilter

    if not _OTEL_AVAILABLE:
        return  # skip when OTel not installed

    fake_ctx = MagicMock()
    fake_ctx.is_valid = True
    fake_ctx.trace_id = 0xABCD1234 * (2**96)  # 128-bit
    fake_ctx.span_id = 0xDEADBEEF  # 64-bit

    fake_span = MagicMock()
    fake_span.get_span_context.return_value = fake_ctx

    import mcp_paradex.utils.telemetry as tel

    with patch.object(tel._trace, "get_current_span", return_value=fake_span):
        f = TraceContextLogFilter()
        r = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
        f.filter(r)

    assert len(r.trace_id) == 32  # type: ignore[attr-defined]
    assert len(r.span_id) == 16  # type: ignore[attr-defined]


def test_noop_tracer_start_as_current_span():
    """_NoOpTracer context manager yields None and raises no errors."""
    from mcp_paradex.utils.telemetry import _NoOpTracer

    tracer = _NoOpTracer()
    with tracer.start_as_current_span("test.op", kind=None, attributes={}) as span:
        assert span is None


def test_api_call_span_noop_without_otel(monkeypatch):
    """api_call() completes normally when OTel is not configured."""
    from unittest.mock import AsyncMock

    import mcp_paradex.utils.paradex_client as client_module
    import mcp_paradex.utils.telemetry as tel

    # Ensure OTel is treated as unavailable for this test.
    monkeypatch.setattr(tel, "_OTEL_AVAILABLE", False)

    mock_client = MagicMock()
    mock_client.api_url = "https://api.testnet.paradex.trade/v1"
    mock_client.get = MagicMock(return_value={"results": []})

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        client_module.api_call(mock_client, "markets")
    )
    assert result == {"results": []}
    mock_client.get.assert_called_once()
