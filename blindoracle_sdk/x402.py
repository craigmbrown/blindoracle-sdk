"""x402 v2 payment — parse a 402 challenge and sign an EIP-3009 authorization.

@REQ-ID: RQ-BO-SDK-X402-PAY-01

Closes finding F4 of the 2026-08-16 clean-room dogfood run: the published SDK
could not pay for any of BlindOracle's 39 live SKUs. The gateway speaks x402 v2
and expects an EIP-3009 ``transferWithAuthorization`` signature; the SDK sent a
Fedimint ecash note and contained no EIP-3009 code at all, while the README
advertised "Payment = x402 (Base USDC)".

Scheme ``exact`` is **gasless** for the buyer: you sign an authorization, the
facilitator submits the transaction and pays the gas. You therefore need USDC
on Base but no ETH.

Design constraints, each load-bearing:

1. **Every signed field comes from the challenge.** ``asset``, ``payTo``,
   ``amount``, the EIP-712 domain ``name``/``version`` and the chain id are read
   from the server's own ``accepts`` entry. Nothing is defaulted or invented; a
   missing field is an error, never a guess.
2. **Caps are enforced BEFORE a signature exists.** A signed EIP-3009
   authorization is a bearer instrument. ``max_payment_usd`` and
   ``session_budget_usd`` are required, have no unlimited default, and are
   checked before any key material is touched.
3. **Unknown means refuse, not assume.** An unrecognised ``x402Version``,
   ``scheme``, ``network`` or asset raises an error naming the unsupported
   value. Guessing the decimals of an unknown token would silently mis-scale a
   payment by orders of magnitude.
4. **One attempt.** The caller retries a paid endpoint exactly once with the
   payment attached. Retrying a settlement risks double-payment.
5. **Optional dependency.** ``eth_account`` is imported lazily so the SDK keeps
   its zero-dependency promise for callers who never pay
   (``pip install blindoracle-sdk[x402]``).

A private key is never logged, never returned, and never placed in an exception
message.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "PaymentChallenge",
    "X402Error",
    "UnsupportedPaymentError",
    "PaymentCapExceeded",
    "SigningUnavailable",
    "parse_challenge",
    "build_payment_header",
    "PAYMENT_HEADER",
]

#: The header the gateway documents for the paid retry. It also accepts
#: ``X-PAYMENT`` and ``X-402-Payment``; we send the documented one.
PAYMENT_HEADER = "PAYMENT-SIGNATURE"

#: Header carrying the base64 challenge on the 402 response.
CHALLENGE_HEADER = "payment-required"

SUPPORTED_X402_VERSIONS = (2,)
SUPPORTED_SCHEMES = ("exact",)

#: Atomic-unit decimals per (network, asset). Deliberately an explicit registry:
#: an unknown asset must REFUSE rather than assume 18 or 6, because a wrong
#: exponent mis-scales a real payment by 10^12.
_ASSET_DECIMALS = {
    ("eip155:8453", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): 6,   # USDC on Base
    ("eip155:84532", "0x036cbd53842c5426634e7929541ec2318f3dcf7e"): 6,  # USDC on Base Sepolia
}

_EIP3009_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ],
}


class X402Error(Exception):
    """Base class for payment-path failures."""


class UnsupportedPaymentError(X402Error):
    """The challenge asks for something this client cannot satisfy."""


class PaymentCapExceeded(X402Error):
    """The payment would breach a caller-set spend cap. No signature was made."""


class SigningUnavailable(X402Error):
    """Signing was requested but is not possible (no key, or extra not installed)."""


class PaymentChallenge:
    """A parsed, validated x402 v2 ``accepts`` entry.

    Only entries this client can actually satisfy survive construction, so a
    ``PaymentChallenge`` is a promise that signing is possible modulo caps.
    """

    __slots__ = ("scheme", "network", "asset", "amount_atomic", "pay_to",
                 "max_timeout_seconds", "domain_name", "domain_version",
                 "chain_id", "decimals", "resource_url", "raw")

    def __init__(self, entry: Dict[str, Any], resource_url: str = "",
                 raw: Optional[Dict[str, Any]] = None):
        self.raw = raw or {}
        self.resource_url = resource_url

        self.scheme = entry.get("scheme")
        if self.scheme not in SUPPORTED_SCHEMES:
            raise UnsupportedPaymentError(
                f"unsupported x402 scheme {self.scheme!r}; this client supports "
                f"{', '.join(SUPPORTED_SCHEMES)}"
            )

        self.network = (entry.get("network") or "").strip()
        if not self.network.startswith("eip155:"):
            raise UnsupportedPaymentError(
                f"unsupported x402 network {self.network!r}; this client supports "
                f"EVM networks of the form 'eip155:<chainId>'"
            )
        try:
            self.chain_id = int(self.network.split(":", 1)[1])
        except (IndexError, ValueError):
            raise UnsupportedPaymentError(
                f"could not read a chain id from network {self.network!r}"
            ) from None

        self.asset = (entry.get("asset") or "").strip()
        if not self.asset.startswith("0x"):
            raise UnsupportedPaymentError(
                f"challenge has no usable asset address (got {self.asset!r})"
            )

        key = (self.network, self.asset.lower())
        if key not in _ASSET_DECIMALS:
            # Refusing beats guessing: an assumed exponent mis-scales real money.
            raise UnsupportedPaymentError(
                f"unknown asset {self.asset} on {self.network} — this client does "
                f"not know its decimals and will not guess. Known: "
                f"{', '.join(a for _, a in _ASSET_DECIMALS)}"
            )
        self.decimals = _ASSET_DECIMALS[key]

        self.pay_to = (entry.get("payTo") or "").strip()
        if not self.pay_to.startswith("0x"):
            raise UnsupportedPaymentError(
                f"challenge has no usable payTo address (got {self.pay_to!r})"
            )

        raw_amount = entry.get("amount")
        if raw_amount is None:
            raise UnsupportedPaymentError("challenge has no amount")
        try:
            self.amount_atomic = int(str(raw_amount))
        except ValueError:
            raise UnsupportedPaymentError(
                f"challenge amount {raw_amount!r} is not an integer of atomic units"
            ) from None
        if self.amount_atomic < 0:
            raise UnsupportedPaymentError("challenge amount is negative")

        try:
            self.max_timeout_seconds = int(entry.get("maxTimeoutSeconds") or 60)
        except (TypeError, ValueError):
            self.max_timeout_seconds = 60

        extra = entry.get("extra") or {}
        self.domain_name = extra.get("name")
        self.domain_version = extra.get("version")
        if not self.domain_name or not self.domain_version:
            # The EIP-712 domain must come from the server; a wrong domain
            # produces a signature the token contract will reject.
            raise UnsupportedPaymentError(
                "challenge is missing extra.name / extra.version, which are "
                "required to build the EIP-712 domain for this asset"
            )

    @property
    def amount_usd(self) -> float:
        """Human amount. Named `usd` because every supported asset is a USD stablecoin."""
        return self.amount_atomic / (10 ** self.decimals)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<PaymentChallenge {self.scheme} {self.amount_usd:.6f} "
                f"({self.amount_atomic} atomic) -> {self.pay_to} on {self.network}>")


def _decode_challenge_blob(blob: str) -> Dict[str, Any]:
    """Decode a challenge that may be base64 JSON or bare JSON."""
    blob = (blob or "").strip()
    if not blob:
        raise UnsupportedPaymentError("empty payment challenge")
    try:
        return json.loads(blob)
    except (ValueError, TypeError):
        pass
    try:
        pad = "=" * (-len(blob) % 4)
        return json.loads(base64.b64decode(blob + pad).decode("utf-8"))
    except Exception:
        raise UnsupportedPaymentError(
            "payment challenge is neither JSON nor base64-encoded JSON"
        ) from None


def parse_challenge(body: Any = None, headers: Any = None) -> PaymentChallenge:
    """Parse a 402 response into the first `accepts` entry we can satisfy.

    Reads the ``payment-required`` header when present and falls back to the
    response body, because the gateway sends both. Raises
    :class:`UnsupportedPaymentError` naming the unsupported value when no entry
    is satisfiable — never a generic failure.
    """
    doc: Optional[Dict[str, Any]] = None

    if headers is not None:
        get = getattr(headers, "get", None)
        blob = get(CHALLENGE_HEADER) or get(CHALLENGE_HEADER.title()) if get else None
        if blob:
            doc = _decode_challenge_blob(blob)

    if doc is None and body is not None:
        doc = _decode_challenge_blob(body) if isinstance(body, (str, bytes)) else body

    if not isinstance(doc, dict):
        raise UnsupportedPaymentError("no x402 challenge found in headers or body")

    version = doc.get("x402Version")
    if version is not None and version not in SUPPORTED_X402_VERSIONS:
        raise UnsupportedPaymentError(
            f"unsupported x402Version {version!r}; this client supports "
            f"{', '.join(str(v) for v in SUPPORTED_X402_VERSIONS)}"
        )

    accepts = doc.get("accepts") or []
    if not accepts:
        raise UnsupportedPaymentError("x402 challenge lists no `accepts` entries")

    resource_url = ((doc.get("resource") or {}) or {}).get("url", "") \
        if isinstance(doc.get("resource"), dict) else ""

    reasons = []
    for entry in accepts:
        try:
            return PaymentChallenge(entry, resource_url=resource_url, raw=doc)
        except UnsupportedPaymentError as e:
            reasons.append(str(e))
    raise UnsupportedPaymentError(
        "no `accepts` entry is satisfiable by this client: " + "; ".join(reasons)
    )


def _check_caps(challenge: PaymentChallenge, max_payment_usd: Optional[float],
                session_spent_usd: float, session_budget_usd: Optional[float]) -> None:
    """Enforce spend caps. Called BEFORE any key material is touched."""
    if max_payment_usd is None:
        raise PaymentCapExceeded(
            "max_payment_usd is required — this client will not sign a transfer "
            "authorization without an explicit per-call cap"
        )
    if session_budget_usd is None:
        raise PaymentCapExceeded(
            "session_budget_usd is required — this client will not sign a transfer "
            "authorization without an explicit cumulative cap"
        )
    amt = challenge.amount_usd
    if amt > max_payment_usd:
        raise PaymentCapExceeded(
            f"payment of ${amt:.6f} exceeds max_payment_usd ${max_payment_usd:.6f} "
            f"for {challenge.resource_url or 'this resource'} — nothing was signed"
        )
    if session_spent_usd + amt > session_budget_usd:
        raise PaymentCapExceeded(
            f"payment of ${amt:.6f} would take session spend to "
            f"${session_spent_usd + amt:.6f}, over session_budget_usd "
            f"${session_budget_usd:.6f} — nothing was signed"
        )


def _load_account(private_key: Optional[str]):
    """Lazily import eth_account and load the signer. Never logs the key."""
    key = private_key or os.getenv("BLINDORACLE_WALLET_KEY") or ""
    key = key.strip()
    if not key:
        raise SigningUnavailable(
            "no signing key: pass private_key= or set BLINDORACLE_WALLET_KEY. "
            "The key is used locally to sign an EIP-3009 authorization and is "
            "never transmitted."
        )
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
    except ImportError:
        raise SigningUnavailable(
            "x402 payment needs the signing extra: pip install 'blindoracle-sdk[x402]'"
        ) from None
    try:
        return Account.from_key(key), encode_typed_data
    except Exception:
        # Deliberately does NOT echo the key or its length.
        raise SigningUnavailable("the configured signing key could not be loaded") from None


def build_payment_header(
    challenge: PaymentChallenge,
    *,
    private_key: Optional[str] = None,
    max_payment_usd: Optional[float] = None,
    session_budget_usd: Optional[float] = None,
    session_spent_usd: float = 0.0,
    now: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Sign an EIP-3009 authorization for `challenge`.

    Returns ``(header_value, payload)`` where ``header_value`` is the base64
    payload for :data:`PAYMENT_HEADER` and ``payload`` is the decoded dict (for
    logging the authorization — never the key).

    Caps are checked first, so a breach raises before a signature exists.
    """
    _check_caps(challenge, max_payment_usd, session_spent_usd, session_budget_usd)

    account, encode_typed_data = _load_account(private_key)

    ts = int(now if now is not None else time.time())
    valid_after = 0
    valid_before = ts + max(challenge.max_timeout_seconds, 60)
    nonce = "0x" + secrets.token_hex(32)

    message = {
        "from": account.address,
        "to": challenge.pay_to,
        "value": challenge.amount_atomic,
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": bytes.fromhex(nonce[2:]),
    }
    domain = {
        "name": challenge.domain_name,
        "version": challenge.domain_version,
        "chainId": challenge.chain_id,
        "verifyingContract": challenge.asset,
    }

    signable = encode_typed_data(
        domain_data=domain,
        message_types={"TransferWithAuthorization":
                       _EIP3009_TYPES["TransferWithAuthorization"]},
        message_data=message,
    )
    signed = account.sign_message(signable)

    payload = {
        "x402Version": 2,
        "scheme": challenge.scheme,
        "network": challenge.network,
        "payload": {
            "signature": signed.signature.hex()
            if signed.signature.hex().startswith("0x")
            else "0x" + signed.signature.hex(),
            "authorization": {
                "from": account.address,
                "to": challenge.pay_to,
                "value": str(challenge.amount_atomic),
                "validAfter": str(valid_after),
                "validBefore": str(valid_before),
                "nonce": nonce,
            },
        },
    }
    header_value = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return header_value, payload
