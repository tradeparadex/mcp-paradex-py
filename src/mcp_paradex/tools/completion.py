"""
Argument completion handler for Paradex MCP tools.

Provides IDE-style autocomplete for prompt and resource template arguments
such as market_id and vault_id.
"""

import logging
from typing import Any

from mcp.types import ResourceTemplateReference

from mcp_paradex.server.server import server
from mcp_paradex.utils.paradex_client import api_call, get_paradex_client

logger = logging.getLogger(__name__)

_STATIC_COMPLETIONS: dict[str, list[str]] = {
    "timeframe": ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"],
    "risk_tolerance": ["low", "medium", "high", "aggressive"],
    "investment_objective": ["income", "growth", "balanced", "capital_preservation"],
    "time_horizon": ["short", "medium", "long"],
}

_DYNAMIC_ARG_NAMES = {"market_id", "vault_id", "vault_address"}
_ORDER_SIDE_VALUES = ["BUY", "SELL"]


async def _complete_market_id(value: str) -> list[str]:
    try:
        client = await get_paradex_client()
        response = client.fetch_markets()
        symbols = [r["symbol"] for r in response.get("results", [])]
        return [s for s in symbols if s.startswith(value.upper())][:20]
    except Exception as e:
        logger.debug(f"Completion failed for market_id: {e}")
        return []


async def _complete_vault_id(value: str) -> list[str]:
    try:
        client = await get_paradex_client()
        response = await api_call(client, "vaults")
        addresses = [r.get("address", "") for r in response.get("results", [])]
        return [a for a in addresses if a.startswith(value)][:20]
    except Exception as e:
        logger.debug(f"Completion failed for vault_id: {e}")
        return []


@server.completion()
async def handle_completion(ref: Any, argument: Any, context: Any = None) -> list[str]:
    """Provide argument completions for prompts and resource templates."""
    name = getattr(argument, "name", None)
    value = getattr(argument, "value", "") or ""

    # Static enum completions — always available
    if name in _STATIC_COMPLETIONS:
        return [v for v in _STATIC_COMPLETIONS[name] if v.startswith(value)]
    if name in ("side", "order_side"):
        return [v for v in _ORDER_SIDE_VALUES if v.upper().startswith(value.upper())]

    # Dynamic completions — skip for resource templates with unknown arg names
    if isinstance(ref, ResourceTemplateReference) and name not in _DYNAMIC_ARG_NAMES:
        return []

    if name == "market_id":
        return await _complete_market_id(value)
    if name in ("vault_id", "vault_address"):
        return await _complete_vault_id(value)

    return []
