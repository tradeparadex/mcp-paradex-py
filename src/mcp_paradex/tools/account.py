"""
Account management tools.
"""

import asyncio
from typing import Annotated

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from mcp_paradex.models import (
    AccountOverview,
    AccountSummary,
    Balance,
    Fill,
    MarketDetails,
    MarketSummary,
    Position,
    PreTradeBBO,
    PreTradeCheckResult,
    PreTradeEstimates,
    PreTradeMarketConstraints,
    Transaction,
)
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info
from mcp_paradex.utils.paradex_client import (
    api_call,
    get_authenticated_paradex_client,
    get_paradex_client,
)

account_summary_adapter = TypeAdapter(AccountSummary)
balance_adapter = TypeAdapter(list[Balance])
market_details_adapter = TypeAdapter(list[MarketDetails])
market_summary_adapter = TypeAdapter(list[MarketSummary])
position_adapter = TypeAdapter(list[Position])
fill_adapter = TypeAdapter(list[Fill])
transaction_adapter = TypeAdapter(list[Transaction])

# Default taker fee rate (0.05%). Actual rate depends on the account's volume-based fee tier.
_default_taker_fee_rate = 0.0005

# Maps asset_kind to the corresponding taker fee field in the account's fees object.
# Falls back to "taker_rate" (PERP) for unknown kinds.
_FEE_FIELD_BY_ASSET_KIND: dict[str, str] = {
    "SPOT": "spot_taker_rate",
    "OPTION": "dated_option_taker_rate",
    "PERP_OPTION": "perp_option_taker_rate",
}


def _check_readiness(
    account: AccountSummary, market_details: MarketDetails, size: float
) -> list[str]:
    reasons: list[str] = []
    if account.status != "ACTIVE":
        reasons.append(f"Account status is {account.status}, not ACTIVE")
    if account.free_collateral is not None:
        try:
            if float(account.free_collateral) <= 0:
                reasons.append("Free collateral is zero or negative")
        except ValueError:
            reasons.append("Cannot parse free_collateral")
    else:
        reasons.append("Cannot parse free_collateral")
    position_limit = float(market_details.position_limit or 0)
    if position_limit > 0 and size > position_limit:
        reasons.append(f"Size {size} exceeds position limit {position_limit}")
    return reasons


