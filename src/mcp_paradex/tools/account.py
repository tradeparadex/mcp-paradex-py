"""
Account management tools.
"""

import asyncio
from typing import Annotated, Any

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from mcp_paradex.models import (
    AccountCredentials,
    AccountInfo,
    AccountMarginConfig,
    AccountOverview,
    AccountSummary,
    ApiToken,
    Balance,
    Fill,
    Position,
    Subkey,
    Transaction,
)
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info
from mcp_paradex.utils.errors import check_response
from mcp_paradex.utils.paradex_client import (
    api_call,
    get_authenticated_paradex_client,
)

account_summary_adapter = TypeAdapter(AccountSummary)
balance_adapter = TypeAdapter(list[Balance])
position_adapter = TypeAdapter(list[Position])
fill_adapter = TypeAdapter(list[Fill])
transaction_adapter = TypeAdapter(list[Transaction])


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
    response = await check_response(ctx, client.fetch_balances(), path="balance")
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
    response = await check_response(ctx, client.fetch_positions(), path="positions")
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
    open positions, fee rates, and margin methodology in a single call.

    Use this instead of calling paradex_account_summary, paradex_account_balance,
    and paradex_account_positions separately.

    Returns:
    - summary: account value, free collateral, margin requirements, health status
    - balances: token balances (USDC, DIME, etc.)
    - positions: all open positions with P&L and liquidation prices
    - info: account fees (maker/taker rates for all product types), account kind,
      and isolation mode if applicable
    - margin: margin methodology (cross_margin or portfolio_margin) and per-market
      leverage/margin-type configuration
    """
    client = await get_authenticated_paradex_client()

    await ctx.report_progress(0, 2, "Fetching account data...")

    (
        summary_resp,
        balances_resp,
        positions_resp,
        info_resp,
        margin_resp,
    ) = await asyncio.gather(
        api_call(client, "account"),
        asyncio.to_thread(client.fetch_balances),
        asyncio.to_thread(client.fetch_positions),
        asyncio.to_thread(client.fetch_account_info),
        api_call(client, "account/margin"),
        return_exceptions=True,
    )

    await ctx.report_progress(1, 2, "Building overview...")

    if isinstance(summary_resp, Exception):
        raise summary_resp
    if isinstance(balances_resp, Exception):
        raise balances_resp
    if isinstance(positions_resp, Exception):
        raise positions_resp
    balances_resp = await check_response(ctx, balances_resp, path="balance")
    positions_resp = await check_response(ctx, positions_resp, path="positions")

    info: AccountInfo | None = None
    if not isinstance(info_resp, Exception):
        info_list = (info_resp or {}).get("results", [])
        if info_list:
            info = AccountInfo.model_validate(info_list[0])

    margin: AccountMarginConfig | None = None
    if not isinstance(margin_resp, Exception):
        margin = AccountMarginConfig.model_validate(margin_resp)

    return AccountOverview(
        summary=account_summary_adapter.validate_python(summary_resp),
        balances=balance_adapter.validate_python(balances_resp["results"]),
        positions=position_adapter.validate_python(positions_resp["results"]),
        info=info,
        margin=margin,
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
    response = await check_response(ctx, client.fetch_fills(params), path="fills")
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

    Funding payments can significantly impact trading P&L,
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
    response = await check_response(ctx, client.fetch_transactions(params), path="transactions")
    transactions = transaction_adapter.validate_python(response["results"])
    await ctx_info(ctx, f"Found {len(transactions)} transactions", logger_name="paradex.account")
    return transactions


@server.tool(
    name="paradex_account_keys",
    title="Account Keys & Tokens",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_keys(
    include_revoked: Annotated[
        bool,
        Field(default=False, description="Include revoked subkeys in results."),
    ],
    with_invalid_tokens: Annotated[
        bool,
        Field(default=False, description="Include expired or revoked API tokens."),
    ],
    ctx: Context,
) -> AccountCredentials:
    """
    List all credentials registered for this account: Paradex subkeys and API tokens.

    Use this tool when you need to:
    - Audit which subkeys and API tokens have access to the account
    - Verify that a generated subkey was successfully registered on Paradex
    - Check token expiry dates or identify revoked tokens
    - Confirm key setup before starting agent trading

    Returns:
    - subkeys: Paradex keypairs registered for on-chain signing (e.g. agent keys).
      Each subkey includes its `allowed_cidrs` IP allowlist when one is configured —
      use this to audit which network ranges can use the key.
    - tokens: JWT / API key tokens for REST API access. Each token includes its
      `allowed_cidrs` IP allowlist when one is configured.

    Example use cases:
    - After registering a subkey, list keys to confirm it appears as active
    - Reviewing active tokens to identify any that are near expiry
    - Verifying agent credential setup during onboarding
    """
    client = await get_authenticated_paradex_client()
    subkey_params: dict[str, Any] = {}
    if include_revoked:
        subkey_params["include_revoked"] = True
    token_params: dict[str, Any] = {}
    if with_invalid_tokens:
        token_params["with_invalid"] = True

    subkeys_resp, tokens_resp = await asyncio.gather(
        asyncio.to_thread(client.fetch_subkeys, params=subkey_params or None),
        api_call(client, "account/tokens", params=token_params or None),
        return_exceptions=True,
    )

    subkeys: list[Subkey] = (
        [Subkey.model_validate(r) for r in (subkeys_resp or {}).get("results", [])]
        if not isinstance(subkeys_resp, Exception)
        else []
    )
    tokens: list[ApiToken] = (
        [ApiToken.model_validate(t) for t in (tokens_resp or {}).get("results", [])]
        if not isinstance(tokens_resp, Exception)
        else []
    )

    await ctx_info(
        ctx,
        f"Found {len(subkeys)} subkeys, {len(tokens)} tokens",
        logger_name="paradex.account",
    )
    return AccountCredentials(subkeys=subkeys, tokens=tokens)


@server.tool(
    name="paradex_account_profile",
    title="Account Profile & Settings",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_account_profile(ctx: Context) -> dict[str, Any]:
    """
    Get static account profile and display settings.

    Use this tool when you need to:
    - Check your username or referral code
    - Review per-market max slippage limits
    - Inspect referral configuration (commission rate, discount rate, minimum volume)
    - Check TAP affiliate status and share rates
    - Review notification preferences or linked social accounts
    - See the AI agent WebSocket URL for this account

    This data changes infrequently. For live financial data (balances, positions,
    margin health, fee rates), use paradex_account_overview instead.

    Returns:
    - profile: username, referral config, market_max_slippage, notifications,
      social links, TAP/XP rates, NFT holdings, AI agent URL
    - settings: trading_value_display preference (SPOT_NOTIONAL or MARKET_VALUE)
    """
    client = await get_authenticated_paradex_client()
    profile_resp, settings_resp = await asyncio.gather(
        api_call(client, "account/profile"),
        api_call(client, "account/settings"),
        return_exceptions=True,
    )
    result: dict[str, Any] = {}
    if not isinstance(profile_resp, Exception):
        result["profile"] = profile_resp
    if not isinstance(settings_resp, Exception):
        result["settings"] = settings_resp
    return result
