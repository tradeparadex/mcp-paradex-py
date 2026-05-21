"""
Vault management tools for Paradex.

This module provides tools for retrieving information about Paradex vaults,
which are smart contracts that allow users to deposit funds and trade on Paradex
with self-custody. These tools help with monitoring vault status, balances,
positions, and transaction history.
"""

import logging
from typing import Annotated

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from mcp_paradex.models import (
    PagedVaults,
    PagedVaultSummaries,
    Position,
    Vault,
    VaultAccountSummary,
    VaultBalance,
    VaultOverview,
    VaultStrategy,
    VaultSummary,
)
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_debug, ctx_info
from mcp_paradex.utils.errors import check_response
from mcp_paradex.utils.jmespath_utils import apply_jmespath_filter
from mcp_paradex.utils.paradex_client import api_call, get_paradex_client

logger = logging.getLogger(__name__)

vault_strategy_adapter = TypeAdapter(list[VaultStrategy])
vault_adapter = TypeAdapter(list[Vault])


@server.tool(
    name="paradex_vaults",
    title="Vaults",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_vaults(
    vault_address: Annotated[
        str,
        Field(
            default="",
            description="The address of the vault to get details for or empty string to get all vaults.",
        ),
    ],
    jmespath_filter: Annotated[
        str,
        Field(
            default=None, description="JMESPath expression to filter, sort, or limit the results."
        ),
    ],
    limit: Annotated[
        int,
        Field(
            default=10,
            gt=0,
            le=100,
            description="Limit the number of results to the specified number.",
        ),
    ],
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Offset the results to the specified number.",
        ),
    ],
    ctx: Context,
) -> PagedVaults:
    """
    Get detailed information about a specific vault or all vaults if no address is provided.

    Retrieves comprehensive details about a specific vault identified by its address,
    including configuration, permissions, and other vault-specific parameters.

    Use jmespath_filter to reduce the number of results as much as possible as number of vaults can be large.

    You can use JMESPath expressions to filter, sort, or limit the results.
    Examples:
    - Filter by owner: "[?owner_account=='0x123...']"
    - Filter by status: "[?status=='ACTIVE']"
    - Find vaults with specific strategy: "[?contains(strategies, 'strategy_id')]"
    - Sort by creation date: "sort_by([*], &created_at)"
    - Limit to newest vaults: "sort_by([*], &created_at)[-5:]"
    - Select specific fields: "[*].{address: address, name: name, kind: kind, status: status}"
    """
    client = await get_paradex_client()
    params = {"address": vault_address} if vault_address else None
    response = await api_call(client, "vaults", params=params)
    response = await check_response(ctx, response, path="vaults")
    vaults = vault_adapter.validate_python(response["results"])

    if jmespath_filter:
        await ctx_debug(
            ctx, f"Applying JMESPath filter: {jmespath_filter}", logger_name="paradex.vaults"
        )
        vaults = apply_jmespath_filter(
            data=vaults,
            jmespath_filter=jmespath_filter,
            type_adapter=vault_adapter,
            error_logger=logger.error,
        )
    sorted_vaults = sorted(vaults, key=lambda x: x.created_at, reverse=True)
    await ctx_info(
        ctx,
        f"Returning {min(limit, len(sorted_vaults))} of {len(sorted_vaults)} vaults",
        logger_name="paradex.vaults",
    )
    result_vaults = sorted_vaults[offset : offset + limit]
    return PagedVaults(
        results=result_vaults,
        total=len(sorted_vaults),
        limit=limit,
        offset=offset,
    )


vault_balance_adapter = TypeAdapter(list[VaultBalance])


vault_summary_adapter = TypeAdapter(list[VaultSummary])


