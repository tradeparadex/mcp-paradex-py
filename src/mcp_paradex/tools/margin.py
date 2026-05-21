"""
Margin simulation tool — answers "if I open this trade, what happens to my
margin and free collateral?" without touching the exchange.

Backed by the offline calculator in :mod:`paradex_py.margin` (0.6.0+).
"""

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from paradex_py.margin import MarginInputs, compute
from pydantic import Field

from mcp_paradex.models import MarginSimulationResult, OrderSideEnum
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info
from mcp_paradex.utils.errors import check_response
from mcp_paradex.utils.paradex_client import (
    api_call,
    get_authenticated_paradex_client,
    get_paradex_client,
)


def _margin_numbers(result: dict[str, object]) -> tuple[float, float]:
    """Pull (IMR, MMR) out of a `compute()` result, tolerating missing keys."""
    imr = float(result.get("IMR", 0.0) or 0.0)  # type: ignore[arg-type]
    mmr = float(result.get("MMR", 0.0) or 0.0)  # type: ignore[arg-type]
    return imr, mmr


def _account_value(account_resp: dict[str, object]) -> float:
    """Best-effort account_value extraction from the /account snapshot."""
    for key in ("account_value", "total_collateral", "equity"):
        v = account_resp.get(key)
        if v is None:
            continue
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return 0.0


def _first_account_info(resp: Any) -> dict[str, Any] | None:
    """Pull the first /account/info row out of the raw response (or None)."""
    if not isinstance(resp, dict):
        return None
    results = resp.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        return first if isinstance(first, dict) else None
    return None


def _resolve_methodology(requested: str, pm_config_available: bool, notes: list[str]) -> str:
    if requested != "auto":
        return requested
    if pm_config_available:
        return "portfolio_margin"
    notes.append("portfolio-margin config unavailable; using cross_margin.")
    return "cross_margin"


def _compute_with_fallback(
    base_inputs: MarginInputs,
    what_if_inputs: MarginInputs,
    methodology: str,
    notes: list[str],
) -> tuple[dict[str, object], dict[str, object], str]:
    """Run `compute()` for before/after, falling back to cross_margin if PM fails."""
    try:
        before = compute(**base_inputs.compute_kwargs(), margin_methodology=methodology)
        after = compute(**what_if_inputs.compute_kwargs(), margin_methodology=methodology)
        return before, after, methodology
    except ValueError as exc:
        if methodology != "portfolio_margin":
            raise
        notes.append(f"portfolio_margin failed ({exc}); falling back to cross_margin.")
        before = compute(**base_inputs.compute_kwargs(), margin_methodology="cross_margin")
        after = compute(**what_if_inputs.compute_kwargs(), margin_methodology="cross_margin")
        return before, after, "cross_margin"


