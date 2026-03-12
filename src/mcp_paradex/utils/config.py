"""
Configuration utilities for the MCP Paradex server.
"""

import os
from enum import Enum

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

    PARADEX_ACCOUNT_ADDRESS: str | None = os.getenv("PARADEX_ACCOUNT_ADDRESS")
    PARADEX_ACCOUNT_PRIVATE_KEY: str | None = os.getenv("PARADEX_ACCOUNT_PRIVATE_KEY")

    # JWT-based auth (alternative to private key)
    PARADEX_JWT_TOKEN: str | None = os.getenv("PARADEX_JWT_TOKEN")
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
                cls.PARADEX_AUTH_SERVER_URL is not None,
            ]
        )


config = Config()
