"""
Tests for JWT token expiry detection and automatic refresh.

Covers:
- api_call() calls _validate_auth() for authenticated clients
- api_call() skips _validate_auth() for unauthenticated (public) clients
- Private-key client auto-refreshes when token is expired
- JWT-only client (auto_auth=False) does not raise "Account not found" on expiry
"""

import time
from unittest.mock import MagicMock, patch

import pytest

import mcp_paradex.utils.paradex_client as _client_module
from mcp_paradex.utils.paradex_client import api_call

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(*, has_account: bool = False, has_manual_token: bool = False) -> MagicMock:
    client = MagicMock()
    client.account = MagicMock() if has_account else None
    client._manual_token = "tok" if has_manual_token else None
    client.api_url = "https://api.prod.paradex.trade/v1"
    client.get.return_value = {"results": []}
    return client


# ---------------------------------------------------------------------------
# api_call() / _validate_auth() gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_call_validates_auth_when_account_set():
    """api_call() must call _validate_auth() when client has an account."""
    client = _make_mock_client(has_account=True)
    await api_call(client, "account")
    client._validate_auth.assert_called_once()


@pytest.mark.asyncio
async def test_api_call_validates_auth_when_manual_token_set():
    """api_call() must call _validate_auth() when client has a manual JWT token."""
    client = _make_mock_client(has_manual_token=True)
    await api_call(client, "account")
    client._validate_auth.assert_called_once()


@pytest.mark.asyncio
async def test_api_call_skips_validate_auth_for_public_client():
    """api_call() must NOT call _validate_auth() for unauthenticated public clients."""
    client = _make_mock_client(has_account=False, has_manual_token=False)
    await api_call(client, "system/config")
    client._validate_auth.assert_not_called()


# ---------------------------------------------------------------------------
# SDK _validate_auth() behaviour — private-key (auto_auth=True) mode
# ---------------------------------------------------------------------------


def _make_real_api_client(*, expired: bool, auto_auth: bool = True):
    """Build a ParadexApiClient with mocked internals, bypassing __init__."""
    from paradex_py.api.api_client import ParadexApiClient

    client = ParadexApiClient.__new__(ParadexApiClient)
    client.auto_auth = auto_auth
    client.account = MagicMock() if auto_auth else None
    client.auth_provider = None
    client._manual_token = None if auto_auth else "static.jwt.token"
    client._token_exp = time.time() - 60 if expired else time.time() + 300
    client.auth_timestamp = int(time.time()) - (120 if expired else 10)
    client.auth_params = {"token_usage": "interactive"}
    client.classname = "ParadexApiClient"
    client.logger = MagicMock()
    client.on_token_expired = None
    client.api_url = "https://api.prod.paradex.trade/v1"
    client._is_evm_account = False
    return client


def test_validate_auth_calls_auth_when_token_expired():
    """Private-key client: _validate_auth() must call auth() when the token is expired."""
    client = _make_real_api_client(expired=True, auto_auth=True)
    with patch.object(client, "auth") as mock_auth:
        client._validate_auth()
    mock_auth.assert_called_once_with(params={"token_usage": "interactive"})


def test_validate_auth_skips_auth_when_token_fresh():
    """Private-key client: _validate_auth() must NOT call auth() when token is still valid."""
    client = _make_real_api_client(expired=False, auto_auth=True)
    with patch.object(client, "auth") as mock_auth:
        client._validate_auth()
    mock_auth.assert_not_called()


# ---------------------------------------------------------------------------
# JWT-only mode (auto_auth=False) — no "Account not found" on expiry
# ---------------------------------------------------------------------------


def test_validate_auth_no_error_for_jwt_client_with_expired_token():
    """JWT client (auto_auth=False): _validate_auth() must not raise on token expiry."""
    client = _make_real_api_client(expired=True, auto_auth=False)
    # Should not raise ValueError("Account not found")
    client._validate_auth()  # warns via logger, does not raise


# ---------------------------------------------------------------------------
# End-to-end: api_call() triggers auth() refresh for expired private-key client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_call_triggers_token_refresh_on_expiry():
    """Full chain: api_call() with expired private-key client calls auth() before the request."""
    client = _make_real_api_client(expired=True, auto_auth=True)

    with (
        patch.object(client, "auth") as mock_auth,
        patch.object(client, "get", return_value={"results": []}) as mock_get,
    ):
        await api_call(client, "account")

    mock_auth.assert_called_once()
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_api_call_no_refresh_when_token_fresh():
    """Full chain: api_call() with a valid token does NOT call auth()."""
    client = _make_real_api_client(expired=False, auto_auth=True)

    with (
        patch.object(client, "auth") as mock_auth,
        patch.object(client, "get", return_value={"results": []}) as mock_get,
    ):
        await api_call(client, "account")

    mock_auth.assert_not_called()
    mock_get.assert_called_once()
