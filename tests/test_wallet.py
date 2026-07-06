"""Tests for bo.wallet.balance() — free starter-credit preflight (v0.8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blindoracle_sdk.client import BlindOracleClient  # noqa: E402


def _client_with_stub(captured, response):
    bo = BlindOracleClient(api_key="test-key", ecash_token="")
    def fake_request(method, path, params=None, body=None, extra_headers=None, base=None):
        captured.update({"method": method, "path": path,
                         "extra_headers": extra_headers or {}, "base": base})
        return response
    bo._request = fake_request
    return bo


def test_balance_no_token_short_circuits():
    bo = BlindOracleClient(api_key="k")
    out = bo.wallet.balance()
    assert out["status"] == "unknown"
    assert "no token" in out["detail"]


def test_balance_uses_client_ecash_token():
    cap = {}
    bo = _client_with_stub(cap, {"status": "live", "agent": "a", "remaining_usd": 1.0})
    bo.ecash_token = "N" * 120
    out = bo.wallet.balance()
    assert out["status"] == "live"
    assert cap["method"] == "GET"
    assert cap["path"] == "/v1/wallet/balance"
    assert cap["extra_headers"]["X-402-Payment"] == "N" * 120
    assert cap["base"] == bo.gateway_base_url


def test_balance_explicit_token_overrides():
    cap = {}
    bo = _client_with_stub(cap, {"status": "revoked", "remaining_usd": 0.0})
    bo.ecash_token = "CLIENT" * 20
    out = bo.wallet.balance(token="OVERRIDE" * 15)
    assert out["status"] == "revoked"
    assert cap["extra_headers"]["X-402-Payment"] == "OVERRIDE" * 15


def test_wallet_namespace_wired():
    bo = BlindOracleClient(api_key="k")
    assert hasattr(bo, "wallet") and callable(bo.wallet.balance)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
