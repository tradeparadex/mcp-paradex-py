"""
Trade-preview tool — pre-trade validation + SDK-backed margin/fee impact.

Replaces the legacy `paradex_pre_trade_check` and `paradex_margin_simulate`
tools. Margin math comes from `paradex_py.margin.compute`; fee logic from
`paradex_py.margin.fee_rate_for_market`. We keep validation (account status,
position limit, free collateral) and slippage/funding estimates here because
they're not part of the margin calculator.
"""

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from paradex_py.margin import MarginInputs, compute, fee_rate_for_market, market_specs_by_symbol
from pydantic import Field

from mcp_paradex.models import (
    MarketDetails,
    MarketSummary,
    OrderSideEnum,
    Position,
    PreTradeBBO,
    PreTradeEstimates,
    PreTradeMarketConstraints,
    TradePreviewMargin,
    TradePreviewResult,
)
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info
from mcp_paradex.utils.errors import check_response
from mcp_paradex.utils.paradex_client import (
    api_call,
    get_authenticated_paradex_client,
    get_paradex_client,
)


def _f(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_account_info(resp: Any) -> dict[str, Any] | None:
    """Pull the account-info row out of the raw response.

    Paradex returns this endpoint in two observed shapes — either the row
    directly (`{"fees": {...}, ...}`) or wrapped in `{"results": [row]}`.
    """
    if not isinstance(resp, dict):
        return None
    results = resp.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        return first if isinstance(first, dict) else None
    return resp


def _resolve_methodology(requested: str, pm_config_available: bool, notes: list[str]) -> str:
    if requested != "auto":
        return requested
    if pm_config_available:
        return "portfolio_margin"
    notes.append("portfolio-margin config unavailable; using cross_margin.")
    return "cross_margin"


def _compute_margins(
    base_inputs: MarginInputs,
    what_if_inputs: MarginInputs,
    methodology: str,
    notes: list[str],
) -> tuple[dict[str, object], dict[str, object], str]:
    """Run compute() for before/after; fall back to cross_margin if PM fails.

    Returns zeroed IM/MM if the calculator rejects the inputs entirely
    (e.g. unsupported asset_kind like SPOT). Caller still surfaces fee /
    slippage / readiness; only the margin block is unavailable.
    """
    try:
        before = compute(**base_inputs.compute_kwargs(), margin_methodology=methodology)
        after = compute(**what_if_inputs.compute_kwargs(), margin_methodology=methodology)
        return before, after, methodology
    except ValueError as exc:
        if methodology == "portfolio_margin":
            notes.append(f"portfolio_margin failed ({exc}); falling back to cross_margin.")
            try:
                before = compute(**base_inputs.compute_kwargs(), margin_methodology="cross_margin")
                after = compute(
                    **what_if_inputs.compute_kwargs(), margin_methodology="cross_margin"
                )
                return before, after, "cross_margin"
            except ValueError as exc2:
                exc = exc2
        notes.append(f"margin simulation unavailable: {exc}")
        zero: dict[str, object] = {"IMR": 0.0, "MMR": 0.0}
        return zero, zero, methodology


def _estimate_trade(
    market_summary: MarketSummary,
    market_spec: dict[str, Any],
    account_info: dict[str, Any] | None,
    side: str,
    size: float,
    current_position: Position | None,
) -> PreTradeEstimates:
    """Fee/slippage/funding/break-even estimates.

    Uses the SDK's `fee_rate_for_market` for the taker rate (which already
    handles spot/option/perp-option asset-kind fee fields). Falls back to
    0.05% if neither account-tier nor market-published fees are available.
    """
    bid = _f(market_summary.bid)
    ask = _f(market_summary.ask)
    mark = _f(market_summary.mark_price)
    funding_rate_8h = _f(market_summary.funding_rate)
    mid_price = (bid + ask) / 2 if bid and ask else mark
    entry_price = ask if side.upper() == "BUY" else bid
    if not entry_price:
        entry_price = mid_price

    taker_fee_rate = fee_rate_for_market(market_spec, account_info=account_info, default=0.0005)

    estimated_fee_usdc = round(size * entry_price * taker_fee_rate, 4)
    slippage_bps = round(abs(entry_price - mid_price) / mid_price * 10000, 2) if mid_price else 0.0
    funding_sign = -1.0 if side.upper() == "BUY" else 1.0
    daily_funding_cost_usdc = round(funding_sign * size * entry_price * funding_rate_8h * 3, 4)
    break_even_pct = round(taker_fee_rate * 2 * 100, 4)
    existing_unrealized: float | None = None
    if current_position is not None:
        existing_unrealized = round(
            _f(current_position.unrealized_pnl) + _f(current_position.unrealized_funding_pnl),
            4,
        )
    return PreTradeEstimates(
        estimated_entry_price=entry_price,
        estimated_fee_usdc=estimated_fee_usdc,
        slippage_bps=slippage_bps,
        daily_funding_cost_usdc=daily_funding_cost_usdc,
        break_even_price_change_pct=break_even_pct,
        existing_unrealized_pnl_usdc=existing_unrealized,
    )


def _readiness_reasons(
    account_status: str,
    free_collateral_after: float,
    market_details: MarketDetails,
    size: float,
) -> list[str]:
    reasons: list[str] = []
    if account_status != "ACTIVE":
        reasons.append(f"Account status is {account_status}, not ACTIVE")
    if free_collateral_after < 0:
        reasons.append(
            f"Free collateral after trade is {free_collateral_after:.4f} (would be liquidatable)"
        )
    position_limit = _f(market_details.position_limit)
    if position_limit > 0 and size > position_limit:
        reasons.append(f"Size {size} exceeds position limit {position_limit}")
    return reasons


@server.tool(
    name="paradex_trade_preview",
    title="Trade Preview",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def trade_preview(
    market_id: Annotated[str, Field(description="Market symbol, e.g. 'BTC-USD-PERP'.")],
    side: Annotated[OrderSideEnum, Field(description="Order side: BUY or SELL.")],
    size: Annotated[float, Field(description="Order size in base asset units.", gt=0)],
    margin_methodology: Annotated[
        Literal["auto", "cross_margin", "portfolio_margin"],
        Field(
            default="auto",
            description=(
                "Margin methodology to simulate. 'auto' uses portfolio_margin when "
                "the live PM config is available for the underlying, else cross_margin."
            ),
        ),
    ],
    ctx: Context,
) -> TradePreviewResult:
    """
    One-shot pre-trade analysis combining readiness validation and margin impact.

    Use before submitting any order. Returns:
    - account_status, current_position, bbo, market_constraints — context for the trade.
    - margin — IM/MM before/after the trade, account_value, free_collateral_after.
      Margin math is the live `paradex_py.margin.compute` calculator; no hand math.
    - estimates — fee, slippage, daily funding, break-even (taker rate via the
      SDK's `fee_rate_for_market` which respects account-tier and asset-kind).
    - ready_to_trade + not_ready_reasons — actionable summary: account is ACTIVE,
      size respects the market position limit, and free_collateral_after >= 0.
    """
    auth_client, public_client = await asyncio.gather(
        get_authenticated_paradex_client(),
        get_paradex_client(),
    )

    await ctx.report_progress(0, 2, "Fetching account, positions, market state...")

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

    for required in (
        positions_resp,
        orders_resp,
        balances_resp,
        markets_summary_resp,
        markets_resp,
        account_resp,
    ):
        if isinstance(required, Exception):
            raise required

    positions_resp = await check_response(ctx, positions_resp, path="positions")
    orders_resp = await check_response(ctx, orders_resp, path="orders")
    balances_resp = await check_response(ctx, balances_resp, path="balance")
    markets_summary_resp = await check_response(ctx, markets_summary_resp, path="markets/summary")
    markets_resp = await check_response(ctx, markets_resp, path="markets")

    pm_config_dict = pm_config_resp if not isinstance(pm_config_resp, Exception) else None
    account_info_first = _first_account_info(
        account_info_resp if not isinstance(account_info_resp, Exception) else None
    )

    # Pull the rows we care about for THIS market.
    summary_rows = (markets_summary_resp or {}).get("results", [])
    market_rows = (markets_resp or {}).get("results", [])
    position_rows = (positions_resp or {}).get("results", [])

    summary_raw = next((s for s in summary_rows if s.get("symbol") == market_id), None)
    market_raw = next((m for m in market_rows if m.get("symbol") == market_id), None)
    if summary_raw is None:
        raise ValueError(f"Market {market_id} not found in summaries")
    if market_raw is None:
        raise ValueError(f"Market {market_id} not found in market details")

    market_summary = MarketSummary.model_validate(summary_raw)
    market_details = MarketDetails.model_validate(market_raw)

    current_position_raw = next(
        (p for p in position_rows if p.get("market") == market_id and p.get("status") == "OPEN"),
        None,
    )
    current_position = (
        Position.model_validate(current_position_raw) if current_position_raw else None
    )

    # Resolve methodology, then run the margin calculator twice (before / after).
    notes: list[str] = []
    methodology = _resolve_methodology(margin_methodology, pm_config_dict is not None, notes)

    await ctx.report_progress(1, 2, "Running margin calculator...")

    common_inputs = {
        "positions_resp": positions_resp,
        "orders_resp": orders_resp,
        "balances_resp": balances_resp,
        "markets_summary_resp": markets_summary_resp,
        "markets_resp": markets_resp,
        "pm_config_resp": pm_config_dict,
        "account_info_resp": account_info_first,
    }
    base_inputs = MarginInputs.from_api_responses(**common_inputs)
    what_if_inputs = MarginInputs.from_api_responses(
        **common_inputs,
        what_if=[{"market": market_id, "side": side.value, "size": str(size)}],
    )
    before, after, methodology = _compute_margins(base_inputs, what_if_inputs, methodology, notes)

    imr_before = _f(before.get("IMR"))
    imr_after = _f(after.get("IMR"))
    mmr_before = _f(before.get("MMR"))
    mmr_after = _f(after.get("MMR"))
    account_value = _f((account_resp or {}).get("account_value"))
    free_collateral_before = _f((account_resp or {}).get("free_collateral"))
    free_collateral_after = account_value - imr_after

    # Fee/slippage/funding estimates (SDK fee lookup; no hand-rolled asset-kind dict).
    market_specs = market_specs_by_symbol(market_rows)
    market_spec_dict = market_specs.get(market_id, {})
    estimates = _estimate_trade(
        market_summary=market_summary,
        market_spec=market_spec_dict,
        account_info=account_info_first,
        side=side.value,
        size=size,
        current_position=current_position,
    )

    account_status = str((account_resp or {}).get("status") or "")
    not_ready_reasons = _readiness_reasons(
        account_status, free_collateral_after, market_details, size
    )

    await ctx_info(
        ctx,
        f"Trade preview {side} {size} {market_id}: ΔIM={imr_after - imr_before:.4f} "
        f"free_after={free_collateral_after:.4f} ready={not not_ready_reasons}",
        logger_name="paradex.preview",
    )

    return TradePreviewResult(
        market_id=market_id,
        side=side.value,
        size=size,
        account_status=account_status,
        current_position=current_position,
        bbo=PreTradeBBO(
            bid=market_summary.bid or "",
            ask=market_summary.ask or "",
            mark_price=market_summary.mark_price or "",
            funding_rate=market_summary.funding_rate or "",
        ),
        market_constraints=PreTradeMarketConstraints(
            min_notional=_f(market_details.min_notional),
            order_size_increment=market_details.order_size_increment or "",
            position_limit=_f(market_details.position_limit),
            price_tick_size=_f(market_details.price_tick_size),
        ),
        margin=TradePreviewMargin(
            methodology=methodology,
            initial_margin_before=imr_before,
            initial_margin_after=imr_after,
            initial_margin_delta=imr_after - imr_before,
            maintenance_margin_before=mmr_before,
            maintenance_margin_after=mmr_after,
            account_value=account_value,
            free_collateral_before=free_collateral_before,
            free_collateral_after=free_collateral_after,
        ),
        estimates=estimates,
        ready_to_trade=not not_ready_reasons,
        not_ready_reasons=not_ready_reasons,
        notes=notes,
    )
