# Contributing to MCP Paradex Server

Thank you for your interest in contributing to the MCP Paradex Server project!

## Development

### Project Structure

- `src/mcp_paradex/` - Main package
  - `server/` - MCP server implementation
    - `server.py` - FastMCP server configuration
  - `resources/` - Read-only data resources
    - `system.py` - System status resource
    - `market.py` - Market data resources
    - `vaults.py` - Vault management resources
  - `tools/` - Action tools for operations
    - `system.py` - System management tools
    - `market.py` - Market data tools
    - `account.py` - Account management tools
    - `orders.py` - Order management tools
    - `vaults.py` - Vault management tools
  - `utils/` - Utility functions and helpers
    - `config.py` - Configuration handling
    - `paradex_client.py` - Paradex API client

### Development Progress

- [x] **Step 1:** Create Basic Project Structure

  - Set up package configuration and dependencies
  - Create initial FastMCP server configuration
  - Implement basic system health checks

- [x] **Step 2:** Implement Authentication Layer

  - Design secure API key management system
  - Create authentication flow for Paradex API

- [x] **Step 3:** Deploy Basic Server with Health Check

  - Implement system status resource
  - Create connectivity verification tool
  - Add public API endpoints that don't require authentication

- [x] **Step 4:** Market Data Integration

  - Implement market data resources
  - Create market data tools
  - Add orderbook and trade history functionality

- [x] **Step 5:** Account and Order Management

  - Implement account information resources
  - Create order management tools
  - Add vault management capabilities

- [x] **Step 6:** Add Smithery.ai Support
  - Create Smithery.ai configuration file
  - Add Claude Desktop configuration example
  - Document Smithery.ai integration

### Code Quality Tools

This project uses several tools to maintain code quality:

- **Black**: Code formatter that enforces a consistent style
- **Ruff**: Fast Python linter that combines functionality from multiple linting tools
- **Mypy**: Static type checker for Python
- **Pre-commit**: Git hook scripts to automate checks before commits

### Setup Development Environment

1. Install development dependencies:

   ```bash
   make install-dev
   ```

2. Format code:

   ```bash
   make format
   ```

3. Lint code:

   ```bash
   make lint
   ```

4. Type check:

   ```bash
   make typecheck
   ```

5. Run all checks:

   ```bash
   make check
   ```

6. Run pre-commit on all files:

   ```bash
   make pre-commit
   ```

7. Run tests:

   ```bash
   make test
   ```

8. Run tests with coverage report:
   ```bash
   make test-cov
   ```

### Testing

This project uses pytest for testing. Tests are located in the `tests` directory.

#### Running Tests

```bash
# Run all tests
make test
# OR
pytest

# Run tests with coverage report
make test-cov
# OR
pytest --cov=mcp_paradex --cov-report=html
```

This will generate an HTML coverage report in the `htmlcov` directory.

#### Local Testing and Development

##### 1. Testing the MCP Server Locally

To test the MCP server during development:

```bash
# Run the server in development mode
uv run mcp-paradex

# Test with specific environment variables
PARADEX_ENVIRONMENT=testnet uv run mcp-paradex

# Test with Docker
docker build . -t mcp-paradex-local
docker run --rm -i mcp-paradex-local
```

##### 2. Using MCP Inspector

The MCP Inspector is a debugging tool for testing MCP servers:

```bash
# Install MCP Inspector
npm install -g @anthropic/mcp-inspector

# Run inspector with your local server
mcp-inspector uv run mcp-paradex

# Or test with environment variables
mcp-inspector --env PARADEX_ENVIRONMENT=testnet uv run mcp-paradex
```

The inspector will open a web interface where you can:
- View available resources and tools
- Test tool calls interactively
- Debug server responses
- Check for errors or warnings

##### 3. Testing with Claude Desktop

For testing with Claude Desktop during development:

1. Update your `claude_desktop_config.json` to use the local development server:

```json
{
  "mcpServers": {
    "paradex-dev": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-paradex-py", "mcp-paradex"],
      "env": {
        "PARADEX_ENVIRONMENT": "testnet",
        "PARADEX_ACCOUNT_PRIVATE_KEY": "your_test_private_key"
      }
    }
  }
}
```

2. Restart Claude Desktop to load the new configuration

##### 4. Manual Testing Commands

```bash
# Test system endpoints (no auth required)
curl -X POST http://localhost:8000/system/config

# Test with authentication (requires proper setup)
PARADEX_ACCOUNT_PRIVATE_KEY=your_key uv run mcp-paradex

# Test specific tools
python -c "from mcp_paradex.tools.system import paradex_system_config; print(paradex_system_config())"
```

##### 5. Environment Setup for Testing

Create a `.env.test` file for testing:

```bash
# Copy template
cp .env.template .env.test

# Edit with test credentials
PARADEX_ENVIRONMENT=testnet
PARADEX_ACCOUNT_PRIVATE_KEY=your_test_private_key

# Use in tests
source .env.test
uv run mcp-paradex
```