def _compute_estimates(
    market_summary: MarketSummary,
    size: float,
    side: str,
    current_position: Position | None,
    taker_fee_rate: float = _default_taker_fee_rate,
) -> PreTradeEstimates:
    bid = float(market_summary.bid or 0)
    ask = float(market_summary.ask or 0)
    mark = float(market_summary.mark_price or 0)
    funding_rate_8h = float(market_summary.funding_rate or 0)
    mid_price = (bid + ask) / 2 if bid and ask else mark
    entry_price = ask if side.upper() == "BUY" else bid
    if not entry_price:
        entry_price = mid_price
    estimated_fee_usdc = round(size * entry_price * taker_fee_rate, 4)
    slippage_bps = round(abs(entry_price - mid_price) / mid_price * 10000, 2) if mid_price else 0.0
    # Daily funding: 8h rate * 3 periods; positive rate = longs pay / shorts receive
    funding_sign = -1.0 if side.upper() == "BUY" else 1.0
    daily_funding_cost_usdc = round(funding_sign * size * entry_price * funding_rate_8h * 3, 4)
    break_even_pct = round(taker_fee_rate * 2 * 100, 4)
    existing_unrealized: float | None = None
    if current_position is not None:
        existing_unrealized = round(
            float(current_position.unrealized_pnl or 0)
            + float(current_position.unrealized_funding_pnl or 0),
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


@server.tool(
    name="paradex_account_summary",
    title="Account Summary",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_summary(ctx: Context) -> AccountSummary:
    """
    Get a snapshot of your account's current financial status and trading capacity.

    Use this tool when you need to:
    - Check your current available and total balance
    - Understand your margin utilization and remaining trading capacity
    - Verify your account health and distance from liquidation
    - Get an overview of realized and unrealized P&L

    This provides the essential financial information needed to make informed
    trading decisions and manage risk appropriately.

    Example use cases:
    - Checking available balance before placing new orders
    - Monitoring account health during volatile market conditions
    - Assessing realized and unrealized P&L for performance tracking
    - Verifying margin requirements and utilization
    """
    client = await get_authenticated_paradex_client()
    response = await api_call(client, "account")
    return account_summary_adapter.validate_python(response)


@server.tool(
    name="paradex_account_balance",
    title="Account Balances",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_balance(ctx: Context) -> list[Balance]:
    """
    Get token balances for your account (e.g. USDC, DIME).

    Use this tool when you need to:
    - Check how much of each token you hold
    - Verify available USDC balance before depositing or withdrawing
    - See all token denominations in your account

    Example use cases:
    - Checking USDC balance before a deposit/withdrawal
    - Viewing DIME or other token holdings
    """
    client = await get_authenticated_paradex_client()
    response = client.fetch_balances()
    if "error" in response:
        await ctx.error(response["error"])
        raise Exception(response["error"])
    return balance_adapter.validate_python(response["results"])


@server.tool(
    name="paradex_account_positions",
    title="Account Positions",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_positions(ctx: Context) -> list[Position]:
    """
    Analyze your open positions to monitor exposure, profitability, and risk.

    Use this tool when you need to:
    - Check the status and P&L of all your open positions
    - Monitor your liquidation prices and margin requirements
    - Assess your exposure across different markets
    - Make decisions about position management (scaling, hedging, closing)

    Understanding your current positions is fundamental to proper risk management
    and is the starting point for many trading decisions.

    Example use cases:
    - Checking the unrealized P&L of your positions
    - Monitoring liquidation prices during market volatility
    - Assessing total exposure across related assets
    - Verifying entry prices and position sizes
    """
    client = await get_authenticated_paradex_client()
    response = client.fetch_positions()
    if "error" in response:
        await ctx.error(response["error"])
        raise Exception(response["error"])
    positions = position_adapter.validate_python(response["results"])
    await ctx_info(ctx, f"Found {len(positions)} open positions", logger_name="paradex.account")
    return positions


@server.tool(
    name="paradex_account_overview",
    title="Account Overview",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_overview(ctx: Context) -> AccountOverview:
    """
    Get a complete snapshot of your account: margin health, token balances,
    and all open positions in a single call.

    Use this instead of calling paradex_account_summary, paradex_account_balance,
    and paradex_account_positions separately.

    Returns:
    - summary: account value, free collateral, margin requirements, health status
    - balances: token balances (USDC, DIME, etc.)
    - positions: all open positions with P&L and liquidation prices
    """
    client = await get_authenticated_paradex_client()

    await ctx.report_progress(0, 3, "Fetching account summary...")
    summary_resp = await api_call(client, "account")

    await ctx.report_progress(1, 3, "Fetching balances...")
    balances_resp = client.fetch_balances()
    if "error" in balances_resp:
        await ctx.error(balances_resp["error"])
        raise Exception(balances_resp["error"])

    await ctx.report_progress(2, 3, "Fetching positions...")
    positions_resp = client.fetch_positions()
    if "error" in positions_resp:
        await ctx.error(positions_resp["error"])
        raise Exception(positions_resp["error"])

    return AccountOverview(
        summary=account_summary_adapter.validate_python(summary_resp),
        balances=balance_adapter.validate_python(balances_resp["results"]),
        positions=position_adapter.validate_python(positions_resp["results"]),
    )


@server.tool(
    name="paradex_account_fills",
    title="Trade Fills",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_fills(
    market_id: Annotated[str, Field(description="Filter by market ID.")],
    start_unix_ms: Annotated[int, Field(description="Start time in unix milliseconds.")],
    end_unix_ms: Annotated[int, Field(description="End time in unix milliseconds.")],
    ctx: Context,
) -> list[Fill]:
    """
    Analyze your executed trades to evaluate performance and execution quality.

    Use this tool when you need to:
    - Review your trading history across specific markets
    - Calculate your average entry price for multi-fill positions
    - Analyze execution quality compared to intended prices
    - Track realized PnL from completed trades
    - Verify order execution details for reconciliation

    Detailed fill information is essential for performance analysis and
    understanding how your orders were actually executed.

    Example use cases:
    - Calculating volume-weighted average price (VWAP) of your entries
    - Analyzing execution slippage from your intended prices
    - Reviewing trade history for tax or accounting purposes
    - Tracking commission costs across different markets
    - Identifying which of your strategies produced the best execution
    """
    client = await get_authenticated_paradex_client()
    params = {"market": market_id, "start_at": start_unix_ms, "end_at": end_unix_ms}
    response = client.fetch_fills(params)
    if "error" in response:
        await ctx.error(response["error"])
        raise Exception(response["error"])
    fills = fill_adapter.validate_python(response["results"])
    await ctx_info(
        ctx, f"Found {len(fills)} fills for market {market_id}", logger_name="paradex.account"
    )
    return fills


@server.tool(
    name="paradex_account_funding_payments",
    title="Funding Payments",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_funding_payments(
    market_id: Annotated[str | None, Field(default=None, description="Filter by market ID.")],
    start_unix_ms: Annotated[int, Field(description="Start time in unix milliseconds.")],
    end_unix_ms: Annotated[int, Field(description="End time in unix milliseconds.")],
    ctx: Context,
) -> dict:
    """
    Track your funding payment history to understand its impact on P&L.

    Use this tool when you need to:
    - Calculate total funding costs or gains for a position
    - Analyze how funding has affected your overall performance
    - Plan position timing around funding payment schedules
    - Compare funding costs across different markets
    - Account for funding in your trading strategy profitability

    Funding payments can significantly impact perpetual futures trading P&L,
    especially for longer-term positions or in markets with volatile funding rates.

    Example use cases:
    - Calculating the total funding component of your P&L
    - Comparing funding costs against trading profits
    - Planning position entries/exits around funding payment times
    - Identifying markets where funding has been consistently favorable
    - Reconciling funding payments for accounting purposes
    """
    client = await get_authenticated_paradex_client()
    params = {"market": market_id, "start_at": start_unix_ms, "end_at": end_unix_ms}
    params = {k: v for k, v in params.items() if v is not None}
    response = client.fetch_funding_payments(params)
    return response  # type: ignore[no-any-return]


@server.tool(
    name="paradex_account_transactions",
    title="Account Transactions",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_transactions(
    transaction_type: Annotated[
        str | None, Field(default=None, description="Filter by transaction type.")
    ],
    start_unix_ms: Annotated[int, Field(description="Start time in unix milliseconds.")],
    end_unix_ms: Annotated[int, Field(description="End time in unix milliseconds.")],
    limit: Annotated[
        int, Field(default=50, description="Maximum number of transactions to return.")
    ],
    ctx: Context,
) -> list[Transaction]:
    """
    Get account transaction history.

    Retrieves a filtered history of account transactions, including deposits,
    withdrawals, trades, funding payments, and other account activities.
    Use transaction_type and time filters to limit the results and avoid
    overwhelming the client.

    This tool is valuable for:
    - Reconciliation of account activity
    - Auditing trading history
    - Tracking deposits and withdrawals
    - Analyzing funding payments over time

    """
    client = await get_authenticated_paradex_client()
    params = {
        "type": transaction_type,
        "start_at": start_unix_ms,
        "end_at": end_unix_ms,
        "limit": limit,
    }
    params = {k: v for k, v in params.items() if v is not None}
    response = client.fetch_transactions(params)
    if "error" in response:
        await ctx.error(response["error"])
        raise Exception(response["error"])
    transactions = transaction_adapter.validate_python(response["results"])
    await ctx_info(ctx, f"Found {len(transactions)} transactions", logger_name="paradex.account")
    return transactions


@server.tool(
    name="paradex_pre_trade_check",
    title="Pre-Trade Check",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def pre_trade_check(
    market_id: Annotated[str, Field(description="Market symbol, e.g. 'BTC-USD-PERP'.")],
    side: Annotated[str, Field(description="Order side: 'BUY' or 'SELL'.")],
    size: Annotated[float, Field(description="Desired order size in base asset units.", gt=0)],
    ctx: Context,
) -> PreTradeCheckResult:
    """
    Validate a trade idea before submitting an order.

    Use this tool when you need to:
    - Confirm your account has sufficient free collateral for a trade
    - Check whether a given order size is within market limits
    - Get current bid/ask and existing position in one call
    - Receive a single ready_to_trade flag with human-readable reasons if not ready

    Use this instead of calling paradex_account_summary, paradex_account_positions,
    paradex_market_summaries, and paradex_markets separately before placing an order.

    Returns:
    - account_status: account health (ACTIVE, LIQUIDATION, etc.)
    - free_collateral: available collateral for new positions
    - current_position: existing open position in this market, if any
    - bbo: best bid/ask, mark price, and current funding rate
    - market_constraints: tick size, min notional, position limit, order size increment
    - estimates: fee, slippage, funding cost, and break-even using the account's actual fee tier
    - ready_to_trade: True when account is healthy, collateral is positive,
      and size is within market limits
    - not_ready_reasons: list of reasons why ready_to_trade is False (empty when True)
    """
    auth_client, public_client = await asyncio.gather(
        get_authenticated_paradex_client(),
        get_paradex_client(),
    )

    await ctx.report_progress(
        0, 4, "Fetching account, positions, market summary, constraints, and fees..."
    )

    (
        account_resp,
        positions_resp,
        summaries_resp,
        markets_resp,
        account_info_resp,
    ) = await asyncio.gather(
        api_call(auth_client, "account"),
        asyncio.to_thread(auth_client.fetch_positions),
        asyncio.to_thread(public_client.fetch_markets_summary, params={"market": market_id}),
        asyncio.to_thread(public_client.fetch_markets),
        asyncio.to_thread(auth_client.fetch_account_info),
    )

    await ctx.report_progress(1, 4, "Parsing account and position data...")

    if "error" in positions_resp:
        raise Exception(positions_resp["error"])
    if "error" in summaries_resp:
        raise Exception(summaries_resp["error"])
    if "error" in markets_resp:
        raise Exception(markets_resp["error"])

    account = account_summary_adapter.validate_python(account_resp)

    all_positions = position_adapter.validate_python(positions_resp["results"])
    current_position = next(
        (p for p in all_positions if p.market == market_id and p.status == "OPEN"), None
    )

    await ctx.report_progress(2, 4, "Parsing market data...")

    summaries = market_summary_adapter.validate_python(summaries_resp["results"])
    market_summary = next((s for s in summaries if s.symbol == market_id), None)
    if market_summary is None:
        raise Exception(f"Market {market_id} not found in summaries")

    all_markets = market_details_adapter.validate_python(markets_resp["results"])
    market_details = next((m for m in all_markets if m.symbol == market_id), None)
    if market_details is None:
        raise Exception(f"Market {market_id} not found in market details")

    # Extract actual taker fee rate from account info; fall back to default if unavailable.
    # Different asset kinds have separate fee tiers in the account's fees object.
    taker_fee_rate = _default_taker_fee_rate
    try:
        fees = (account_info_resp.get("fees") or {}) if isinstance(account_info_resp, dict) else {}
        fee_field = _FEE_FIELD_BY_ASSET_KIND.get(market_details.asset_kind or "", "taker_rate")
        taker_rate_str = fees.get(fee_field) or fees.get("taker_rate")
        if taker_rate_str:
            taker_fee_rate = float(taker_rate_str)
    except (ValueError, TypeError, AttributeError):
        pass

    await ctx.report_progress(3, 4, "Computing readiness and estimates...")

    not_ready_reasons = _check_readiness(account, market_details, size)
    estimates = _compute_estimates(market_summary, size, side, current_position, taker_fee_rate)

    await ctx_info(
        ctx,
        f"Pre-trade check for {side} {size} {market_id}: ready={not not_ready_reasons}",
        logger_name="paradex.account",
    )

    return PreTradeCheckResult(
        market_id=market_id,
        side=side,
        size=size,
        account_status=account.status or "",
        free_collateral=account.free_collateral or "",
        current_position=current_position,
        bbo=PreTradeBBO(
            bid=market_summary.bid or "",
            ask=market_summary.ask or "",
            mark_price=market_summary.mark_price or "",
            funding_rate=market_summary.funding_rate or "",
        ),
        market_constraints=PreTradeMarketConstraints(
            min_notional=float(market_details.min_notional or 0),
            order_size_increment=market_details.order_size_increment or "",
            position_limit=float(market_details.position_limit or 0),
            price_tick_size=float(market_details.price_tick_size or 0),
        ),
        estimates=estimates,
        ready_to_trade=not not_ready_reasons,
        not_ready_reasons=not_ready_reasons,
    )
