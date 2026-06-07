"""SDK attestation client — surfaces the server passport/audit gate as typed errors."""
import json
from blindoracle_sdk.attestation import AttestationAPI
from blindoracle_sdk.exceptions import PassportRequiredError, CredentialNotFoundError


class _FakeClient:
    timeout = 5


def _api_with(monkeypatch, resp):
    api = AttestationAPI(_FakeClient())
    monkeypatch.setattr(api, "_rpc", lambda m, p=None: resp)
    return api


def test_passport_required(monkeypatch):
    api = _api_with(monkeypatch, {"result": {"isError": True, "content": [
        {"text": "Passport required: passport revoked for agent-x"}]}})
    try:
        api.request_credential("p1"); assert False
    except PassportRequiredError:
        pass


def test_not_found(monkeypatch):
    api = _api_with(monkeypatch, {"result": {"isError": True, "content": [
        {"text": "No credential found for proof_id p1. Required flow: ..."}]}})
    try:
        api.request_credential("p1"); assert False
    except CredentialNotFoundError:
        pass


def test_success_returns_vc(monkeypatch):
    vc = {"w3c_vc": {"type": ["VerifiableCredential"]}, "verify_url": "https://x"}
    api = _api_with(monkeypatch, {"result": {"isError": False, "content": [
        {"text": json.dumps(vc)}]}})
    out = api.request_credential("p1")
    assert out["verify_url"] == "https://x"
