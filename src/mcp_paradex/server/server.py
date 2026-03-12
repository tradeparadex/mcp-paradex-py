"""
MCP server implementation for Paradex integration.
"""

import argparse
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any

from mcp.server.fastmcp.server import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_paradex import __version__
from mcp_paradex.utils.config import config
from mcp_paradex.utils.paradex_client import _request_bearer_token

# Context variable holding the MCP-Session-Id for the current request.
# Defaults to "-" so log records outside a request context are still valid.
session_id_ctx: ContextVar[str] = ContextVar("session_id", default="-")


class _SessionIdFilter(logging.Filter):
    """Injects session_id from context into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = session_id_ctx.get()  # type: ignore[attr-defined]
        return True


# Configure logging — include session= so all modules get correlation for free.
_handler = logging.StreamHandler()
_handler.addFilter(_SessionIdFilter())
_handler.setFormatter(
    logging.Formatter("%(asctime)s %(name)s %(levelname)s session=%(session_id)s %(message)s")
)
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("mcp-paradex")


class RequestTracingMiddleware:
    """
    Extracts MCP-Session-Id from the request header and stores it in a
    ContextVar so every log line emitted during that request is tagged with
    session=<id>.  Also logs request/response with wall-clock timing.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        session_id = headers.get(b"mcp-session-id", b"").decode() or "-"
        token = session_id_ctx.set(session_id)
        method = scope["method"]
        path = scope["path"]
        t0 = time.monotonic()
        logger.info("request method=%s path=%s", method, path)
        try:
            await self.app(scope, receive, send)
        finally:
            logger.info(
                "response method=%s path=%s ms=%.0f",
                method,
                path,
                (time.monotonic() - t0) * 1000,
            )
            session_id_ctx.reset(token)


class HealthMiddleware:
    """
    Handles GET /health with 200 OK so Lambda Web Adapter readiness checks pass.
    All other requests (including lifespan) are forwarded to the inner app unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/health":
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class BearerAuthMiddleware:
    """
    Extracts Bearer token from the Authorization header and stores it in a
    ContextVar so tool handlers can use it to authenticate Paradex API calls.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            token: str | None = None
            if auth.startswith("Bearer "):
                token = auth.removeprefix("Bearer ").strip() or None
            ctx_token = _request_bearer_token.set(token)
            try:
                await self.app(scope, receive, send)
            finally:
                _request_bearer_token.reset(ctx_token)
        else:
            await self.app(scope, receive, send)


class OAuthResourceMetadataMiddleware:
    """
    Handles GET /.well-known/oauth-protected-resource (RFC 9728) to advertise
    the OAuth Authorization Server that MCP clients should use to obtain tokens.
    All other requests are forwarded unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and scope["path"] == "/.well-known/oauth-protected-resource"
        ):
            metadata: dict[str, Any] = {
                "bearer_methods_supported": ["header"],
            }
            if config.MCP_SERVER_URL:
                metadata["resource"] = config.MCP_SERVER_URL
            if config.PARADEX_AUTH_SERVER_URL:
                metadata["authorization_servers"] = [config.PARADEX_AUTH_SERVER_URL]
            response = JSONResponse(metadata)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RejectGetMiddleware:
    """
    Rejects GET requests with 405 in stateless HTTP mode.

    In stateless mode (Lambda), GET /mcp would open a persistent SSE stream that
    Lambda cannot hold open. Returning 405 causes MCP clients to fall back to
    POST-only mode, which works correctly with Lambda's request/response model.
    """

    def __init__(self, app: ASGIApp, mcp_path: str = "/mcp") -> None:
        self.app = app
        self.mcp_path = mcp_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"] == self.mcp_path:
            response = Response(
                content="Method Not Allowed: GET is not supported in stateless mode",
                status_code=405,
                headers={"Allow": "POST"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_server() -> FastMCP:
    """
    Create and configure the FastMCP server instance.

    Returns:
        FastMCP: The configured server instance.
    """
    # Server metadata
    server_metadata: dict[str, Any] = {
        "name": config.SERVER_NAME,
        "description": "MCP server for Paradex trading platform",
        "vendor": "Model Context Protocol",
        "version": __version__,
    }

    # Create server instance
    server = FastMCP(
        name=config.SERVER_NAME,
    )

    return server


# Singleton instance of the server
server = create_server()

from mcp_paradex.prompts import *
from mcp_paradex.resources import *
from mcp_paradex.tools import *


def run_cli() -> None:
    """
    Run the MCP Paradex server from the command line.
    This function is used as an entry point in pyproject.toml.
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="MCP Paradex Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport to use (stdio or streamable-http) [env: MCP_TRANSPORT]",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", str(config.SERVER_PORT))),
        help=f"Port for streamable-http transport (default: {config.SERVER_PORT}) [env: MCP_PORT]",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        default=os.environ.get("MCP_STATELESS", "").lower() in ("1", "true", "yes"),
        help="Enable stateless HTTP mode (required for Lambda / serverless deployments) [env: MCP_STATELESS]",
    )
    args = parser.parse_args()

    logger.info(f"Starting MCP Paradex server with {args.transport} transport...")

    try:
        if args.transport == "streamable-http":
            import uvicorn

            server.settings.port = args.port
            server.settings.stateless_http = args.stateless
            server.settings.host = "0.0.0.0"  # bind all interfaces for container deployments
            # Disable DNS rebinding protection: the Host header won't be localhost
            # when running behind Lambda Function URL / CloudFront. Security is
            # handled at the infrastructure layer (TLS, IAM, CloudFront).
            server.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
            starlette_app: ASGIApp = server.streamable_http_app()
            starlette_app = HealthMiddleware(starlette_app)
            if config.PARADEX_AUTH_SERVER_URL:
                # Advertise OAuth AS and extract Bearer tokens from requests.
                starlette_app = OAuthResourceMetadataMiddleware(starlette_app)
                starlette_app = BearerAuthMiddleware(starlette_app)
            if args.stateless:
                # Wrap with middleware that rejects GET requests.
                # In stateless mode GET /mcp would open a persistent SSE stream
                # that Lambda cannot hold — 405 makes clients fall back to POST-only.
                starlette_app = RejectGetMiddleware(
                    starlette_app, mcp_path=server.settings.streamable_http_path
                )
            # Outermost: extract MCP-Session-Id and log request/response timing.
            starlette_app = RequestTracingMiddleware(starlette_app)

            import anyio

            async def _serve() -> None:
                config = uvicorn.Config(
                    starlette_app,
                    host=server.settings.host,
                    port=server.settings.port,
                    log_level=server.settings.log_level.lower(),
                )
                await uvicorn.Server(config).serve()

            anyio.run(_serve)
        else:
            server.run(transport=args.transport)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception(f"Error running server: {e}")
        sys.exit(1)

    logger.info("Server stopped")
