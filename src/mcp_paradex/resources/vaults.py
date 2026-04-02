"""
Vault data resources that don't require authentication.
"""

import logging
from typing import Any

from mcp_paradex.server.server import server
from mcp_paradex.utils.paradex_client import api_call, get_paradex_client

logger = logging.getLogger(__name__)


@server.resource("paradex://vaults")
async def get_vaults() -> dict[str, Any]:
    """
    Get the list of all available vaults on Paradex.

    Returns vault addresses, names, descriptions, owner/operator accounts,
    strategies, status, kind, profit share, lockup period, and TVL cap.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults")
    except Exception as e:
        logger.error(f"Error fetching vaults: {e!s}")
        raise


@server.resource("paradex://vaults/config")
async def get_vaults_config() -> dict[str, Any]:
    """
    Get the global vault configuration (protocol-level parameters).

    Returns platform-wide vault settings such as fee structures,
    deposit/withdrawal limits, and protocol constants.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults/config")
    except Exception as e:
        logger.error(f"Error fetching vaults config: {e!s}")
        raise


@server.resource("paradex://vaults/balance/{vault_id}")
async def get_vault_balance(vault_id: str) -> dict[str, Any]:
    """
    Get the current token balances for a specific vault.

    Returns token name, balance amount, and last-updated timestamp
    for each token held by the vault (e.g. USDC).

    Args:
        vault_id: The contract address of the vault.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults/balance", params={"address": vault_id})
    except Exception as e:
        logger.error(f"Error fetching balance for vault {vault_id}: {e!s}")
        raise


@server.resource("paradex://vaults/summary/{vault_id}")
async def get_vault_summary(vault_id: str) -> dict[str, Any]:
    """
    Get the performance and statistics summary for a specific vault.

    Returns TVL, ROI (24h/7d/30d/all-time), P&L, max drawdown, trading
    volume, vault token price/supply, and number of depositors.

    Args:
        vault_id: The contract address of the vault.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults/summary", params={"address": vault_id})
    except Exception as e:
        logger.error(f"Error fetching summary for vault {vault_id}: {e!s}")
        raise


@server.resource("paradex://vaults/transfers/{vault_id}")
async def get_vault_transfers(vault_id: str) -> dict[str, Any]:
    """
    Get the deposit and withdrawal history for a specific vault.

    Returns the complete transfer history including transaction hashes,
    amounts, directions (deposit/withdrawal), and timestamps.

    Args:
        vault_id: The contract address of the vault.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults/transfers", params={"address": vault_id})
    except Exception as e:
        logger.error(f"Error fetching transfers for vault {vault_id}: {e!s}")
        raise


@server.resource("paradex://vaults/positions/{vault_id}")
async def get_vault_positions(vault_id: str) -> dict[str, Any]:
    """
    Get the open trading positions for a specific vault.

    Returns all open positions with market, side, size, entry price,
    unrealized P&L, liquidation price, and leverage.

    Args:
        vault_id: The contract address of the vault.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults/positions", params={"address": vault_id})
    except Exception as e:
        logger.error(f"Error fetching positions for vault {vault_id}: {e!s}")
        raise


@server.resource("paradex://vaults/account-summary/{vault_id}")
async def get_vault_account_summary(vault_id: str) -> dict[str, Any]:
    """
    Get the trading account health summary for a specific vault.

    Returns margin requirements, free collateral, account value,
    total collateral, and account status (ACTIVE, LIQUIDATION, etc.).

    Args:
        vault_id: The contract address of the vault.
    """
    try:
        client = await get_paradex_client()
        return await api_call(client, "vaults/account-summary", params={"address": vault_id})
    except Exception as e:
        logger.error(f"Error fetching account summary for vault {vault_id}: {e!s}")
        raise
