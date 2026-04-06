"""
Configuration utilities for the MCP Paradex server.
"""

import os
from enum import Enum

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _sanitize_env(value: str | None) -> str | None:
    """Return None for unsubstituted MCPB template variables like ${user_config.foo}."""
    if value and value.startswith("${") and value.endswith("}"):
        return None
    return value or None


class Environment(str, Enum):
    """Trading environment options."""

    TESTNET = "testnet"
    PROD = "prod"


class Config:
    """Configuration settings for the MCP Paradex server."""

    # Server configuration
    SERVER_NAME: str = os.getenv("SERVER_NAME", "Paradex Trading")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "3000"))

    # Paradex configuration
    ENVIRONMENT: str = os.getenv("PARADEX_ENVIRONMENT", "prod")

    PARADEX_ACCOUNT_ADDRESS: str | None = _sanitize_env(os.getenv("PARADEX_ACCOUNT_ADDRESS"))
    PARADEX_ACCOUNT_PRIVATE_KEY: str | None = _sanitize_env(
        os.getenv("PARADEX_ACCOUNT_PRIVATE_KEY")
    )

    # JWT-based auth (alternative to private key)
    PARADEX_JWT_TOKEN: str | None = _sanitize_env(os.getenv("PARADEX_JWT_TOKEN"))
    # Long-term API key (JWT) — exposed as user_config.paradex_api_key in the MCPB manifest.
    # Account address is auto-extracted from the token payload at startup.
    PARADEX_API_KEY: str | None = _sanitize_env(os.getenv("PARADEX_API_KEY"))
    # OAuth Resource Server config (for HTTP mode)
    MCP_SERVER_URL: str | None = os.getenv("MCP_SERVER_URL")
    PARADEX_AUTH_SERVER_URL: str | None = os.getenv("PARADEX_AUTH_SERVER_URL")

    @classmethod
    def is_configured(cls) -> bool:
        """Check if all required configuration is set."""
        return any(
            [
                cls.PARADEX_ACCOUNT_PRIVATE_KEY is not None,
                cls.PARADEX_JWT_TOKEN is not None,
                cls.PARADEX_API_KEY is not None,
                cls.PARADEX_AUTH_SERVER_URL is not None,
            ]
        )


config = Config()


def _decode_jwt_payload(token: str) -> dict:
    """Decode the payload segment of a JWT without verifying the signature."""
    import base64
    import json as _json

    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return _json.loads(base64.urlsafe_b64decode(padded))  # type: ignore[no-any-return]


def _extract_account_from_jwt(token: str) -> str | None:
    """Return the account address embedded in a Paradex JWT payload, or None."""
    try:
        payload = _decode_jwt_payload(token)
    except Exception:
        return None
    for key in ("account", "account_address", "sub"):
        value = payload.get(key)
        if value and isinstance(value, str):
            return str(value)
    return None


# Map PARADEX_API_KEY → PARADEX_JWT_TOKEN so the rest of the implementation is unchanged.
if config.PARADEX_API_KEY and not config.PARADEX_JWT_TOKEN:
    config.PARADEX_JWT_TOKEN = config.PARADEX_API_KEY

# Auto-populate account address from API key JWT when not explicitly configured.
if config.PARADEX_API_KEY and not config.PARADEX_ACCOUNT_ADDRESS:
    _addr = _extract_account_from_jwt(config.PARADEX_API_KEY)
    if _addr:
        config.PARADEX_ACCOUNT_ADDRESS = _addr
