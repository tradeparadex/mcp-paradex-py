"""
Pytest configuration for mcp-paradex tests.
"""

import os
import sys
import types

# Stub out ledgerblue (native C extension that is not buildable in all
# environments) before anything else imports paradex-py / ledgereth.
if "ledgerblue" not in sys.modules:
    _lb = types.ModuleType("ledgerblue")
    _comm = types.ModuleType("ledgerblue.comm")
    _comm.getDongle = lambda *_a, **_kw: None  # type: ignore[attr-defined]
    _exc = types.ModuleType("ledgerblue.commException")
    _exc.CommException = type("CommException", (Exception,), {})  # type: ignore[attr-defined]
    _dongle = types.ModuleType("ledgerblue.Dongle")
    _dongle.Dongle = type("Dongle", (), {})  # type: ignore[attr-defined]
    _lb.comm = _comm  # type: ignore[attr-defined]
    _lb.commException = _exc  # type: ignore[attr-defined]
    _lb.Dongle = _dongle  # type: ignore[attr-defined]
    sys.modules["ledgerblue"] = _lb
    sys.modules["ledgerblue.comm"] = _comm
    sys.modules["ledgerblue.commException"] = _exc
    sys.modules["ledgerblue.Dongle"] = _dongle

# Set a fake private key before any server module is imported so that
# config.is_configured() returns True and auth-required tools get registered
# on the FastMCP server.  Actual network calls are mocked in each test.
os.environ.setdefault("PARADEX_ACCOUNT_PRIVATE_KEY", "0xtest")
