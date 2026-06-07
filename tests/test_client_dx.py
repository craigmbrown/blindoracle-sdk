"""Developer-experience surface (v0.4.0): env-var fallback + one-line register()."""

import io
import json
import urllib.error
import pytest

from blindoracle_sdk import BlindOracleClient
from blindoracle_sdk.exceptions import BlindOracleError

# --- env-var fallback -------------------------------------------------------


def test_env_api_key_fallback(monkeypatch):
    monkeypatch.setenv("BLINDORACLE_API_KEY", "env_key_123")
    assert BlindOracleClient().api_key == "env_key_123"


def test_env_ecash_fallback(monkeypatch):
    monkeypatch.setenv("BLINDORACLE_ECASH_TOKEN", "ecash_xyz")
    assert BlindOracleClient().ecash_token == "ecash_xyz"


def test_explicit_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv("BLINDORACLE_API_KEY", "env_key_123")
    assert BlindOracleClient(api_key="explicit").api_key == "explicit"


def test_no_env_no_arg_is_none(monkeypatch):
    monkeypatch.delenv("BLINDORACLE_API_KEY", raising=False)
    assert BlindOracleClient().api_key is None


# --- one-line register() ----------------------------------------------------


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _fake_urlopen(payload):
    def _open(req, timeout=30):
        return _Resp(json.dumps(payload).encode("utf-8"))

    return _open


def test_register_returns_authed_client(monkeypatch):
    payload = {
        "agent_id": "agent_abc",
        "api_key": "k_live",
        "tier": "observer",
        "erc8004_identity": {"id": "did:..."},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(payload))
    bo = BlindOracleClient.register("my-agent", ["verified-introduction"])
    assert bo.api_key == "k_live"
    assert bo.agent_id == "agent_abc"
    assert bo.registration["tier"] == "observer"
    assert isinstance(bo, BlindOracleClient)


def test_register_raises_on_error_payload(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen({"error": "name already taken"}))
    with pytest.raises(BlindOracleError):
        BlindOracleClient.register("dup", ["x"])


def test_register_raises_on_http_error(monkeypatch):
    def _raise(req, timeout=30):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"bad"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    with pytest.raises(BlindOracleError):
        BlindOracleClient.register("x", ["y"])
