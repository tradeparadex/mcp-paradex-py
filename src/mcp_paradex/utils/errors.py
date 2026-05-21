"""
Typed errors for the Paradex MCP server.

`ParadexApiError` carries enough structured detail (HTTP path, status, error
code, message) that an MCP client sees something actionable instead of a bare
`Exception("internal error")`.
"""

from __future__ import annotations

import contextlib
from typing import Any


class ParadexApiError(Exception):
    """A failure reported by the Paradex API."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.status = status
        self.code = code
        super().__init__(self._format())

    def _format(self) -> str:
        parts: list[str] = []
        if self.path:
            parts.append(f"path={self.path}")
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.code:
            parts.append(f"code={self.code}")
        prefix = " ".join(parts)
        return f"paradex API error ({prefix}): {self.message}" if prefix else self.message


def _extract_error(resp: Any) -> tuple[str | None, str | None]:
    """Return (code, message) if `resp` is a Paradex API error envelope.

    Paradex returns errors in a few shapes:
    - `{"error": "...message..."}`
    - `{"error": {"code": "...", "message": "..."}}`
    - `{"message": "...", "code": "..."}` (nested under "error" or top-level)
    """
    if not isinstance(resp, dict):
        return None, None
    err = resp.get("error")
    if isinstance(err, str):
        return None, err
    if isinstance(err, dict):
        return err.get("code"), err.get("message") or err.get("error")
    # No "error" key — some endpoints return top-level message/code on failure.
    if "message" in resp and ("code" in resp or "status" in resp):
        msg = resp.get("message")
        code = resp.get("code")
        if isinstance(msg, str) and isinstance(code, str | None):
            return code, msg
    return None, None


async def check_response(ctx: Any, resp: Any, *, path: str) -> Any:
    """Raise `ParadexApiError` if `resp` carries an API error; otherwise return it.

    Also reports the failure via `ctx.error` so it surfaces in MCP log channels.
    """
    code, message = _extract_error(resp)
    if message is None:
        return resp
    err = ParadexApiError(message, path=path, code=code)
    # ctx.error is async and may fail when there's no live session; ignore.
    with contextlib.suppress(Exception):
        await ctx.error(str(err))
    raise err
