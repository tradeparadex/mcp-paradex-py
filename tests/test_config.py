"""
Unit tests for config.py JWT decode helpers and account address auto-population.
"""

import base64
import json
import sys
from unittest.mock import patch


def _make_jwt(payload: dict) -> str:
    """Build a minimal JWT string with a real base64url-encoded payload."""

    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = _b64(json.dumps({"alg": "HS256"}).encode())
    body = _b64(json.dumps(payload).encode())
    return f"{header}.{body}.fakesig"


def _reload_config(env: dict):
    """Re-import config under a controlled environment so module-level side effects re-run."""
    for mod in list(sys.modules):
        if "mcp_paradex" in mod:
            del sys.modules[mod]
    with patch.dict("os.environ", env, clear=False):
        import mcp_paradex.utils.config as cfg

        return cfg


class TestDecodeJwtPayload:
    def test_returns_dict_from_valid_jwt(self):
        from mcp_paradex.utils.config import _decode_jwt_payload

        token = _make_jwt({"sub": "0xabc", "exp": 9999999999})
        assert _decode_jwt_payload(token)["sub"] == "0xabc"

    def test_handles_all_padding_variants(self):
        from mcp_paradex.utils.config import _decode_jwt_payload

        # payload byte lengths that produce 0-3 missing base64 padding chars
        for extra in range(4):
            payload = {"k": "x" * extra}
            token = _make_jwt(payload)
            assert _decode_jwt_payload(token)["k"] == "x" * extra


class TestExtractAccountFromJwt:
    def test_prefers_account_claim(self):
        from mcp_paradex.utils.config import _extract_account_from_jwt

        token = _make_jwt({"account": "0xacc", "account_address": "0xaddr", "sub": "0xsub"})
        assert _extract_account_from_jwt(token) == "0xacc"

    def test_falls_back_to_account_address(self):
        from mcp_paradex.utils.config import _extract_account_from_jwt

        token = _make_jwt({"account_address": "0xaddr", "sub": "0xsub"})
        assert _extract_account_from_jwt(token) == "0xaddr"

    def test_falls_back_to_sub(self):
        from mcp_paradex.utils.config import _extract_account_from_jwt

        token = _make_jwt({"sub": "0xsub"})
        assert _extract_account_from_jwt(token) == "0xsub"

    def test_returns_none_when_no_known_claim(self):
        from mcp_paradex.utils.config import _extract_account_from_jwt

        token = _make_jwt({"exp": 9999999999})
        assert _extract_account_from_jwt(token) is None

    def test_returns_none_for_malformed_token(self):
        from mcp_paradex.utils.config import _extract_account_from_jwt

        assert _extract_account_from_jwt("not-a-jwt") is None
        assert _extract_account_from_jwt("only.two") is None


class TestConfigAutoPopulatesAddress:
    def test_address_extracted_from_api_key(self):
        token = _make_jwt({"account": "0xdeadbeef"})
        cfg = _reload_config({"PARADEX_API_KEY": token, "PARADEX_ACCOUNT_ADDRESS": ""})
        assert cfg.config.PARADEX_ACCOUNT_ADDRESS == "0xdeadbeef"

    def test_api_key_mapped_to_jwt_token(self):
        token = _make_jwt({"account": "0xabc"})
        cfg = _reload_config({"PARADEX_API_KEY": token, "PARADEX_JWT_TOKEN": ""})
        # PARADEX_API_KEY is aliased to PARADEX_JWT_TOKEN so no code path changes are needed.
        assert token == cfg.config.PARADEX_JWT_TOKEN

    def test_existing_jwt_token_not_overwritten(self):
        api_token = _make_jwt({"account": "0xfromapi"})
        jwt_token = _make_jwt({"account": "0xfromjwt"})
        cfg = _reload_config({"PARADEX_API_KEY": api_token, "PARADEX_JWT_TOKEN": jwt_token})
        assert jwt_token == cfg.config.PARADEX_JWT_TOKEN

    def test_explicit_address_not_overwritten(self):
        token = _make_jwt({"account": "0xfromjwt"})
        cfg = _reload_config({"PARADEX_API_KEY": token, "PARADEX_ACCOUNT_ADDRESS": "0xexplicit"})
        assert cfg.config.PARADEX_ACCOUNT_ADDRESS == "0xexplicit"

    def test_no_op_when_no_api_key(self):
        cfg = _reload_config({"PARADEX_API_KEY": "", "PARADEX_ACCOUNT_ADDRESS": ""})
        assert cfg.config.PARADEX_ACCOUNT_ADDRESS is None

    def test_api_key_registered_in_is_configured(self):
        token = _make_jwt({"account": "0xabc"})
        cfg = _reload_config(
            {
                "PARADEX_API_KEY": token,
                "PARADEX_ACCOUNT_PRIVATE_KEY": "",
                "PARADEX_JWT_TOKEN": "",
                "PARADEX_AUTH_SERVER_URL": "",
            }
        )
        assert cfg.Config.is_configured() is True
