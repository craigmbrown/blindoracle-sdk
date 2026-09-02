"""v0.10 routes — offline: every call is captured, nothing hits the network."""
import json
import pytest

from blindoracle_sdk import BlindOracleClient, tool_name_for


class _Capture:
    def __init__(self):
        self.calls = []
        self.reply = {}

    def __call__(self, method, path, params=None, body=None, extra_headers=None, base=None):
        self.calls.append({"method": method, "path": path, "params": params, "body": body,
                           "headers": extra_headers or {}, "base": base})
        return self.reply


@pytest.fixture
def bo():
    c = BlindOracleClient(api_key="bo_test_key")
    c.agent_id = "grok-scout-01"
    cap = _Capture()
    c._request = cap  # type: ignore[assignment]
    return c, cap


def test_tool_name_mapping():
    assert tool_name_for("agent.trust-badge") == "agent_trust-badge"
    assert tool_name_for("reputation.lookup") == "reputation_lookup"


def test_claim_starter_credit_uses_agent_id_and_bearer(bo):
    c, cap = bo
    cap.reply = {"ok": True, "starter_credit_note": "AgEE...", "sats": 100}
    r = c.agents.claim_starter_credit()
    assert r["sats"] == 100
    assert cap.calls[-1]["path"] == "/a2a/agents/grok-scout-01/starter-credit"
    assert cap.calls[-1]["method"] == "POST"


def test_set_wallet_and_passport(bo):
    c, cap = bo
    c.agents.set_wallet("0x" + "a" * 40)
    assert cap.calls[-1]["path"] == "/a2a/agents/grok-scout-01/wallet"
    assert cap.calls[-1]["body"] == {"evm_address": "0x" + "a" * 40}
    c.agents.passport("TheBaby")
    assert cap.calls[-1]["path"] == "/a2a/passport/TheBaby"


def test_get_request_and_input_schema(bo):
    c, cap = bo
    cap.reply = {"request_id": "r1", "bids": [], "jobs": [{"job_id": "j1"}]}
    assert c.marketplace.get_request("r1")["jobs"][0]["job_id"] == "j1"
    cap.reply = {"services": [{"sku_id": "oracle.alert-generator", "input_schema": {"type": "object"}}]}
    assert c.marketplace.input_schema("oracle.alert-generator") == {"type": "object"}
    assert c.marketplace.input_schema("nope") is None


def test_mcp_call_puts_note_in_meta_never_in_arguments(bo):
    c, cap = bo
    cap.reply = {"jsonrpc": "2.0", "id": 1, "result": {"isError": False, "content": [{"type": "text", "text": "ok"}],
                                                       "structuredContent": {"job_id": "j9", "status": "complete"}}}
    r = c.mcp.call("agent.trust-badge", {}, x402_payment="NOTE123")
    sent = cap.calls[-1]
    assert sent["path"] == "/v1/mcp" and sent["method"] == "POST"
    assert sent["body"]["params"]["name"] == "agent_trust-badge"
    assert sent["body"]["params"]["_meta"] == {"bo/x402-payment": "NOTE123"}
    assert "_meta" not in sent["body"]["params"]["arguments"]
    assert sent["headers"].get("X-402-Payment") == ""  # note must not also ride the header
    assert r["isError"] is False and r["structured"]["job_id"] == "j9" and r["text"] == "ok"


def test_mcp_call_usdc_payload_wins(bo):
    c, cap = bo
    cap.reply = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "{}"}]}}
    c.mcp.call("reputation.lookup", {}, x402_payment="NOTE", usdc_payment={"x402Version": 2})
    assert cap.calls[-1]["body"]["params"]["_meta"] == {"x402/payment": {"x402Version": 2}}


def test_proofs(bo):
    c, cap = bo
    cap.reply = {"count": 1, "proofs": [{"proof_id": "so-1", "settlement_ref": "0xabc"}]}
    assert c.proofs.settlements(3)[0]["settlement_ref"] == "0xabc"
    assert cap.calls[-1]["params"] == {"limit": 3}
    cap.reply = {"count": 1, "proofs": [{"proof_id": "so-1", "settlement_ref": "0xabc"}]}   # live shape
    assert c.proofs.settlement("0xabc")["proof_id"] == "so-1"
    cap.reply = {"count": 0, "proofs": []}
    assert c.proofs.settlement("0xnope") is None
    assert c.proofs.settlement("") is None
    assert len(c.proofs.verify_recipe()) == 3


def test_version_is_0_10():
    """pyproject and the source-tree fallback agree on 0.10 (the installed
    metadata may lag on a dev box; test_version_consistency covers that link)."""
    import re
    from pathlib import Path
    from blindoracle_sdk import _version
    root = Path(__file__).resolve().parent.parent
    py = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M).group(1)
    assert py == _version._FALLBACK and py.startswith("0.10")
