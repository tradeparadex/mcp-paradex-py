"""
Paradex API client utilities.
"""

import asyncio
import logging
import time
from contextvars import ContextVar
from typing import Any

import httpx
from paradex_py.account.account import ParadexAccount
from paradex_py.account.subkey_account import SubkeyAccount
from paradex_py.api.api_client import ParadexApiClient

from mcp_paradex.utils.config import config

logger = logging.getLogger(__name__)

# Singleton instance of the Paradex client
_paradex_client: ParadexApiClient | None = None
_client_lock = asyncio.Lock()

# Set by BearerAuthMiddleware for each HTTP request; None means no Bearer token present.
_request_bearer_token: ContextVar[str | None] = ContextVar("bearer_token", default=None)


def _make_jwt_client(jwt: str) -> ParadexApiClient:
    """Create a Paradex client authenticated with a JWT token (no private key needed)."""
    http_client = httpx.Client(
        transport=httpx.HTTPTransport(retries=1),
        timeout=httpx.Timeout(30.0),
    )
    client = ParadexApiClient(
        env=config.ENVIRONMENT,
        logger=logger,
        http_client=http_client,
        auth_params={"token_usage": "interactive"},
    )
    client.set_token(jwt)
    return client


async def get_paradex_client() -> ParadexApiClient:
    """
    Get or initialize the Paradex client.

    Returns:
        Paradex: The initialized Paradex client.

    Raises:
        ValueError: If the required configuration is not set.
    """
    # Per-request Bearer token takes precedence over the singleton.
    bearer_token = _request_bearer_token.get()
    if bearer_token:
        return _make_jwt_client(bearer_token)

    global _paradex_client

    if _paradex_client is not None:
        return _paradex_client

    async with _client_lock:
        # Double-check in case another task initialized it while waiting
        if _paradex_client is not None:
            return _paradex_client

        logger.info("Initializing Paradex client env=%s", config.ENVIRONMENT)
        # retries=1 on the transport causes httpx to retry automatically on a fresh
        # connection when a pooled connection is stale (e.g. after a Lambda freeze).
        http_client = httpx.Client(
            transport=httpx.HTTPTransport(retries=1),
            timeout=httpx.Timeout(30.0),
        )
        _paradex_client = ParadexApiClient(
            env=config.ENVIRONMENT,
            logger=logger,
            http_client=http_client,
            auth_params={"token_usage": "interactive"},
        )
        logger.info("Paradex client api_url=%s", _paradex_client.api_url)

        if config.PARADEX_ACCOUNT_PRIVATE_KEY:
            response = _paradex_client.fetch_system_config()
            if config.PARADEX_ACCOUNT_ADDRESS:
                # Use SubkeyAccount for any L2 key + address pair.
                # Works for both main account keys and registered subkeys
                # (same pattern as the SDK's ParadexL2 high-level client).
                logger.info("Authenticating Paradex client via L2 key + address")
                acc: ParadexAccount = SubkeyAccount(
                    config=response,
                    l2_private_key=config.PARADEX_ACCOUNT_PRIVATE_KEY,
                    l2_address=config.PARADEX_ACCOUNT_ADDRESS,
                )
            else:
                logger.info("Authenticating Paradex client via private key")
                acc = ParadexAccount(
                    config=response,
                    l1_address="0x0000000000000000000000000000000000000000",
                    l2_private_key=config.PARADEX_ACCOUNT_PRIVATE_KEY,
                )
            _paradex_client.init_account(acc)
            logger.info("Paradex client authenticated account=%s", _paradex_client.account)
        elif config.PARADEX_JWT_TOKEN:
            logger.info("Authenticating Paradex client via JWT token")
            _paradex_client.set_token(config.PARADEX_JWT_TOKEN)

        return _paradex_client


async def get_authenticated_paradex_client() -> ParadexApiClient:
    """
    Get or initialize the authenticated Paradex client.

    Returns:
        Paradex: The initialized Paradex client.

    Raises:
        ValueError: If the required configuration is not set.
    """
    # Per-request Bearer token always yields an authenticated client.
    bearer_token = _request_bearer_token.get()
    if bearer_token:
        return _make_jwt_client(bearer_token)

    client = await get_paradex_client()
    # For JWT-token singleton mode, set_token was called but account is None — that's OK.
    # We detect authentication by checking either account or the JWT token config.
    if client.account is None and not config.PARADEX_JWT_TOKEN:
        raise ValueError("Paradex client is not authenticated")
    return client


async def api_call(
    client: ParadexApiClient, path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Make a direct API call to Paradex.

    Args:
        client: The Paradex client instance.
        path: The API path to call.
        params: Optional parameters for the API call.

    Returns:
        Dict[str, Any]: The response from the API call.
    """
    from mcp_paradex.utils.telemetry import SpanKind, get_tracer

    url = f"{client.api_url}/{path}"
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"paradex.api {path}",
        kind=SpanKind.CLIENT,
        attributes={"http.url": url, "peer.service": "paradex-api"},
    ):
        logger.info("API call url=%s params=%s", url, params)
        t0 = time.monotonic()
        try:
            response = client.get(client.api_url, path, params)
            logger.info("API call url=%s completed ms=%.0f", url, (time.monotonic() - t0) * 1000)
            return response  # type: ignore[no-any-return]
        except Exception as exc:
            logger.error(
                "API call url=%s failed ms=%.0f error=%s: %s",
                url,
                (time.monotonic() - t0) * 1000,
                type(exc).__name__,
                exc,
            )
            raise
