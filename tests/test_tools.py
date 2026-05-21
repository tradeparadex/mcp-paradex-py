"""
Layer 2 integration tests: exercise tools via FastMCP.call_tool() with the
Paradex HTTP client mocked out.

Strategy
--------
All tools call get_paradex_client() or get_authenticated_paradex_client(),
both of which return the module-level `_paradex_client` singleton.  Setting
that variable to a MagicMock bypasses real network calls while still
exercising the full tool logic (arg parsing, Pydantic validation, response
shaping).

call_tool() returns [TextContent(type="text", text="<json>")], so helpers
_text() / _json() extract the payload.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import Context

import mcp_paradex.utils.paradex_client as _client_module
from mcp_paradex.server.server import server

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(result: Any) -> str:
    """Pull the JSON text from a call_tool result.

    FastMCP call_tool() returns one of:
    - [TextContent(...)]              for tools annotated with plain `dict` / `list`
    - ([TextContent(...)], dict)      for tools annotated with `dict[str, Any]` or
                                      a Pydantic/dataclass model (structured output)
    """
    if isinstance(result, tuple):
        return result[0][0].text
    return result[0].text


def _json(result: Any) -> Any:
    return json.loads(_text(result))


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


@pytest.fixture()
def no_ctx_progress():
    """Suppress ctx.report_progress for tools tested outside a live MCP session."""
    with patch.object(Context, "report_progress", new_callable=AsyncMock):
        yield


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

MARKET_RECORD = {
    "symbol": "BTC-USD-PERP",
    "base_currency": "BTC",
    "quote_currency": "USD",
    "settlement_currency": "USDC",
    "order_size_increment": "0.0001",
    "price_tick_size": "0.1",
    "min_notional": "1.0",
    "open_at": 0,
    "expiry_at": 0,
    "asset_kind": "PERP",
    "market_kind": "cross",
    "position_limit": "100.0",
    "price_bands_width": "0.05",
    "max_open_orders": 50,
    "max_funding_rate": "0.0003",
    "delta1_cross_margin_params": {},
    "option_cross_margin_params": {},
    "price_feed_id": "",
    "oracle_ewma_factor": "0.0",
    "max_order_size": "1000.0",
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

SUMMARY_RECORD = {
    "symbol": "BTC-USD-PERP",
    "mark_price": "95000.0",
    "delta": "1.0",
    "greeks": {
        "delta": "1.0",
        "gamma": "0.0",
        "vega": "0.0",
        "rho": "0.0",
        "vanna": "0.0",
        "volga": "0.0",
    },
    "last_traded_price": "95000.0",
    "bid": "94999.0",
    "ask": "95001.0",
    "volume_24h": "100000000",
    "total_volume": "1000000000",
    "created_at": 1_700_000_000_000,
    "underlying_price": "95000.0",
    "open_interest": "500",
    "funding_rate": "0.0001",
    "price_change_rate_24h": "0.02",
}

ORDER_RECORD = {
    "id": "ord-1",
    "account": "0xabc123",
    "market": "BTC-USD-PERP",
    "side": "BUY",
    "type": "LIMIT",
    "size": "0.1",
    "remaining_size": "0.1",
    "price": "94000.0",
    "status": "OPEN",
    "created_at": 1_700_000_000_000,
    "last_updated_at": 1_700_000_000_000,
    "timestamp": 1_700_000_000_000,
    "cancel_reason": "",
    "client_id": "my-order-1",
    "seq_no": 1,
    "instruction": "GTC",
    "avg_fill_price": "0",
    "stp": None,
    "received_at": 1_700_000_000_000,
    "published_at": 1_700_000_000_000,
    "flags": [],
    "trigger_price": "",
}

ACCOUNT_RESPONSE = {
    "account": "0xabc123",
    "account_value": "10000.0",
    "free_collateral": "8000.0",
    "initial_margin_requirement": "1000.0",
    "maintenance_margin_requirement": "500.0",
    "margin_cushion": "9500.0",
    "seq_no": 1,
    "settlement_asset": "USDC",
    "status": "ACTIVE",
    "total_collateral": "10000.0",
    "updated_at": 1_700_000_000_000,
}

POSITION_RECORD = {
    "id": "pos-1",
    "account": "0xabc123",
    "market": "BTC-USD-PERP",
    "status": "OPEN",
    "side": "LONG",
    "size": "0.1",
    "average_entry_price": "95000.0",
    "average_entry_price_usd": "95000.0",
    "average_exit_price": "0.0",
    "unrealized_pnl": "500.0",
    "unrealized_funding_pnl": "-10.0",
    "cost": "9500.0",
    "cost_usd": "9500.0",
    "cached_funding_index": "0.0",
    "last_updated_at": 1_700_000_000_000,
    "last_fill_id": "fill-1",
    "seq_no": 1,
}


# ---------------------------------------------------------------------------
# System tools
# ---------------------------------------------------------------------------


async def test_system_state_returns_status_and_timestamp(mock_client):
    mock_client.fetch_system_state.return_value = {"status": "ok"}
    mock_client.fetch_system_time.return_value = {"server_time": 1_700_000_000_000}

    result = await server.call_tool("paradex_system_state", {})
    data = _json(result)

    assert data["status"] == "ok"
    assert data["timestamp"] == 1_700_000_000_000
    mock_client.fetch_system_state.assert_called_once()
    mock_client.fetch_system_time.assert_called_once()


SYSTEM_CONFIG_RESPONSE = {
    "starknet_gateway_url": "https://alpha-mainnet.starknet.io",
    "starknet_fullnode_rpc_url": "https://rpc.mainnet.starknet.io",
    "starknet_fullnode_rpc_base_url": "https://rpc.mainnet.starknet.io",
    "starknet_chain_id": "0x534e5f4d41494e",
    "block_explorer_url": "https://starkscan.co",
    "paraclear_address": "0xabc",
    "paraclear_decimals": 8,
    "paraclear_account_proxy_hash": "0xdef",
    "paraclear_account_hash": "0x123",
    "oracle_address": "0x456",
    "bridged_tokens": [],
    "l1_core_contract_address": "0x789",
    "l1_operator_address": "0xabc",
    "l1_chain_id": "1",
    "liquidation_fee": "0.005",
}


PM_ASSET_RESPONSE = {
    "base_asset": "BTC",
    "funding_provision_hour": 8.0,
    "hedged_margin_factor": 0.01,
    "unhedged_margin_factor": 0.02,
    "mmf_factor": 0.5,
    "scenarios": [
        {"spot_shock": 0.16, "vol_shock": 0.4, "weight": 1.0},
        {"spot_shock": -0.16, "vol_shock": 0.4, "weight": 1.0},
    ],
    "vol_shock_params": {
        "dte_floor_days": 1.0,
        "min_vol_shock_up": 0.4,
        "vega_power_long_dte": 0.13,
        "vega_power_short_dte": 0.3,
    },
}


async def test_system_config_calls_correct_api_path(mock_client):
    # Tool now calls both system/config and system/portfolio-margin-config concurrently.
    def _get_side_effect(url, path, params):
        if path == "system/portfolio-margin-config":
            return {"results": []}
        return SYSTEM_CONFIG_RESPONSE

    mock_client.get.side_effect = _get_side_effect

    result = await server.call_tool("paradex_system_config", {})
    data = _json(result)

    assert data["config"]["starknet_chain_id"] == "0x534e5f4d41494e"
    assert "portfolio_margin" in data
    mock_client.get.assert_any_call(mock_client.api_url, "system/config", None)
    mock_client.get.assert_any_call(mock_client.api_url, "system/portfolio-margin-config", None)


async def test_system_config_portfolio_margin_field_types(mock_client):
    """PM factor fields must be floats (not strings) and nested objects parsed."""

    def _get_side_effect(url, path, params):
        if path == "system/portfolio-margin-config":
            return {"results": [PM_ASSET_RESPONSE]}
        return SYSTEM_CONFIG_RESPONSE

    mock_client.get.side_effect = _get_side_effect

    result = await server.call_tool("paradex_system_config", {})
    data = _json(result)

    pm = data["portfolio_margin"]
    assert len(pm) == 1
    asset = pm[0]

    assert asset["base_asset"] == "BTC"
    assert isinstance(asset["hedged_margin_factor"], float)
    assert asset["hedged_margin_factor"] == 0.01
    assert isinstance(asset["unhedged_margin_factor"], float)
    assert asset["unhedged_margin_factor"] == 0.02
    assert isinstance(asset["mmf_factor"], float)
    assert asset["mmf_factor"] == 0.5
    assert asset["funding_provision_hour"] == 8.0

    scenarios = asset["scenarios"]
    assert len(scenarios) == 2
    assert isinstance(scenarios[0]["spot_shock"], float)
    assert scenarios[0]["spot_shock"] == 0.16
    assert scenarios[1]["spot_shock"] == -0.16

    vsp = asset["vol_shock_params"]
    assert vsp["dte_floor_days"] == 1.0
    assert vsp["min_vol_shock_up"] == 0.4
    assert vsp["vega_power_long_dte"] == 0.13
    assert vsp["vega_power_short_dte"] == 0.3


async def test_system_config_portfolio_margin_multiple_assets(mock_client):
    """All assets in the PM response are returned."""
    eth_asset = {**PM_ASSET_RESPONSE, "base_asset": "ETH", "hedged_margin_factor": 0.02}

    def _get_side_effect(url, path, params):
        if path == "system/portfolio-margin-config":
            return {"results": [PM_ASSET_RESPONSE, eth_asset]}
        return SYSTEM_CONFIG_RESPONSE

    mock_client.get.side_effect = _get_side_effect

    result = await server.call_tool("paradex_system_config", {})
    data = _json(result)

    pm = data["portfolio_margin"]
    assert len(pm) == 2
    assert pm[0]["base_asset"] == "BTC"
    assert pm[1]["base_asset"] == "ETH"
    assert pm[1]["hedged_margin_factor"] == 0.02


# ---------------------------------------------------------------------------
# Market tools
# ---------------------------------------------------------------------------


async def test_markets_returns_results(mock_client):
    mock_client.fetch_markets.return_value = {"results": [MARKET_RECORD]}

    result = await server.call_tool("paradex_markets", {"market_ids": ["ALL"]})
    data = _json(result)

    assert data["total"] == 1
    assert data["results"][0]["symbol"] == "BTC-USD-PERP"
    mock_client.fetch_markets.assert_called_once()


async def test_markets_filters_by_symbol(mock_client):
    eth_record = {**MARKET_RECORD, "symbol": "ETH-USD-PERP", "base_currency": "ETH"}
    mock_client.fetch_markets.return_value = {"results": [MARKET_RECORD, eth_record]}

    result = await server.call_tool("paradex_markets", {"market_ids": ["ETH-USD-PERP"]})
    data = _json(result)

    assert data["total"] == 1
    assert data["results"][0]["symbol"] == "ETH-USD-PERP"


async def test_markets_pagination(mock_client):
    records = [{**MARKET_RECORD, "symbol": f"MKT{i}-USD-PERP"} for i in range(5)]
    mock_client.fetch_markets.return_value = {"results": records}

    result = await server.call_tool(
        "paradex_markets", {"market_ids": ["ALL"], "limit": 2, "offset": 0}
    )
    data = _json(result)

    assert data["total"] == 5
    assert len(data["results"]) == 2


async def test_market_summaries_fetches_all(mock_client):
    mock_client.fetch_markets_summary.return_value = {"results": [SUMMARY_RECORD]}

    result = await server.call_tool("paradex_market_summaries", {"market_ids": ["ALL"]})
    data = _json(result)

    assert data["total"] == 1
    assert data["results"][0]["symbol"] == "BTC-USD-PERP"
    mock_client.fetch_markets_summary.assert_called_once_with(params={"market": "ALL"})


async def test_bbo_returns_bid_ask(mock_client):
    mock_client.fetch_bbo.return_value = {
        "market": "BTC-USD-PERP",
        "seq_no": 42,
        "ask": "95001.0",
        "ask_size": "0.5",
        "bid": "94999.0",
        "bid_size": "1.0",
        "last_updated_at": 1_700_000_000_000,
    }

    result = await server.call_tool("paradex_bbo", {"market_id": "BTC-USD-PERP"})
    data = _json(result)

    assert data["market"] == "BTC-USD-PERP"
    assert data["ask"] == "95001.0"
    mock_client.fetch_bbo.assert_called_once_with("BTC-USD-PERP")


async def test_orderbook_passes_depth_param(mock_client):
    mock_client.fetch_orderbook.return_value = {
        "market": "BTC-USD-PERP",
        "asks": [["95001.0", "0.1"]],
        "bids": [["94999.0", "0.2"]],
    }

    result = await server.call_tool("paradex_orderbook", {"market_id": "BTC-USD-PERP", "depth": 20})
    data = _json(result)

    assert data["market"] == "BTC-USD-PERP"
    mock_client.fetch_orderbook.assert_called_once_with("BTC-USD-PERP", params={"depth": 20})


async def test_trades_passes_time_params(mock_client):
    mock_client.fetch_trades.return_value = {
        "results": [
            {
                "id": "trade-1",
                "market": "BTC-USD-PERP",
                "side": "BUY",
                "size": "0.1",
                "price": "95000.0",
                "created_at": 1_700_000_000_000,
                "trade_type": "FILL",
            }
        ]
    }

    result = await server.call_tool(
        "paradex_trades",
        {"market_id": "BTC-USD-PERP", "start_unix_ms": 1_000, "end_unix_ms": 2_000},
    )
    # list[Trade] → structured output: (content_list, {'result': [...]})
    trades = result[1]["result"]

    assert len(trades) == 1
    assert trades[0]["id"] == "trade-1"
    mock_client.fetch_trades.assert_called_once_with(
        params={"market": "BTC-USD-PERP", "start_at": 1_000, "end_at": 2_000}
    )


async def test_klines_passes_params_and_shapes_ohlcv(mock_client):
    mock_client.get.return_value = {
        "results": [[1_700_000_000_000, 95000.0, 95500.0, 94500.0, 95200.0, 100.0]]
    }

    result = await server.call_tool(
        "paradex_klines",
        {
            "market_id": "BTC-USD-PERP",
            "resolution": 1,
            "start_unix_ms": 1_000,
            "end_unix_ms": 2_000,
        },
    )
    # list[OHLCV] → structured output: (content_list, {'result': [...]})
    candles = result[1]["result"]

    assert len(candles) == 1
    assert candles[0]["open"] == 95000.0
    assert candles[0]["high"] == 95500.0
    assert candles[0]["close"] == 95200.0
    mock_client.get.assert_called_once_with(
        mock_client.api_url,
        "markets/klines",
        {"symbol": "BTC-USD-PERP", "resolution": "1", "start_at": 1_000, "end_at": 2_000},
    )


async def test_funding_data_passes_params(mock_client):
    mock_client.fetch_funding_data.return_value = {
        "results": [
            {
                "market": "BTC-USD-PERP",
                "created_at": 1_700_000_000_000,
                "funding_index": "0.001",
                "funding_premium": "0.0002",
                "funding_rate": "0.0001",
            }
        ]
    }

    result = await server.call_tool(
        "paradex_funding_data",
        {"market_id": "BTC-USD-PERP", "start_unix_ms": 1_000, "end_unix_ms": 2_000},
    )
    # list[FundingData] → structured output: (content_list, {'result': [...]})
    funding = result[1]["result"]

    assert funding[0]["market"] == "BTC-USD-PERP"
    mock_client.fetch_funding_data.assert_called_once_with(
        params={"market": "BTC-USD-PERP", "start_at": 1_000, "end_at": 2_000}
    )


async def test_filters_model_returns_schema(mock_client):
    result = await server.call_tool("paradex_filters_model", {"tool_name": "paradex_markets"})
    data = _json(result)

    # Should be a JSON Schema with at least a 'properties' key
    assert "properties" in data
    assert "symbol" in data["properties"]


# ---------------------------------------------------------------------------
# Account tools — require authentication
# ---------------------------------------------------------------------------


async def test_account_summary_raises_when_unauthenticated(mock_client):
    mock_client.account = None

    with pytest.raises(ToolError, match="not authenticated"):
        await server.call_tool("paradex_account_summary", {})


async def test_account_summary_returns_data(auth_client):
    auth_client.get.return_value = ACCOUNT_RESPONSE

    result = await server.call_tool("paradex_account_summary", {})
    data = _json(result)

    assert data["account"] == "0xabc123"
    assert data["status"] == "ACTIVE"
    auth_client.get.assert_called_once_with(auth_client.api_url, "account", None)


async def test_account_positions_returns_list(auth_client):
    auth_client.fetch_positions.return_value = {"results": [POSITION_RECORD]}

    result = await server.call_tool("paradex_account_positions", {})
    # list[Position] → structured output: (content_list, {'result': [...]})
    positions = result[1]["result"]

    assert len(positions) == 1
    assert positions[0]["market"] == "BTC-USD-PERP"
    assert positions[0]["side"] == "LONG"
    auth_client.fetch_positions.assert_called_once()


# ---------------------------------------------------------------------------
# Order tools — require authentication
# ---------------------------------------------------------------------------


async def test_open_orders_no_market_filter(auth_client):
    auth_client.fetch_orders.return_value = {"results": [ORDER_RECORD]}

    result = await server.call_tool("paradex_open_orders", {"market_id": "ALL", "limit": 10})
    data = _json(result)

    assert data["total"] == 1
    assert data["results"][0]["id"] == "ord-1"
    # market_id=ALL → params=None
    auth_client.fetch_orders.assert_called_once_with(params=None)


async def test_open_orders_passes_market_filter(auth_client):
    auth_client.fetch_orders.return_value = {"results": []}

    await server.call_tool("paradex_open_orders", {"market_id": "ETH-USD-PERP"})

    auth_client.fetch_orders.assert_called_once_with(params={"market": "ETH-USD-PERP"})


async def test_cancel_order_by_order_id(auth_client):
    auth_client.cancel_order.return_value = None

    result = await server.call_tool(
        "paradex_cancel_orders", {"order_id": "ord-1", "client_id": "", "market_id": ""}
    )
    data = _json(result)

    assert data["status"] == "queued"
    assert data["order_id"] == "ord-1"
    auth_client.cancel_order.assert_called_once_with("ord-1")
    auth_client.cancel_order_by_client_id.assert_not_called()


async def test_cancel_order_by_client_id(auth_client):
    auth_client.cancel_order_by_client_id.return_value = None

    result = await server.call_tool(
        "paradex_cancel_orders", {"order_id": "", "client_id": "my-order-1", "market_id": ""}
    )
    data = _json(result)

    assert data["status"] == "queued"
    assert data["client_id"] == "my-order-1"
    auth_client.cancel_order_by_client_id.assert_called_once_with("my-order-1")
    auth_client.cancel_order.assert_not_called()


async def test_order_status_by_order_id(auth_client):
    auth_client.fetch_order.return_value = ORDER_RECORD

    result = await server.call_tool("paradex_order_status", {"order_id": "ord-1", "client_id": ""})
    data = _json(result)

    assert data["id"] == "ord-1"
    assert data["market"] == "BTC-USD-PERP"
    auth_client.fetch_order.assert_called_once_with("ord-1")


async def test_order_status_by_client_id(auth_client):
    auth_client.fetch_order_by_client_id.return_value = ORDER_RECORD

    result = await server.call_tool(
        "paradex_order_status", {"order_id": "", "client_id": "my-order-1"}
    )
    data = _json(result)

    assert data["client_id"] == "my-order-1"
    auth_client.fetch_order_by_client_id.assert_called_once_with("my-order-1")


# ---------------------------------------------------------------------------
# Trade preview tool (paradex_trade_preview)
# Combined readiness + SDK-backed margin/fee impact.
# ---------------------------------------------------------------------------

# Fee rates by asset kind used in mock responses below.
_FEES_ALL_KINDS = {
    "fees": {
        "taker_rate": "0.0010",
        "spot_taker_rate": "0.0020",
        "dated_option_taker_rate": "0.0005",
        "perp_option_taker_rate": "0.0006",
    }
}

# Cross-margin params required by paradex_py.margin.compute(). The hand-rolled
# margin math didn't need these, but the SDK calculator validates them.
_DELTA1_CROSS_MARGIN_PARAMS = {
    "imf_base": "0.05",
    "imf_factor": "0",
    "imf_shift": "0",
    "mmf_factor": "0.5",
}


def _setup_trade_preview_mocks(auth_client, market_record, fees=_FEES_ALL_KINDS):
    auth_client.get.return_value = ACCOUNT_RESPONSE
    auth_client.fetch_positions.return_value = {"results": []}
    auth_client.fetch_orders.return_value = {"results": []}
    auth_client.fetch_balances.return_value = {"results": [{"token": "USDC", "size": "10000"}]}
    auth_client.fetch_markets_summary.return_value = {"results": [SUMMARY_RECORD]}
    auth_client.fetch_markets.return_value = {
        "results": [{**market_record, "delta1_cross_margin_params": _DELTA1_CROSS_MARGIN_PARAMS}]
    }
    auth_client.fetch_account_info.return_value = fees
    # PM config unavailable in tests — calculator falls back to cross_margin.
    auth_client.fetch_portfolio_margin_config.side_effect = Exception("no pm config in test")


async def test_trade_preview_ready_to_trade(auth_client, no_ctx_progress):
    _setup_trade_preview_mocks(auth_client, MARKET_RECORD)

    result = await server.call_tool(
        "paradex_trade_preview",
        {"market_id": "BTC-USD-PERP", "side": "BUY", "size": 1.0},
    )
    data = _json(result)

    assert data["ready_to_trade"] is True
    assert data["not_ready_reasons"] == []
    assert data["account_status"] == "ACTIVE"
    assert data["market_id"] == "BTC-USD-PERP"
    # Margin block must be populated from the SDK calculator.
    assert data["margin"]["methodology"] == "cross_margin"
    assert data["margin"]["initial_margin_after"] > data["margin"]["initial_margin_before"]
    assert data["margin"]["initial_margin_delta"] > 0
    assert data["margin"]["free_collateral_after"] < data["margin"]["account_value"]


@pytest.mark.parametrize(
    "asset_kind, expected_fee",
    [
        # PERP → taker_rate (0.0010)
        ("PERP", round(1.0 * 95001.0 * 0.0010, 4)),
        # SPOT → spot_taker_rate (0.0020) via SDK fee_rate_for_market
        ("SPOT", round(1.0 * 95001.0 * 0.0020, 4)),
        # OPTION (dated) → dated_option_taker_rate (0.0005)
        ("OPTION", round(1.0 * 95001.0 * 0.0005, 4)),
        # PERP_OPTION → perp_option_taker_rate (0.0006)
        ("PERP_OPTION", round(1.0 * 95001.0 * 0.0006, 4)),
        # FUTURE → falls back to taker_rate (0.0010)
        ("FUTURE", round(1.0 * 95001.0 * 0.0010, 4)),
    ],
)
async def test_trade_preview_fee_rate_by_asset_kind(
    auth_client, no_ctx_progress, asset_kind, expected_fee
):
    market_record = {**MARKET_RECORD, "asset_kind": asset_kind}
    _setup_trade_preview_mocks(auth_client, market_record)

    result = await server.call_tool(
        "paradex_trade_preview",
        {"market_id": "BTC-USD-PERP", "side": "BUY", "size": 1.0},
    )
    data = _json(result)

    assert data["estimates"]["estimated_fee_usdc"] == expected_fee


async def test_trade_preview_falls_back_to_taker_rate_when_specific_fee_absent(
    auth_client, no_ctx_progress
):
    """When the asset-specific fee field is absent, falls back to generic taker_rate."""
    market_record = {**MARKET_RECORD, "asset_kind": "SPOT"}
    # spot_taker_rate deliberately omitted
    _setup_trade_preview_mocks(auth_client, market_record, fees={"fees": {"taker_rate": "0.0010"}})

    result = await server.call_tool(
        "paradex_trade_preview",
        {"market_id": "BTC-USD-PERP", "side": "BUY", "size": 1.0},
    )
    data = _json(result)

    assert data["estimates"]["estimated_fee_usdc"] == round(1.0 * 95001.0 * 0.0010, 4)


async def test_trade_preview_with_existing_position(auth_client, no_ctx_progress):
    """Existing position unrealized PnL is reflected in estimates."""
    _setup_trade_preview_mocks(auth_client, MARKET_RECORD)
    auth_client.fetch_positions.return_value = {"results": [POSITION_RECORD]}

    result = await server.call_tool(
        "paradex_trade_preview",
        {"market_id": "BTC-USD-PERP", "side": "BUY", "size": 1.0},
    )
    data = _json(result)

    assert data["ready_to_trade"] is True
    assert data["current_position"]["market"] == "BTC-USD-PERP"
    # unrealized_pnl (500.0) + unrealized_funding_pnl (-10.0) = 490.0
    assert data["estimates"]["existing_unrealized_pnl_usdc"] == 490.0


# ---------------------------------------------------------------------------
# Additional fixtures for account / vault / order tests
# ---------------------------------------------------------------------------

BALANCE_RECORD = {"token": "USDC", "size": "10000.0"}

FILL_RECORD = {
    "id": "fill-1",
    "side": "BUY",
    "liquidity": "TAKER",
    "market": "BTC-USD-PERP",
    "order_id": "ord-1",
    "price": "95000.0",
    "size": "0.1",
    "fee": "4.75",
    "fee_currency": "USDC",
    "created_at": 1_700_000_000_000,
    "client_id": "my-order-1",
    "fill_type": "FILL",
    "realized_pnl": "0.0",
    "realized_funding": "0.0",
    "account": "0xabc123",
}

TRANSACTION_RECORD = {
    "id": "tx-1",
    "type": "TRANSACTION_FILL",
    "hash": "0xabcdef",
    "state": "ACCEPTED_ON_L2",
    "created_at": 1_700_000_000_000,
    "completed_at": 1_700_000_001_000,
}

VAULT_RECORD = {
    "address": "0xvault1",
    "name": "Test Vault",
    "created_at": 1_700_000_000_000,
}

VAULT_SUMMARY_RECORD = {
    "address": "0xvault1",
    "total_roi": "5.0",
    "tvl": "50000.0",
}

VAULT_BALANCE_RECORD = {
    "token": "USDC",
    "size": "50000.0",
    "last_updated_at": 1_700_000_000_000,
}

VAULT_ACCOUNT_SUMMARY_RECORD = {
    "address": "0xvault1",
    "deposited_amount": "10000.0",
    "vtoken_amount": "9523.8",
    "total_roi": "5.0",
    "total_pnl": "500.0",
    "created_at": 1_700_000_000_000,
}


# ---------------------------------------------------------------------------
# Account overview / fills / transactions
# ---------------------------------------------------------------------------


_ACCOUNT_INFO_ENTRY = {
    "account": "0xabc123",
    "kind": "main",
    "username": "trader",
    "fees": {"maker_rate": "0.0001", "taker_rate": "0.0003"},
}

_MARGIN_RESPONSE = {
    "margin_methodology": "portfolio_margin",
    "configs": [{"market": "BTC-USD-PERP", "margin_type": "CROSS", "leverage": 10}],
}


async def test_account_overview_returns_composite(auth_client, no_ctx_progress):
    auth_client.get.return_value = ACCOUNT_RESPONSE
    auth_client.fetch_balances.return_value = {"results": [BALANCE_RECORD]}
    auth_client.fetch_positions.return_value = {"results": [POSITION_RECORD]}
    # account/info and account/margin are fetched concurrently; provide minimal stubs.
    auth_client.fetch_account_info.return_value = {"results": []}

    result = await server.call_tool("paradex_account_overview", {})
    data = _json(result)

    assert data["summary"]["account"] == "0xabc123"
    assert len(data["balances"]) == 1
    assert len(data["positions"]) == 1
    assert data["positions"][0]["market"] == "BTC-USD-PERP"


async def test_account_overview_includes_info_and_margin(auth_client, no_ctx_progress):
    def _get(url, path, params):
        if path == "account/margin":
            return _MARGIN_RESPONSE
        return ACCOUNT_RESPONSE

    auth_client.get.side_effect = _get
    auth_client.fetch_balances.return_value = {"results": [BALANCE_RECORD]}
    auth_client.fetch_positions.return_value = {"results": [POSITION_RECORD]}
    auth_client.fetch_account_info.return_value = {"results": [_ACCOUNT_INFO_ENTRY]}

    result = await server.call_tool("paradex_account_overview", {})
    data = _json(result)

    assert data["info"]["kind"] == "main"
    assert data["info"]["fees"]["taker_rate"] == "0.0003"
    assert data["margin"]["margin_methodology"] == "portfolio_margin"
    assert data["margin"]["configs"][0]["market"] == "BTC-USD-PERP"


async def test_account_overview_info_margin_optional_on_failure(auth_client, no_ctx_progress):
    """Overview succeeds even if account/info or account/margin calls fail."""
    auth_client.get.return_value = ACCOUNT_RESPONSE
    auth_client.fetch_balances.return_value = {"results": [BALANCE_RECORD]}
    auth_client.fetch_positions.return_value = {"results": [POSITION_RECORD]}
    auth_client.fetch_account_info.side_effect = Exception("unavailable")

    result = await server.call_tool("paradex_account_overview", {})
    data = _json(result)

    assert data["summary"]["account"] == "0xabc123"
    assert data["info"] is None


async def test_account_fills_passes_params(auth_client):
    auth_client.fetch_fills.return_value = {"results": [FILL_RECORD]}

    result = await server.call_tool(
        "paradex_account_fills",
        {"market_id": "BTC-USD-PERP", "start_unix_ms": 1_000, "end_unix_ms": 2_000},
    )
    fills = result[1]["result"]

    assert len(fills) == 1
    assert fills[0]["id"] == "fill-1"
    assert fills[0]["market"] == "BTC-USD-PERP"
    auth_client.fetch_fills.assert_called_once_with(
        {"market": "BTC-USD-PERP", "start_at": 1_000, "end_at": 2_000}
    )


async def test_account_transactions_passes_params(auth_client):
    auth_client.fetch_transactions.return_value = {"results": [TRANSACTION_RECORD]}

    result = await server.call_tool(
        "paradex_account_transactions",
        {"start_unix_ms": 1_000, "end_unix_ms": 2_000},
    )
    transactions = result[1]["result"]

    assert len(transactions) == 1
    assert transactions[0]["id"] == "tx-1"
    auth_client.fetch_transactions.assert_called_once_with(
        {"start_at": 1_000, "end_at": 2_000, "limit": 50}
    )


# ---------------------------------------------------------------------------
# Account keys (subkeys + tokens)
# ---------------------------------------------------------------------------

SUBKEY_RECORD = {
    "public_key": "0xabc123",
    "label": "agent-key",
    "state": "ACTIVE",
    "created_at": 1_700_000_000_000,
}


async def test_account_keys_returns_credentials(auth_client):
    auth_client.fetch_subkeys.return_value = {"results": [SUBKEY_RECORD]}
    auth_client.get.return_value = {"results": []}  # empty tokens

    result = await server.call_tool("paradex_account_keys", {"include_revoked": False})
    data = _json(result)

    assert len(data["subkeys"]) == 1
    assert data["subkeys"][0]["public_key"] == "0xabc123"
    assert data["subkeys"][0]["state"] == "ACTIVE"
    assert data["tokens"] == []
    auth_client.fetch_subkeys.assert_called_once_with(params=None)


async def test_account_keys_with_revoked(auth_client):
    auth_client.fetch_subkeys.return_value = {"results": [SUBKEY_RECORD]}
    auth_client.get.return_value = {"results": []}

    await server.call_tool("paradex_account_keys", {"include_revoked": True})

    auth_client.fetch_subkeys.assert_called_once_with(params={"include_revoked": True})


TOKEN_RECORD = {
    "token_id": "tok-1",
    "lookup_id": "lkp-1",
    "name": "My API Key",
    "kind": "api_key",
    "created_at": 1_700_000_000_000,
    "expiry_at": 1_800_000_000_000,
    "revoked_at": 0,
}


async def test_account_keys_returns_tokens(auth_client):
    auth_client.fetch_subkeys.return_value = {"results": []}
    auth_client.get.return_value = {"results": [TOKEN_RECORD]}

    result = await server.call_tool("paradex_account_keys", {})
    data = _json(result)

    assert data["subkeys"] == []
    assert len(data["tokens"]) == 1
    assert data["tokens"][0]["token_id"] == "tok-1"
    assert data["tokens"][0]["kind"] == "api_key"


async def test_account_keys_with_invalid_tokens(auth_client):
    auth_client.fetch_subkeys.return_value = {"results": []}
    auth_client.get.return_value = {"results": []}

    await server.call_tool("paradex_account_keys", {"with_invalid_tokens": True})

    auth_client.get.assert_called_once_with(
        auth_client.api_url, "account/tokens", {"with_invalid": True}
    )


# ---------------------------------------------------------------------------
# Account profile
# ---------------------------------------------------------------------------

_PROFILE_RESPONSE = {
    "username": "trader",
    "referral_code": "MYCODE",
    "market_max_slippage": {"BTC-USD-PERP": "0.05"},
    "tap_status": "ACTIVE",
}

_SETTINGS_RESPONSE = {"trading_value_display": "SPOT_NOTIONAL"}


async def test_account_profile_returns_profile_and_settings(auth_client):
    def _get(url, path, params):
        if path == "account/settings":
            return _SETTINGS_RESPONSE
        return _PROFILE_RESPONSE

    auth_client.get.side_effect = _get

    result = await server.call_tool("paradex_account_profile", {})
    data = _json(result)

    assert data["profile"]["username"] == "trader"
    assert data["profile"]["referral_code"] == "MYCODE"
    assert data["settings"]["trading_value_display"] == "SPOT_NOTIONAL"


async def test_account_profile_partial_on_failure(auth_client):
    """Profile returns whatever succeeds; missing key is absent (not raised)."""

    def _get(url, path, params):
        if path == "account/settings":
            raise Exception("unavailable")
        return _PROFILE_RESPONSE

    auth_client.get.side_effect = _get

    result = await server.call_tool("paradex_account_profile", {})
    data = _json(result)

    assert data["profile"]["username"] == "trader"
    assert "settings" not in data


# ---------------------------------------------------------------------------
# Order create / history
# ---------------------------------------------------------------------------


async def test_create_order_calls_submit(auth_client):
    auth_client.submit_order.return_value = ORDER_RECORD

    result = await server.call_tool(
        "paradex_create_order",
        {
            "market_id": "BTC-USD-PERP",
            "order_side": "BUY",
            "order_type": "LIMIT",
            "size": 0.1,
            "price": 94000.0,
            "trigger_price": 0.0,
            "client_id": "my-order-1",
        },
    )
    data = _json(result)

    assert data["id"] == "ord-1"
    assert data["market"] == "BTC-USD-PERP"
    auth_client.submit_order.assert_called_once()


async def test_orders_history_passes_params(auth_client):
    auth_client.fetch_orders_history.return_value = {"results": [ORDER_RECORD]}

    result = await server.call_tool(
        "paradex_orders_history",
        {"market_id": "BTC-USD-PERP", "start_unix_ms": 1_000, "end_unix_ms": 2_000},
    )
    orders = result[1]["result"]

    assert len(orders) == 1
    assert orders[0]["id"] == "ord-1"
    auth_client.fetch_orders_history.assert_called_once_with(
        params={"market": "BTC-USD-PERP", "start_at": 1_000, "end_at": 2_000}
    )


# ---------------------------------------------------------------------------
# Vault tools
# ---------------------------------------------------------------------------


async def test_vaults_returns_results(mock_client, no_ctx_progress):
    mock_client.get.return_value = {"results": [VAULT_RECORD]}

    result = await server.call_tool("paradex_vaults", {"vault_address": ""})
    data = _json(result)

    assert data["total"] == 1
    assert data["results"][0]["address"] == "0xvault1"
    mock_client.get.assert_called_once_with(mock_client.api_url, "vaults", None)


async def test_vault_summary_returns_results(mock_client, no_ctx_progress):
    mock_client.get.return_value = {"results": [VAULT_SUMMARY_RECORD]}

    result = await server.call_tool("paradex_vault_summary", {"vault_address": "0xvault1"})
    data = _json(result)

    assert data["total"] == 1
    assert data["results"][0]["address"] == "0xvault1"
    mock_client.get.assert_called_once_with(
        mock_client.api_url, "vaults/summary", {"address": "0xvault1"}
    )


async def test_vault_overview_returns_composite(mock_client, no_ctx_progress):
    def _vault_get(api_url, path, params=None):
        if path == "vaults/balance":
            return {"results": [VAULT_BALANCE_RECORD]}
        if path == "vaults/positions":
            return {"results": [POSITION_RECORD]}
        if path == "vaults/account-summary":
            return {"results": [VAULT_ACCOUNT_SUMMARY_RECORD]}
        return {}

    mock_client.get.side_effect = _vault_get

    result = await server.call_tool("paradex_vault_overview", {"vault_address": "0xvault1"})
    data = _json(result)

    assert len(data["balances"]) == 1
    assert data["balances"][0]["token"] == "USDC"
    assert len(data["positions"]) == 1
    assert data["positions"][0]["market"] == "BTC-USD-PERP"
    assert len(data["account_summary"]) == 1
    assert data["account_summary"][0]["address"] == "0xvault1"


# ---------------------------------------------------------------------------
# Subkey generation tool
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_keys_dir(tmp_path, monkeypatch):
    """Redirect default key storage to a temporary directory.

    Patches the registered tool function's globals directly so the
    fixture is resilient to module reloads (e.g. from test_config.py).
    """
    keys_dir = tmp_path / "keys"
    tool_fn = server._tool_manager._tools["paradex_generate_subkey"].fn
    monkeypatch.setitem(tool_fn.__globals__, "DEFAULT_KEYS_DIR", keys_dir)
    return keys_dir


async def test_generate_subkey_creates_key_file(temp_keys_dir):
    result = await server.call_tool("paradex_generate_subkey", {"name": "test-key"})
    data = _json(result)

    assert data["name"] == "test-key"
    assert data["public_key"].startswith("0x")
    # Private key must NOT be in the response
    assert "private_key" not in data

    # Verify file on disk
    key_file = temp_keys_dir / "test-key.json"
    assert key_file.exists()

    stored = json.loads(key_file.read_text())
    assert stored["name"] == "test-key"
    assert stored["public_key"] == data["public_key"]
    assert stored["private_key"].startswith("0x")
    assert "created_at" in stored

    # Verify restrictive file permissions
    assert oct(key_file.stat().st_mode & 0o777) == oct(0o600)


async def test_generate_subkey_default_name(temp_keys_dir):
    result = await server.call_tool("paradex_generate_subkey", {"name": ""})
    data = _json(result)

    assert data["name"].startswith("subkey-")
    assert data["public_key"].startswith("0x")

    # Verify the file was created with the generated name
    key_file = temp_keys_dir / f"{data['name']}.json"
    assert key_file.exists()


async def test_generate_subkey_custom_path(tmp_path):
    custom_dir = tmp_path / "custom-keys"
    custom_dir.mkdir()

    result = await server.call_tool(
        "paradex_generate_subkey", {"name": "path-key", "path": str(custom_dir)}
    )
    data = _json(result)

    assert data["name"] == "path-key"
    key_file = custom_dir / "path-key.json"
    assert key_file.exists()
    assert oct(key_file.stat().st_mode & 0o777) == oct(0o600)


async def test_generate_subkey_custom_path_created_if_missing(tmp_path):
    new_dir = tmp_path / "new" / "nested" / "keys"

    result = await server.call_tool(
        "paradex_generate_subkey", {"name": "nested-key", "path": str(new_dir)}
    )
    data = _json(result)

    assert data["name"] == "nested-key"
    assert (new_dir / "nested-key.json").exists()


async def test_generate_subkey_rejects_relative_path(temp_keys_dir):
    with pytest.raises(ToolError):
        await server.call_tool("paradex_generate_subkey", {"name": "bad", "path": "relative/path"})


async def test_generate_subkey_rejects_duplicate_name(temp_keys_dir):
    await server.call_tool("paradex_generate_subkey", {"name": "dup-key"})

    with pytest.raises(ToolError):
        await server.call_tool("paradex_generate_subkey", {"name": "dup-key"})


@pytest.mark.parametrize("bad_name", ["../evil", "has spaces", "has/slash", "semi;colon"])
async def test_generate_subkey_rejects_invalid_name(temp_keys_dir, bad_name):
    with pytest.raises(ToolError):
        await server.call_tool("paradex_generate_subkey", {"name": bad_name})