##### 6. Debugging Tips

- Use `--verbose` flag for detailed logging
- Check server logs for authentication issues
- Test with testnet first before mainnet
- Use MCP Inspector's network tab to debug API calls
- Verify environment variables are loaded correctly

##### 7. Integration Testing

Test the full integration flow:

```bash
# 1. Start the server
uv run mcp-paradex &
SERVER_PID=$!

# 2. Test with a simple client
python -c "
from mcp import Client
import asyncio

async def test():
    # Test basic connectivity
    pass

asyncio.run(test())
"

# 3. Cleanup
kill $SERVER_PID
```

### Pre-commit Hooks

Pre-commit hooks are configured to run automatically on git commit. They include:

- Trailing whitespace removal
- End-of-file fixer
- YAML/TOML syntax checking
- Black formatting
- Ruff linting
- Mypy type checking

To manually run all pre-commit hooks on all files:

```bash
pre-commit run --all-files
```

Generate models.py

Convert paradex swagger to openapi using https://converter.swagger.io/#/Converter/convertByUrl

```
https://api.prod.paradex.trade/swagger/doc.json
```

```bash
pip install datamodel-code-generator
datamodel-codegen  --input prompts/paradex-openapi.json --use-annotated --use-default-kwarg --keep-model-order --output src/mcp_paradex/models/
```

## MCPB Bundle Maintenance

The project ships an `.mcpb` bundle (MCP Bundle) for one-click installation in Claude Desktop and other compatible apps. The bundle is defined by two files at the repository root:

- **`manifest.json`** — MCPB manifest (v0.4, `uv` server type). Declares metadata, tools, user config fields, and compatibility.
- **`.mcpbignore`** — Controls which files are excluded from the bundle (similar to `.gitignore`).

### When to Update `manifest.json`

- **Adding or removing a tool** — update the `tools` array to match. Each entry needs `name` and `description`.
- **Bumping the version** — keep `version` in sync with `src/mcp_paradex/__init__.py`.
- **Changing environment variables** — update `server.mcp_config.env` and `user_config` if new user-facing env vars are added or existing ones renamed. Note: `PARADEX_ENVIRONMENT` is hardcoded to `prod` and not exposed to users.
- **Changing entry point or dependencies** — update `server.entry_point` and `server.mcp_config.args` if the startup command changes.

### Validating and Building the Bundle

```bash
# Install the MCPB CLI (one-time)
npm install -g @anthropic-ai/mcpb

# Validate the manifest
mcpb validate manifest.json

# Build the bundle
mcpb pack .
# Output: mcp-paradex-<version>.mcpb

# Inspect bundle contents
mcpb info mcp-paradex-<version>.mcpb
```

### Testing the Bundle

1. **Manifest validation** — `mcpb validate manifest.json` must pass with no errors.
2. **Stdio transport** — `uv run python src/mcp_paradex/__main__.py` should start the server in stdio mode (it will block waiting for JSON-RPC input; Ctrl+C to exit).
3. **Install in Claude Desktop** — double-click the `.mcpb` file. Verify the install dialog shows correct metadata, config fields, and tool count.
4. **Smoke test** — after installation, ask Claude "What markets are available on Paradex?" and verify tools respond.

### Release Checklist

The `.mcpb` bundle is built and attached to GitHub releases automatically by the `publish.yml` workflow. When cutting a new release:

1. Bump version in `src/mcp_paradex/__init__.py`
2. Update `version` in `manifest.json` to match
3. Run `mcpb validate manifest.json` locally to catch errors early
4. Create the GitHub release — the CI workflow will build and attach the `.mcpb` file automatically

To build locally for testing:

```bash
mcpb pack .
# Output: mcp-paradex-<version>.mcpb
```

---

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please make sure your code follows the existing style and passes all tests and linters before submitting a PR.

## Evals and Testing Framework

### MCP Testing Framework

[MCP Testing Framework](https://github.com/L-Qun/mcp-testing-framework) - A comprehensive testing framework for MCP servers.

### Testing Checklist

Before submitting a PR, ensure:

- [ ] All tests pass: `make test`
- [ ] Code coverage is maintained: `make test-cov`
- [ ] Linting passes: `make lint`
- [ ] Type checking passes: `make typecheck`
- [ ] Pre-commit hooks pass: `make pre-commit`
- [ ] MCP Inspector shows no errors
- [ ] Manual testing with Claude Desktop works
- [ ] Both testnet and mainnet configurations tested (if applicable)

### Common Testing Issues

1. **Authentication Errors**: Ensure `PARADEX_ACCOUNT_PRIVATE_KEY` is set correctly
2. **Network Issues**: Check if testnet/mainnet endpoints are accessible
3. **MCP Protocol Errors**: Use MCP Inspector to debug protocol-level issues
4. **Environment Variables**: Verify all required env vars are loaded
5. **Dependencies**: Run `uv sync --dev --all-extras` to update dependencies