@server.tool(
    name="paradex_vault_summary",
    title="Vault Summary",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_vault_summary(
    vault_address: Annotated[
        str,
        Field(
            default=None,
            description="The address of the vault to get summary for or None to get all vaults.",
        ),
    ],
    jmespath_filter: Annotated[
        str,
        Field(default=None, description="JMESPath expression to filter or transform the result."),
    ],
    limit: Annotated[
        int,
        Field(
            default=10,
            gt=0,
            le=100,
            description="Limit the number of results to the specified number.",
        ),
    ],
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Offset the results to the specified number.",
        ),
    ],
    ctx: Context,
) -> PagedVaultSummaries:
    """
    Get a comprehensive summary of a specific vault or all vaults if no address is provided.

    Retrieves a summary of all important information about a vault,
    including balance, positions, recent activity, and performance metrics.
    This provides a high-level overview of the vault's current state.

    Use jmespath_filter to reduce the number of results as much as possible as number of vaults can be large.

    You can use JMESPath expressions to filter, sort, or transform the results.
    Examples:
    - Filter by TVL: "[?to_number(tvl) > `10000`]"
    - Filter by performance: "[?to_number(total_roi) > `5.0`]"
    - Sort by TVL (descending): "reverse(sort_by([*], &to_number(tvl)))"
    - Get top performers: "sort_by([*], &to_number(total_roi))[-3:]"
    - Filter by recent returns: "[?to_number(roi_24h) > `0.5`]"
    - Extract specific metrics: "[*].{address: address, tvl: tvl, total_roi: total_roi, volume_24h: volume_24h}"
    """
    client = await get_paradex_client()
    params = {"address": vault_address} if vault_address else None
    response = await api_call(client, "vaults/summary", params=params)
    response = await check_response(ctx, response, path="vaults/summary")
    summary = vault_summary_adapter.validate_python(response["results"])

    if jmespath_filter:
        await ctx_debug(
            ctx,
            f"Applying JMESPath filter: {jmespath_filter}",
            logger_name="paradex.vaults",
        )
        summary = apply_jmespath_filter(
            data=summary,
            jmespath_filter=jmespath_filter,
            type_adapter=vault_summary_adapter,
            error_logger=logger.error,
        )
    sorted_summary = sorted(summary, key=lambda x: x.address, reverse=True)
    await ctx_info(
        ctx,
        f"Returning {min(limit, len(sorted_summary))} of {len(sorted_summary)} vault summaries",
        logger_name="paradex.vaults",
    )
    result_summary = sorted_summary[offset : offset + limit]
    return PagedVaultSummaries(
        results=result_summary,
        total=len(sorted_summary),
        limit=limit,
        offset=offset,
    )


@server.tool(
    name="paradex_vault_transfers",
    title="Vault Transfers",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_vault_transfers(
    vault_address: Annotated[
        str, Field(description="The address of the vault to get transfers for.")
    ],
    ctx: Context,
) -> dict:
    """
    Track deposit and withdrawal history for auditing and reconciliation.

    Use this tool when you need to:
    - Verify deposits have completed and are available for trading
    - Track withdrawal status and confirm transaction settlement
    - Audit the complete fund flow history for a vault
    - Reconcile on-chain transactions with platform records
    - Understand historical capital allocation patterns

    Complete transfer history is essential for proper accounting and provides
    a clear audit trail of all capital movements.

    Example use cases:
    - Confirming that a recent deposit was credited to your account
    - Tracking the status of pending withdrawals
    - Creating transaction reports for accounting or tax purposes
    - Verifying the total amount deposited over time
    - Analyzing deposit/withdrawal patterns for strategy insights
    """
    client = await get_paradex_client()
    response = await api_call(client, "vaults/transfers", params={"address": vault_address})
    response = await check_response(ctx, response, path="vaults/transfers")
    return response["results"]  # type: ignore[no-any-return]


position_adapter = TypeAdapter(list[Position])
vault_account_summary_adapter = TypeAdapter(list[VaultAccountSummary])


@server.tool(
    name="paradex_vault_overview",
    title="Vault Overview",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_vault_overview(
    vault_address: Annotated[str, Field(description="The vault contract address.")],
    ctx: Context,
) -> VaultOverview:
    """
    Get a complete operational snapshot of a vault: token balances, open positions,
    and trading account health in a single call.

    Use this instead of calling paradex_vault_balance, paradex_vault_positions,
    and paradex_vault_account_summary separately.

    Returns:
    - balances: vault token balances
    - positions: all open positions with P&L and liquidation prices
    - account_summary: margin health, free collateral, leverage
    """
    client = await get_paradex_client()

    await ctx.report_progress(0, 3, "Fetching vault balances...")
    balance_resp = await api_call(client, "vaults/balance", params={"address": vault_address})

    await ctx.report_progress(1, 3, "Fetching vault positions...")
    positions_resp = await api_call(client, "vaults/positions", params={"address": vault_address})

    await ctx.report_progress(2, 3, "Fetching vault account summary...")
    account_resp = await api_call(
        client, "vaults/account-summary", params={"address": vault_address}
    )

    balance_resp = await check_response(ctx, balance_resp, path="vaults/balance")
    positions_resp = await check_response(ctx, positions_resp, path="vaults/positions")
    account_resp = await check_response(ctx, account_resp, path="vaults/account-summary")

    return VaultOverview(
        balances=vault_balance_adapter.validate_python(balance_resp["results"]),
        positions=position_adapter.validate_python(positions_resp["results"]),
        account_summary=vault_account_summary_adapter.validate_python(account_resp["results"]),
    )