@server.tool(
    name="paradex_margin_simulate",
    title="Simulate Margin Impact",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def margin_simulate(
    market_id: Annotated[str, Field(description="Market symbol, e.g. 'BTC-USD-PERP'.")],
    side: Annotated[OrderSideEnum, Field(description="Order side: BUY or SELL.")],
    size: Annotated[float, Field(description="Order size in base asset units.", gt=0)],
    margin_methodology: Annotated[
        Literal["auto", "cross_margin", "portfolio_margin"],
        Field(
            default="auto",
            description=(
                "Which methodology to simulate. 'auto' uses portfolio_margin when the "
                "live PM config is available for the underlying, else cross_margin."
            ),
        ),
    ],
    ctx: Context,
) -> MarginSimulationResult:
    """
    What-if calculator for the margin and free-collateral impact of a trade.

    Use this when you need to:
    - Decide whether you have enough collateral to open a position
    - Compare the margin cost of cross vs portfolio margin for the same trade
    - See how much an order would consume of your available margin before placing it

    Runs entirely client-side using `paradex_py.margin.compute` — no order is
    submitted. Pulls live positions, orders, balances, market state, account
    info, and (if available) the portfolio-margin config from Paradex, then
    re-runs the calculator with and without the hypothetical position appended.

    Returned `initial_margin_delta` is `IM_after - IM_before` in USDC; positive
    means the trade consumes more collateral. `can_open` is True when
    `free_collateral_after >= 0`.
    """
    auth_client, public_client = await asyncio.gather(
        get_authenticated_paradex_client(),
        get_paradex_client(),
    )

    await ctx.report_progress(0, 2, "Fetching account, positions, orders, market state...")

    (
        positions_resp,
        orders_resp,
        balances_resp,
        markets_summary_resp,
        markets_resp,
        account_resp,
        account_info_resp,
        pm_config_resp,
    ) = await asyncio.gather(
        asyncio.to_thread(auth_client.fetch_positions),
        asyncio.to_thread(auth_client.fetch_orders),
        asyncio.to_thread(auth_client.fetch_balances),
        asyncio.to_thread(public_client.fetch_markets_summary, params={"market": "ALL"}),
        asyncio.to_thread(public_client.fetch_markets),
        api_call(auth_client, "account"),
        asyncio.to_thread(auth_client.fetch_account_info),
        asyncio.to_thread(auth_client.fetch_portfolio_margin_config),
        return_exceptions=True,
    )

    # Hard-fail when essential inputs are missing; pm_config and account_info
    # are best-effort.
    if isinstance(positions_resp, Exception):
        raise positions_resp
    if isinstance(orders_resp, Exception):
        raise orders_resp
    if isinstance(balances_resp, Exception):
        raise balances_resp
    if isinstance(markets_summary_resp, Exception):
        raise markets_summary_resp
    if isinstance(markets_resp, Exception):
        raise markets_resp
    if isinstance(account_resp, Exception):
        raise account_resp

    positions_resp = await check_response(ctx, positions_resp, path="positions")
    orders_resp = await check_response(ctx, orders_resp, path="orders")
    balances_resp = await check_response(ctx, balances_resp, path="balance")
    markets_summary_resp = await check_response(ctx, markets_summary_resp, path="markets/summary")
    markets_resp = await check_response(ctx, markets_resp, path="markets")

    pm_config_dict = pm_config_resp if not isinstance(pm_config_resp, Exception) else None
    account_info_first = _first_account_info(
        account_info_resp if not isinstance(account_info_resp, Exception) else None
    )

    notes: list[str] = []
    methodology = _resolve_methodology(margin_methodology, pm_config_dict is not None, notes)

    await ctx.report_progress(1, 2, "Running margin calculator...")

    common = {
        "positions_resp": positions_resp,
        "orders_resp": orders_resp,
        "balances_resp": balances_resp,
        "markets_summary_resp": markets_summary_resp,
        "markets_resp": markets_resp,
        "pm_config_resp": pm_config_dict,
        "account_info_resp": account_info_first,
    }
    base_inputs = MarginInputs.from_api_responses(**common)
    what_if_inputs = MarginInputs.from_api_responses(
        **common,
        what_if=[{"market": market_id, "side": side, "size": str(size)}],
    )

    before, after, methodology = _compute_with_fallback(
        base_inputs, what_if_inputs, methodology, notes
    )

    imr_before, mmr_before = _margin_numbers(before)
    imr_after, mmr_after = _margin_numbers(after)
    account_value = _account_value(account_resp)
    free_after = account_value - imr_after

    await ctx_info(
        ctx,
        f"Margin sim {side} {size} {market_id}: ΔIM={imr_after - imr_before:.4f} "
        f"free_after={free_after:.4f}",
        logger_name="paradex.margin",
    )

    return MarginSimulationResult(
        market_id=market_id,
        side=str(side),
        size=size,
        margin_methodology=methodology,
        initial_margin_before=imr_before,
        initial_margin_after=imr_after,
        initial_margin_delta=imr_after - imr_before,
        maintenance_margin_before=mmr_before,
        maintenance_margin_after=mmr_after,
        account_value=account_value,
        free_collateral_after=free_after,
        can_open=free_after >= 0,
        notes=notes,
    )
