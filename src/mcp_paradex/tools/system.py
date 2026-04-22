"""
System management tools for Paradex.

This module provides tools for retrieving system-level information from Paradex,
including configuration, time synchronization, and system state.
These tools help with monitoring the exchange status and retrieving
global parameters that affect trading operations.
"""

import asyncio
import logging

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations

from mcp_paradex.models import PortfolioMarginAssetConfig, SystemConfigResult, SystemState
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info
from mcp_paradex.utils.paradex_client import api_call, get_paradex_client

logger = logging.getLogger(__name__)


@server.tool(
    name="paradex_system_config",
    title="System Configuration",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_system_config(ctx: Context) -> SystemConfigResult:
    """
    Understand the exchange's global parameters and portfolio margin risk factors.

    Use this tool when you need to:
    - Check fee schedules before placing trades
    - Verify trading limits and restrictions
    - Understand exchange-wide parameters that affect your trading
    - Review portfolio margin factors (hedged/unhedged margin, vol-shock params) per asset

    Returns:
    - config: raw system configuration (contract addresses, chain IDs, fee tiers, etc.)
    - portfolio_margin: per-asset portfolio margin parameters used in PM calculations

    Example use cases:
    - Checking current fee tiers for different markets
    - Verifying maximum leverage available for specific markets
    - Reviewing portfolio margin risk factors before switching margin methodology
    """
    try:
        client = await get_paradex_client()
        config_resp, pm_resp = await asyncio.gather(
            api_call(client, "system/config"),
            api_call(client, "system/portfolio-margin-config"),
        )
        pm_items = [
            PortfolioMarginAssetConfig.model_validate(item) for item in pm_resp.get("results", [])
        ]
        return SystemConfigResult(config=config_resp, portfolio_margin=pm_items)
    except Exception as e:
        await ctx.error(f"Error fetching system configuration: {e!s}")
        raise e


@server.tool(
    name="paradex_system_state",
    title="System State",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_system_state(ctx: Context) -> SystemState:
    """
    Verify the exchange is fully operational before executing trades.

    Use this tool when you need to:
    - Check if Paradex is functioning normally before placing important orders
    - Verify system status if you encounter unexpected behavior
    - Confirm that maintenance periods are not in effect
    - Check exchange clock synchronization with your own systems

    This is especially important before executing critical trades or when
    experiencing unexpected behavior from other API calls.

    Example use cases:
    - Verifying the exchange is operational before executing a trading strategy
    - Checking if maintenance mode is active when experiencing delays
    - Confirming exchange status during periods of market volatility
    - Diagnosing API issues by checking system health
    """
    try:
        client = await get_paradex_client()
        state = client.fetch_system_state()
        time = client.fetch_system_time()
        await ctx_info(ctx, f"System status: {state['status']}", logger_name="paradex.system")
        return SystemState(status=state["status"], timestamp=time["server_time"])
    except Exception as e:
        await ctx.error(f"Error fetching system state: {e!s}")
        raise e
