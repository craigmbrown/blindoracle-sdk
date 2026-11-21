"""RQ-BO-X402-ORDER-NONCE-01: a challenge that offers a signed order gets a nonce that IS
the order's hash, and the order goes back in X-BO-Order. Unbound challenges are signed as
before. verify-order checks the binding from a tx receipt. Offline: no network, no funds."""
import base64
import json
import sys
from pathlib import Path

import pytest

SDK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_ROOT))
sys.path.insert(0, str(SDK_ROOT / "examples"))

from blindoracle_sdk import x402  # noqa: E402

pytest.importorskip("eth_account", reason="signing tests need the [x402] extra")
from eth_account import Account  # noqa: E402
from eth_utils import keccak  # noqa: E402

import verify_chain as vc  # noqa: E402

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TREASURY = "0x5E709929A4AB69eC3a8811d03417869059BC4EB9"
ORDER = {"v": 1, "order_id": "a1b2c3d4e5f6", "sku": "agent.trust-badge", "amount": "10000",
         "payTo": TREASURY, "network": "eip155:8453", "exp": 1900000000}
CAPS = dict(max_payment_usd=1.0, session_budget_usd=10.0)


def _challenge(bound=True):
    extra = {"name": "USD Coin", "version": "2"}
    if bound:
        extra.update({"boOrder": ORDER, "boOrderSig": "f" * 64})
    return x402.parse_challenge(body={"x402Version": 2, "accepts": [{
        "scheme": "exact", "network": "eip155:8453", "asset": USDC, "amount": "10000",
        "payTo": TREASURY, "maxTimeoutSeconds": 60, "extra": extra}],
        "resource": {"url": "https://api.craigmbrown.com/v1/services/agent.trust-badge"}})


@pytest.fixture
def key():
    return Account.create("order-bound-nonce-test").key.hex()


def _jcs(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()


def test_bound_challenge_signs_the_order_hash(key):
    _, payload = x402.build_payment_header(_challenge(), private_key=key, **CAPS)
    assert payload["payload"]["authorization"]["nonce"] == "0x" + keccak(_jcs(ORDER)).hex()


def test_order_header_round_trips_exactly():
    hdr = x402.order_header(_challenge())
    body, sig = hdr.split(".")
    assert sig == "f" * 64
    assert json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))) == ORDER


def test_unbound_challenge_keeps_a_random_nonce(key):
    c = _challenge(bound=False)
    n1 = x402.build_payment_header(c, private_key=key, **CAPS)[1]["payload"]["authorization"]["nonce"]
    n2 = x402.build_payment_header(c, private_key=key, **CAPS)[1]["payload"]["authorization"]["nonce"]
    assert n1 != n2 and len(n1) == 66 and x402.order_header(c) is None


def test_opt_out_env_restores_random_nonce(key, monkeypatch):
    monkeypatch.setenv("BLINDORACLE_ORDER_BIND", "0")
    _, payload = x402.build_payment_header(_challenge(), private_key=key, **CAPS)
    assert payload["payload"]["authorization"]["nonce"] != "0x" + keccak(_jcs(ORDER)).hex()
    assert x402.order_header(_challenge()) is None


def test_cap_still_checked_before_signing_a_bound_order(key):
    with pytest.raises(x402.PaymentCapExceeded):
        x402.build_payment_header(_challenge(), private_key=key,
                                  max_payment_usd=0.001, session_budget_usd=10.0)


# --- verify-order -----------------------------------------------------------------------

def _receipt(nonce, amount="10000", to=TREASURY, status="0x1"):
    pad = lambda a: "0x" + "0" * 24 + a.lower()[2:]  # noqa: E731
    payer = "0x" + "ab" * 20
    return {"status": status, "logs": [
        {"address": USDC.lower(), "topics": [vc.AUTH_USED_TOPIC, pad(payer), nonce]},
        {"address": USDC.lower(), "topics": [vc.TRANSFER_TOPIC, pad(payer), pad(to)],
         "data": hex(int(amount))}]}


def test_keccak_fallback_matches_eth_utils():
    for b in (b"", b"abc", b"x" * 300, _jcs(ORDER)):
        assert vc.keccak256(b) == keccak(b)


def test_verify_order_matches_a_bound_payment():
    res = vc.verify_order(_receipt(x402.order_nonce(ORDER)), ORDER)
    assert res["ok"] and res["nonce_matches_order"] and res["transfer_matches_order"]


def test_verify_order_rejects_a_random_nonce_and_a_doctored_order():
    assert not vc.verify_order(_receipt("0x" + "00" * 32), ORDER)["ok"]
    doctored = {**ORDER, "order_id": "ffffffffffff"}
    assert not vc.verify_order(_receipt(x402.order_nonce(ORDER)), doctored)["ok"]


def test_verify_order_rejects_wrong_amount_or_failed_tx():
    n = x402.order_nonce(ORDER)
    assert not vc.verify_order(_receipt(n, amount="9999"), ORDER)["ok"]
    assert not vc.verify_order(_receipt(n, status="0x0"), ORDER)["ok"]


def test_cli_reads_header_value_and_receipt_file(tmp_path, capsys):
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps(_receipt(x402.order_nonce(ORDER))))
    rc = vc.main(["verify-order", "0xabc", "--order", x402.order_header(_challenge()),
                  "--receipt", str(rf)])
    assert rc == 0 and json.loads(capsys.readouterr().out)["ok"] is True
