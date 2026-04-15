"""
Protocol-level integration tests using the MCP SDK's in-memory client/server.

These tests exercise the full MCP protocol stack (JSON-RPC framing, session
initialization, tool schema generation, content serialization) via
``create_connected_server_and_client_session``.  The Paradex HTTP client is
still mocked — the point is to verify protocol correctness, not network calls.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import mcp_paradex.utils.paradex_client as _client_module
from mcp_paradex.server.server import server

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_client():
    """Unauthenticated Paradex client mock (public tools)."""
    client = MagicMock()
    client.account = None
    client.api_url = "https://api.testnet.paradex.trade/v1"
    with patch.object(_client_module, "_paradex_client", client):
        yield client


@pytest.fixture()
def auth_client(mock_client):
    """Authenticated Paradex client mock (account / order tools)."""
    mock_client.account = MagicMock()
    return mock_client


# ---------------------------------------------------------------------------
# Protocol smoke tests
# ---------------------------------------------------------------------------


async def test_session_initializes():
    """The server completes the MCP initialization handshake."""
    async with create_connected_server_and_client_session(server) as client:
        # If we got here, initialization succeeded
        assert client is not None


async def test_list_tools_returns_all_registered():
    """tools/list returns every tool registered on the FastMCP server."""
    async with create_connected_server_and_client_session(server) as client:
        result = await client.list_tools()
        tool_names = {t.name for t in result.tools}

        # Spot-check a representative set of tools across categories
        expected = {
            "paradex_system_config",
            "paradex_system_state",
            "paradex_markets",
            "paradex_market_summaries",
            "paradex_orderbook",
            "paradex_klines",
            "paradex_trades",
            "paradex_bbo",
            "paradex_vaults",
            "paradex_account_summary",
            "paradex_account_positions",
            "paradex_open_orders",
            "paradex_create_order",
            "paradex_cancel_orders",
            "paradex_generate_subkey",
        }
        missing = expected - tool_names
        assert not missing, f"Tools missing from protocol listing: {missing}"


async def test_tool_schemas_have_descriptions():
    """Every tool returned by list_tools has a non-empty description."""
    async with create_connected_server_and_client_session(server) as client:
        result = await client.list_tools()
        for tool in result.tools:
            assert tool.description, f"Tool {tool.name!r} has no description"


async def test_tool_schemas_have_input_schema():
    """Every tool exposes a JSON Schema for its input parameters."""
    async with create_connected_server_and_client_session(server) as client:
        result = await client.list_tools()
        for tool in result.tools:
            assert tool.inputSchema is not None, f"Tool {tool.name!r} has no input schema"
            assert tool.inputSchema.get("type") == "object", (
                f"Tool {tool.name!r} input schema type is not 'object'"
            )


async def test_call_public_tool_via_protocol(mock_client):
    """Call a public tool through the full protocol and verify the response."""
    mock_client.fetch_system_state.return_value = {"status": "ok"}
    mock_client.fetch_system_time.return_value = {"server_time": 1700000000000}

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("paradex_system_state", {})
        assert result.content
        # Structured output: may have multiple text parts (human-readable + JSON)
        text_parts = [c.text for c in result.content if hasattr(c, "text")]
        assert text_parts, "Expected at least one text content block"
        # Find the JSON part (may be the only one or the second one)
        data = None
        for part in text_parts:
            try:
                data = json.loads(part)
                break
            except json.JSONDecodeError:
                continue
        assert data is not None, f"No JSON found in response: {text_parts}"
        assert data["status"] == "ok"


async def test_call_tool_with_structured_output(mock_client):
    """Tools returning structured output serialize correctly over the protocol."""
    mock_client.fetch_markets.return_value = {
        "results": [
            {
                "symbol": "ETH-USD-PERP",
                "base_currency": "ETH",
                "quote_currency": "USD",
                "settlement_currency": "USDC",
                "order_size_increment": "0.001",
                "price_tick_size": "0.01",
                "min_notional": "1.0",
                "open_at": 0,
                "expiry_at": 0,
                "asset_kind": "PERP",
                "market_kind": "cross",
                "position_limit": "500.0",
                "price_bands_width": "0.05",
                "max_open_orders": 50,
                "max_funding_rate": "0.0003",
                "delta1_cross_margin_params": {},
                "option_cross_margin_params": {},
                "price_feed_id": "",
                "oracle_ewma_factor": "0.0",
                "max_order_size": "5000.0",
                "max_funding_rate_change": "0.0001",
                "max_tob_spread": "0.01",
                "interest_rate": "0.0",
                "clamp_rate": "0.0",
                "funding_period_hours": 8,
                "tags": [],
                "option_type": None,
                "strike_price": "0.0",
                "iv_bands_width": "0.0",
            }
        ]
    }

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("paradex_markets", {"market": "ETH-USD-PERP", "filter": ""})
        assert result.content
        text_parts = [c.text for c in result.content if hasattr(c, "text")]
        assert text_parts
        data = json.loads(text_parts[0])
        assert data["results"][0]["symbol"] == "ETH-USD-PERP"


async def test_call_subkey_tool_via_protocol(tmp_path, monkeypatch):
    """The generate_subkey tool works through the full protocol stack."""
    tool_fn = server._tool_manager._tools["paradex_generate_subkey"].fn
    monkeypatch.setitem(tool_fn.__globals__, "DEFAULT_KEYS_DIR", tmp_path / "keys")

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "paradex_generate_subkey", {"name": "proto-test", "path": ""}
        )
        assert result.content
        text_parts = [c.text for c in result.content if hasattr(c, "text")]
        assert text_parts
        data = json.loads(text_parts[0])
        assert data["name"] == "proto-test"
        assert data["public_key"].startswith("0x")
        assert "private_key" not in data


async def test_call_nonexistent_tool_returns_error():
    """Calling a tool that doesn't exist returns an error through the protocol."""
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("paradex_does_not_exist", {})
        assert result.isError
