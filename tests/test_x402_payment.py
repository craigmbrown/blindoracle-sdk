#!/usr/bin/env python3
"""x402 v2 / EIP-3009 payment path.

@REQ-ID: RQ-BO-SDK-X402-PAY-01

Closes finding F4: before this, the published SDK could not pay for any of
BlindOracle's 39 live SKUs. These tests run entirely offline — the challenge
fixture below is a byte-copy of the real 402 response from
``POST /v1/services/agent.trust-badge`` on 2026-08-16.

The tests that matter most are the *refusals*: a payment client that pays when
it should not is far worse than one that fails loudly.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

SDK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_ROOT))

from blindoracle_sdk import x402  # noqa: E402
from blindoracle_sdk.x402 import (  # noqa: E402
    PaymentCapExceeded,
    PaymentChallenge,
    SigningUnavailable,
    UnsupportedPaymentError,
    build_payment_header,
    parse_challenge,
)

eth_account = pytest.importorskip("eth_account",
                                  reason="signing tests need the [x402] extra")
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_typed_data  # noqa: E402

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TREASURY = "0x5E709929A4AB69eC3a8811d03417869059BC4EB9"

# Verbatim shape of the live challenge (2026-08-16, agent.trust-badge, $0.01).
LIVE = {
    "x402Version": 2,
    "error": "payment_required",
    "accepts": [{
        "scheme": "exact",
        "network": "eip155:8453",
        "asset": USDC_BASE,
        "amount": "10000",
        "payTo": TREASURY,
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USD Coin", "version": "2"},
    }],
    "resource": {"url": "https://api.craigmbrown.com/v1/services/agent.trust-badge"},
}

CAPS = dict(max_payment_usd=1.00, session_budget_usd=10.00)


@pytest.fixture
def acct():
    return Account.create("deterministic-enough-for-a-unit-test")


def _chal(**over):
    doc = json.loads(json.dumps(LIVE))
    doc["accepts"][0].update(over)
    return doc


# --- parsing the real challenge ---------------------------------------------

def test_parses_the_live_challenge():
    c = parse_challenge(body=LIVE)
    assert c.scheme == "exact"
    assert c.network == "eip155:8453"
    assert c.chain_id == 8453
    assert c.amount_atomic == 10000
    assert c.amount_usd == pytest.approx(0.01)
    assert c.decimals == 6
    assert c.pay_to == TREASURY
    assert c.domain_name == "USD Coin" and c.domain_version == "2"


def test_parses_base64_header_form():
    blob = base64.b64encode(json.dumps(LIVE).encode()).decode()
    c = parse_challenge(headers={"payment-required": blob})
    assert c.amount_atomic == 10000


def test_header_wins_over_body_but_body_suffices():
    assert parse_challenge(body=json.dumps(LIVE)).amount_atomic == 10000


# --- refusals: unknown means refuse, never assume ---------------------------

@pytest.mark.parametrize("field,value,needle", [
    ("scheme", "upto", "scheme"),
    ("network", "solana:mainnet", "network"),
    ("network", "eip155:notanumber", "chain id"),
    ("asset", "not-an-address", "asset"),
    ("payTo", "nope", "payTo"),
])
def test_unsupported_field_names_the_value(field, value, needle):
    with pytest.raises(UnsupportedPaymentError) as e:
        parse_challenge(body=_chal(**{field: value}))
    assert needle.lower() in str(e.value).lower()


def test_unknown_asset_refuses_rather_than_guessing_decimals():
    """Assuming 18 vs 6 decimals mis-scales a real payment by 10^12."""
    doc = _chal(asset="0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    with pytest.raises(UnsupportedPaymentError) as e:
        parse_challenge(body=doc)
    assert "decimals" in str(e.value) and "will not guess" in str(e.value)


def test_missing_eip712_domain_refuses():
    doc = _chal(extra={})
    with pytest.raises(UnsupportedPaymentError) as e:
        parse_challenge(body=doc)
    assert "extra.name" in str(e.value)


def test_unsupported_x402_version_refuses():
    doc = json.loads(json.dumps(LIVE))
    doc["x402Version"] = 99
    with pytest.raises(UnsupportedPaymentError) as e:
        parse_challenge(body=doc)
    assert "99" in str(e.value)


def test_empty_accepts_refuses():
    doc = json.loads(json.dumps(LIVE))
    doc["accepts"] = []
    with pytest.raises(UnsupportedPaymentError):
        parse_challenge(body=doc)


def test_multiple_accepts_picks_the_satisfiable_one():
    doc = json.loads(json.dumps(LIVE))
    doc["accepts"] = [
        {"scheme": "exact", "network": "solana:mainnet", "asset": "x",
         "amount": "1", "payTo": "y"},
        doc["accepts"][0],
    ]
    assert parse_challenge(body=doc).network == "eip155:8453"


def test_garbage_challenge_refuses():
    with pytest.raises(UnsupportedPaymentError):
        parse_challenge(body="}{not json")
    with pytest.raises(UnsupportedPaymentError):
        parse_challenge(body=None, headers=None)


# --- caps are enforced BEFORE a signature exists ----------------------------

def test_per_call_cap_blocks_and_signs_nothing(acct):
    c = parse_challenge(body=LIVE)
    with pytest.raises(PaymentCapExceeded) as e:
        build_payment_header(c, private_key=acct.key.hex(),
                             max_payment_usd=0.001, session_budget_usd=10.0)
    assert "nothing was signed" in str(e.value)


def test_session_budget_cap_blocks(acct):
    c = parse_challenge(body=LIVE)
    with pytest.raises(PaymentCapExceeded):
        build_payment_header(c, private_key=acct.key.hex(),
                             max_payment_usd=1.0, session_budget_usd=0.05,
                             session_spent_usd=0.045)


@pytest.mark.parametrize("caps", [
    dict(max_payment_usd=None, session_budget_usd=10.0),
    dict(max_payment_usd=1.0, session_budget_usd=None),
])
def test_caps_are_required_no_unlimited_default(acct, caps):
    c = parse_challenge(body=LIVE)
    with pytest.raises(PaymentCapExceeded) as e:
        build_payment_header(c, private_key=acct.key.hex(), **caps)
    assert "required" in str(e.value)


def test_cap_check_precedes_key_loading():
    """A cap breach must raise even with NO key available at all."""
    c = parse_challenge(body=LIVE)
    with pytest.raises(PaymentCapExceeded):
        build_payment_header(c, private_key=None,
                             max_payment_usd=0.0001, session_budget_usd=10.0)


def test_no_key_raises_signing_unavailable(monkeypatch):
    monkeypatch.delenv("BLINDORACLE_WALLET_KEY", raising=False)
    c = parse_challenge(body=LIVE)
    with pytest.raises(SigningUnavailable) as e:
        build_payment_header(c, private_key=None, **CAPS)
    assert "BLINDORACLE_WALLET_KEY" in str(e.value)


# --- the signature itself ----------------------------------------------------

def test_signature_recovers_to_the_configured_wallet(acct):
    c = parse_challenge(body=LIVE)
    _, payload = build_payment_header(c, private_key=acct.key.hex(),
                                      now=1_760_000_000, **CAPS)
    auth = payload["payload"]["authorization"]
    signable = encode_typed_data(
        domain_data={"name": "USD Coin", "version": "2",
                     "chainId": 8453, "verifyingContract": USDC_BASE},
        message_types={"TransferWithAuthorization":
                       x402._EIP3009_TYPES["TransferWithAuthorization"]},
        message_data={"from": auth["from"], "to": auth["to"],
                      "value": int(auth["value"]),
                      "validAfter": int(auth["validAfter"]),
                      "validBefore": int(auth["validBefore"]),
                      "nonce": bytes.fromhex(auth["nonce"][2:])},
    )
    assert Account.recover_message(
        signable, signature=payload["payload"]["signature"]) == acct.address


def test_every_signed_field_comes_from_the_challenge(acct):
    """No field may be defaulted or invented — a wrong payTo pays a stranger."""
    c = parse_challenge(body=LIVE)
    _, payload = build_payment_header(c, private_key=acct.key.hex(),
                                      now=1_760_000_000, **CAPS)
    auth = payload["payload"]["authorization"]
    assert auth["to"] == TREASURY                    # from challenge.payTo
    assert auth["value"] == "10000"                  # from challenge.amount
    assert auth["from"] == acct.address              # from our key
    assert payload["x402Version"] == 2
    assert payload["accepted"]["network"] == "eip155:8453"
    assert payload["accepted"]["scheme"] == "exact"
    assert payload["accepted"]["asset"] == USDC_BASE
    assert payload["accepted"]["amount"] == "10000"


def test_payload_uses_the_canonical_v2_shape_not_v1(acct):
    """v1 put `scheme`/`network` at the top level. The CDP facilitator rejects
    that shape with "'paymentPayload' is invalid: must match one of
    [x402V2Payment…" — a real 402 we hit on the first live attempt."""
    c = parse_challenge(body=LIVE)
    _, payload = build_payment_header(c, private_key=acct.key.hex(), **CAPS)
    assert "accepted" in payload, "v2 requires an `accepted` echo of the requirements"
    assert "scheme" not in payload, "top-level `scheme` is the v1 shape"
    assert "network" not in payload, "top-level `network` is the v1 shape"
    assert payload["resource"]["url"].endswith("agent.trust-badge")


def test_accepted_echoes_the_servers_own_entry(acct):
    """The facilitator checks the echo against what it issued, so it must be the
    server's values verbatim — not a reconstruction."""
    c = parse_challenge(body=LIVE)
    _, payload = build_payment_header(c, private_key=acct.key.hex(), **CAPS)
    for k in ("scheme", "network", "asset", "amount", "payTo",
              "maxTimeoutSeconds", "extra"):
        assert payload["accepted"][k] == LIVE["accepts"][0][k]


def test_validity_window_has_a_floor_for_the_facilitator(acct):
    """`exact` is gasless: the FACILITATOR submits, so a 60s window (what the
    live challenge advertises) expires under it and fails opaquely."""
    c = parse_challenge(body=LIVE)
    assert c.max_timeout_seconds == 60
    _, payload = build_payment_header(c, private_key=acct.key.hex(),
                                      now=1_000_000, **CAPS)
    window = int(payload["payload"]["authorization"]["validBefore"]) - 1_000_000
    assert window >= 300, f"validity window {window}s is too short to settle"


def test_validity_window_derives_from_max_timeout(acct):
    c = parse_challenge(body=LIVE)
    _, payload = build_payment_header(c, private_key=acct.key.hex(),
                                      now=1_000_000, **CAPS)
    auth = payload["payload"]["authorization"]
    assert int(auth["validAfter"]) == 0
    assert int(auth["validBefore"]) > 1_000_000


def test_nonce_is_unique_per_authorization(acct):
    c = parse_challenge(body=LIVE)
    seen = {build_payment_header(c, private_key=acct.key.hex(),
                                 **CAPS)[1]["payload"]["authorization"]["nonce"]
            for _ in range(8)}
    assert len(seen) == 8


def test_header_is_base64_of_the_payload(acct):
    c = parse_challenge(body=LIVE)
    header, payload = build_payment_header(c, private_key=acct.key.hex(), **CAPS)
    assert json.loads(base64.b64decode(header)) == payload


# --- the key must never leak -------------------------------------------------

def test_key_never_appears_in_payload_or_header(acct):
    c = parse_challenge(body=LIVE)
    key_hex = acct.key.hex()
    header, payload = build_payment_header(c, private_key=key_hex, **CAPS)
    blob = json.dumps(payload) + header + base64.b64decode(header).decode()
    stripped = key_hex[2:] if key_hex.startswith("0x") else key_hex
    assert key_hex not in blob and stripped not in blob


def test_bad_key_error_does_not_echo_the_key():
    c = parse_challenge(body=LIVE)
    secret = "0x" + "de" * 20  # wrong length -> load failure
    with pytest.raises(SigningUnavailable) as e:
        build_payment_header(c, private_key=secret, **CAPS)
    assert secret not in str(e.value) and "de" * 20 not in str(e.value)


# --- client wiring -----------------------------------------------------------

def test_client_exposes_caps_and_key(monkeypatch):
    from blindoracle_sdk.client import BlindOracleClient
    monkeypatch.delenv("BLINDORACLE_WALLET_KEY", raising=False)
    c = BlindOracleClient(wallet_key="0xabc", max_payment_usd=0.5,
                          session_budget_usd=5.0)
    assert c.wallet_key == "0xabc"
    assert c.max_payment_usd == 0.5 and c.session_budget_usd == 5.0
    assert c.session_spent_usd == 0.0 and c.payments == []


def test_caps_read_from_env(monkeypatch):
    from blindoracle_sdk.client import BlindOracleClient
    monkeypatch.setenv("BLINDORACLE_MAX_PAYMENT_USD", "0.25")
    monkeypatch.setenv("BLINDORACLE_SESSION_BUDGET_USD", "2.5")
    c = BlindOracleClient()
    assert c.max_payment_usd == 0.25 and c.session_budget_usd == 2.5


def test_malformed_env_cap_is_ignored_not_zero(monkeypatch):
    """A typo'd cap must not silently become 0 (blocks everything) or unlimited."""
    from blindoracle_sdk.client import BlindOracleClient
    monkeypatch.setenv("BLINDORACLE_MAX_PAYMENT_USD", "not-a-number")
    assert BlindOracleClient().max_payment_usd is None


def test_payment_help_names_the_actual_blocker(monkeypatch):
    from blindoracle_sdk.client import BlindOracleClient
    monkeypatch.delenv("BLINDORACLE_WALLET_KEY", raising=False)
    monkeypatch.delenv("BLINDORACLE_MAX_PAYMENT_USD", raising=False)
    monkeypatch.delenv("BLINDORACLE_SESSION_BUDGET_USD", raising=False)

    assert "no wallet key" in BlindOracleClient()._payment_help("x")
    capless = BlindOracleClient(wallet_key="0xabc")
    assert "spend caps are not" in capless._payment_help("x")
    full = BlindOracleClient(wallet_key="0xabc", max_payment_usd=1,
                             session_budget_usd=1)
    assert "did not accept" in full._payment_help("x")


def test_no_stale_ecash_only_message():
    """The old blanket message was a dead end for a funded-wallet caller (F4)."""
    src = (SDK_ROOT / "blindoracle_sdk" / "client.py").read_text()
    assert "Top up ecash at craigmbrown.com/blindoracle. Detail:" not in src


def test_payment_is_attempted_at_most_once():
    """Retrying a settlement could double-pay — the guard must be in the source."""
    src = (SDK_ROOT / "blindoracle_sdk" / "client.py").read_text()
    assert "not headers.get(_X402_HEADER)" in src, \
        "the 402 branch must short-circuit once a payment header is attached"


def test_session_spend_accumulates(acct, monkeypatch):
    from blindoracle_sdk.client import BlindOracleClient
    c = BlindOracleClient(wallet_key=acct.key.hex(), max_payment_usd=1.0,
                          session_budget_usd=10.0)
    for _ in range(3):
        assert c._x402_pay(LIVE, None)
    assert c.session_spent_usd == pytest.approx(0.03)
    assert len(c.payments) == 3
    assert all("nonce" in p for p in c.payments)


def test_recorded_payment_carries_no_key_material(acct):
    from blindoracle_sdk.client import BlindOracleClient
    c = BlindOracleClient(wallet_key=acct.key.hex(), max_payment_usd=1.0,
                          session_budget_usd=10.0)
    c._x402_pay(LIVE, None)
    blob = json.dumps(c.payments)
    assert acct.key.hex() not in blob and "signature" not in blob


def test_unparseable_challenge_falls_through_not_crash(acct):
    from blindoracle_sdk.client import BlindOracleClient
    c = BlindOracleClient(wallet_key=acct.key.hex(), max_payment_usd=1.0,
                          session_budget_usd=10.0)
    assert c._x402_pay({"nope": True}, None) is None


def test_cap_breach_propagates_rather_than_silently_not_paying(acct):
    """Swallowing a cap breach would look like a server failure to the caller."""
    from blindoracle_sdk.client import BlindOracleClient
    c = BlindOracleClient(wallet_key=acct.key.hex(), max_payment_usd=0.001,
                          session_budget_usd=10.0)
    with pytest.raises(PaymentCapExceeded):
        c._x402_pay(LIVE, None)


# --- the zero-dependency promise --------------------------------------------

def test_eth_account_is_an_optional_extra_not_a_hard_dep():
    txt = (SDK_ROOT / "pyproject.toml").read_text()
    assert "dependencies = []" in txt, "the SDK must stay zero-dep for non-payers"
    assert "optional-dependencies" in txt and "eth-account" in txt


def test_x402_module_imports_without_eth_account(monkeypatch):
    """Importing the SDK must never require the signing extra."""
    import importlib
    monkeypatch.setitem(sys.modules, "eth_account", None)
    importlib.reload(x402)
    assert x402.parse_challenge(body=LIVE).amount_atomic == 10000
