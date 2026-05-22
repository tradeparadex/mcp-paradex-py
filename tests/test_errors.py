"""
Tests for the ParadexApiError helper.
"""

from unittest.mock import AsyncMock

import pytest

from mcp_paradex.utils.errors import ParadexApiError, _extract_error, check_response


@pytest.fixture()
def ctx():
    c = AsyncMock()
    return c


async def test_check_response_passthrough_on_success(ctx):
    resp = {"results": [{"x": 1}], "total": 1}
    assert await check_response(ctx, resp, path="positions") is resp
    ctx.error.assert_not_called()


async def test_check_response_raises_on_string_error(ctx):
    with pytest.raises(ParadexApiError) as exc_info:
        await check_response(ctx, {"error": "rate limited"}, path="orders")
    err = exc_info.value
    assert err.message == "rate limited"
    assert err.path == "orders"
    assert err.code is None
    assert "rate limited" in str(err)
    assert "path=orders" in str(err)
    ctx.error.assert_called_once()


async def test_check_response_raises_on_nested_code_message(ctx):
    with pytest.raises(ParadexApiError) as exc_info:
        await check_response(
            ctx,
            {"error": {"code": "INSUFFICIENT_MARGIN", "message": "not enough collateral"}},
            path="orders",
        )
    err = exc_info.value
    assert err.code == "INSUFFICIENT_MARGIN"
    assert err.message == "not enough collateral"
    assert "code=INSUFFICIENT_MARGIN" in str(err)


async def test_check_response_handles_top_level_message_code(ctx):
    with pytest.raises(ParadexApiError) as exc_info:
        await check_response(
            ctx, {"message": "bad input", "code": "VALIDATION_ERROR"}, path="margin"
        )
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.message == "bad input"


async def test_check_response_ignores_non_dict(ctx):
    # Lists / strings / None are returned untouched — they're already the result.
    assert await check_response(ctx, [1, 2, 3], path="x") == [1, 2, 3]
    assert await check_response(ctx, None, path="x") is None
    ctx.error.assert_not_called()


def test_paradex_api_error_string_repr():
    err = ParadexApiError("boom", path="orders", status=429, code="RATE_LIMITED")
    s = str(err)
    assert "path=orders" in s
    assert "status=429" in s
    assert "code=RATE_LIMITED" in s
    assert "boom" in s


def test_extract_error_recognises_envelopes():
    assert _extract_error({"error": "x"}) == (None, "x")
    assert _extract_error({"error": {"code": "C", "message": "M"}}) == ("C", "M")
    assert _extract_error({}) == (None, None)
    assert _extract_error({"results": []}) == (None, None)
    assert _extract_error("not a dict") == (None, None)
