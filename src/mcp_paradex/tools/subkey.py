"""
Subkey management tools for Paradex.

This module provides tools for generating and managing StarkNet subkeys locally.
Private keys are persisted on disk and never leave the agent machine.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from pydantic import Field
from starknet_py.net.signer.stark_curve_signer import KeyPair  # type: ignore[import-not-found]

from mcp_paradex.models import GeneratedSubkey
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info

logger = logging.getLogger(__name__)

# Key storage directory
KEYS_DIR = Path.home() / ".mcp-paradex" / "keys"

_VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@server.tool(
    name="paradex_generate_subkey",
    title="Generate Subkey",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
    ),
)
async def generate_subkey(
    name: Annotated[
        str,
        Field(
            default="",
            description=(
                "Optional label for the key. "
                "Must contain only alphanumeric characters, hyphens, or underscores. "
                "If omitted, a default name is generated from the current timestamp."
            ),
        ),
    ],
    ctx: Context,
) -> GeneratedSubkey:
    """
    Generate a StarkNet keypair for use as a Paradex subkey.

    The private key is persisted locally at ~/.mcp-paradex/keys/ and never
    leaves the machine. Only the public key is returned so the frontend can
    register it on Paradex on behalf of the agent.

    Use this tool when you need to:
    - Provision a new subkey for agent trading
    - Create a keypair before registering the public key on Paradex

    Example use cases:
    - Setting up a new agent with its own trading subkey
    - Rotating to a fresh subkey for an existing account
    """
    try:
        # Determine key name
        sanitized_name = name.strip()
        if not sanitized_name:
            sanitized_name = f"subkey-{int(time.time())}"
        elif not _VALID_NAME_RE.match(sanitized_name):
            raise ValueError(
                f"Invalid key name '{sanitized_name}'. "
                "Use only alphanumeric characters, hyphens, or underscores."
            )

        # Ensure key directory exists with restrictive permissions
        KEYS_DIR.mkdir(parents=True, exist_ok=True)
        KEYS_DIR.chmod(0o700)

        # Generate keypair
        key_pair = KeyPair.generate()
        public_key_hex = hex(key_pair.public_key)
        private_key_hex = hex(key_pair.private_key)

        # Build key data
        key_data = {
            "name": sanitized_name,
            "public_key": public_key_hex,
            "private_key": private_key_hex,
            "created_at": int(time.time()),
        }

        # Write key file atomically with restrictive permissions (0o600).
        # O_EXCL prevents overwriting an existing key with the same name.
        key_file = KEYS_DIR / f"{sanitized_name}.json"
        fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, json.dumps(key_data, indent=2).encode())
        finally:
            os.close(fd)

        await ctx_info(
            ctx,
            f"Generated subkey '{sanitized_name}' with public key {public_key_hex}",
            logger_name="paradex.subkey",
        )

        return GeneratedSubkey(name=sanitized_name, public_key=public_key_hex)

    except FileExistsError:
        msg = f"A key with name '{sanitized_name}' already exists. Choose a different name."
        await ctx.error(msg)
        raise ValueError(msg)
    except ValueError:
        raise
    except Exception as e:
        await ctx.error(f"Error generating subkey: {e!s}")
        raise
