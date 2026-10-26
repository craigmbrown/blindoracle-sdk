"""Verify BlindOracle webhook deliveries (post-and-walk-away).

@REQ-ID: RQ-BO-CALLBACK-ADOPTION-01

BlindOracle POSTs job events to your callback URL instead of making you poll.
Every delivery carries:

    X-BO-Event: job.completed | job.fulfilled | result.document | ...
    X-BO-Delivery-Id: stable id (de-duplicate on it)
    X-BO-Signature: sha256=<hex HMAC-SHA256 over the exact raw body>
    X-BO-Signature-Alg: which key signed it

Keys, by X-BO-Signature-Alg:

    hmac-sha256;key=sha256(api_key)   you registered: key = sha256(your api_key) as
                                      lowercase hex, used as utf-8 bytes
    hmac-sha256;key=callback_secret   anonymous paid call that sent callback_url: the
                                      callback_secret from that call's response
    hmac-sha256;key=server;...        you cannot verify this one; re-fetch verify_url

The body never carries the deliverable. Fetch ``verify_url`` from it and compare
``deliverable_sha256`` — that check needs no key at all.

    from blindoracle_sdk.webhooks import verify
    ok = verify(raw_body, request.headers, api_key=os.environ["BLINDORACLE_API_KEY"])
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Mapping, Optional

ALG_AGENT = "hmac-sha256;key=sha256(api_key)"
ALG_JOB = "hmac-sha256;key=callback_secret"


def _header(headers: Mapping[str, str], name: str) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v or ""
    return ""


def verify(raw_body: bytes, headers: Mapping[str, str], *,
           api_key: Optional[str] = None, callback_secret: Optional[str] = None) -> bool:
    """True when X-BO-Signature matches the key named by X-BO-Signature-Alg.

    Pass ``api_key`` for a registered agent, ``callback_secret`` for an anonymous
    paid call. Returns False for a server-signed delivery (unverifiable by design)
    or when the needed key was not supplied.
    """
    sig = _header(headers, "X-BO-Signature")
    alg = _header(headers, "X-BO-Signature-Alg")
    if not sig.startswith("sha256="):
        return False
    if alg == ALG_AGENT and api_key:
        key = hashlib.sha256(api_key.encode()).hexdigest().encode()
    elif alg == ALG_JOB and callback_secret:
        key = callback_secret.encode()
    else:
        return False
    if isinstance(raw_body, str):
        raw_body = raw_body.encode()
    want = "sha256=" + hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig)
