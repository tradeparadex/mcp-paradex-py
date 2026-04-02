"""
Resilient MCP context logging helpers.

These wrappers call ctx.info/debug/warning/error but silently no-op when the
tool is invoked outside a real MCP request (e.g. in tests or CLI introspection),
where the underlying session is not available.
"""

import contextlib
from typing import Any


async def ctx_info(ctx: Any, message: str, logger_name: str | None = None) -> None:
    with contextlib.suppress(Exception):
        await ctx.info(message, logger_name=logger_name)


async def ctx_debug(ctx: Any, message: str, logger_name: str | None = None) -> None:
    with contextlib.suppress(Exception):
        await ctx.debug(message, logger_name=logger_name)


async def ctx_warning(ctx: Any, message: str, logger_name: str | None = None) -> None:
    with contextlib.suppress(Exception):
        await ctx.warning(message, logger_name=logger_name)
