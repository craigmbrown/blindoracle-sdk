#!/usr/bin/env python3
"""Countersign a BlindOracle delegation chain as the delegate (an x402 seller).

A buyer recorded that it delegated work to you and named your wallet. This script
signs the chain's steps with that wallet, so the chain shows acceptanceStrength
"wallet" (your key signed) instead of "delegator_observed" (the buyer said so).

    export BO_DELEGATE_PRIVATE_KEY=0x...        # the wallet the buyer named
    python3 countersign.py dlg-0123456789abcdef0123
    python3 countersign.py dlg-... --step accept --dry-run

What it does:
  1. GET  https://api.craigmbrown.com/v1/delegations/<id>/countersign   (free, no key)
  2. for each step marked countersign_available: EIP-191 sign message_to_sign
     and POST {step, eip191_signature} to the same URL                  (free)
  3. a step that is not on the chain yet (awaiting_step) needs the delegate token the
     buyer gave you: pass --token; the call is free when the buyer prepaid it, and is
     otherwise printed for you to send with your x402 client.

Needs: pip install eth-account. The key never leaves this process; only signatures are sent.
What a countersignature proves: the holder of this wallet's key signed this exact
delegation id and task (or deliverable) hash. It does not prove who you are off-chain.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("BO_API", "https://api.craigmbrown.com")
UA = "blindoracle-countersign/1.0"


def _call(method: str, url: str, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": e.reason}


def sign(key: str, message: str) -> str:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    sig = Account.from_key(key).sign_message(encode_defunct(text=message)).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("delegation_id")
    ap.add_argument("--step", choices=["accept", "deliver"], help="only this step")
    ap.add_argument("--token", help="your delegate token, for a step not yet on the chain")
    ap.add_argument("--deliverable-sha256", help="sha256 of what you delivered (deliver step not yet on the chain)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be signed and sent")
    ap.add_argument("--api", default=API)
    a = ap.parse_args(argv)

    key = os.environ.get("BO_DELEGATE_PRIVATE_KEY", "").strip()
    if not key and not a.dry_run:
        print("set BO_DELEGATE_PRIVATE_KEY to the private key of the wallet the buyer named", file=sys.stderr)
        return 2
    code, info = _call("GET", f"{a.api}/v1/delegations/{a.delegation_id}/countersign")
    if code != 200:
        print(f"GET countersign -> {code}: {info}", file=sys.stderr)
        return 1
    if key:
        from eth_account import Account
        me = Account.from_key(key).address
        if (info.get("delegate_wallet") or "").lower() != me.lower():
            print(f"this chain names delegate wallet {info.get('delegate_wallet')}; your key is {me}", file=sys.stderr)
            return 1
    rc = 0
    for st in info.get("steps", []):
        if a.step and st["step"] != a.step:
            continue
        status = st.get("status")
        if status == "countersign_available":
            msg = st["message_to_sign"]
            body = {"step": st["step"], "eip191_signature": sign(key, msg) if key else "<signature>"}
            if a.dry_run:
                print(json.dumps({"would_sign": msg, "POST": st["request"]["url"], "body": body}, indent=1))
                continue
            c, out = _call("POST", st["request"]["url"], body)
            print(f"{st['step']}: {c} {out.get('status') or out.get('error')} "
                  f"{out.get('upgraded_from', '')} -> {out.get('strength', out.get('detail', ''))}")
            rc |= 0 if c == 201 else 1
        elif status == "awaiting_step":
            if not a.token:
                print(f"{st['step']}: not on the chain yet; rerun with --token <your delegate token>")
                continue
            msg = st["message_to_sign"]
            req = json.loads(json.dumps(st["request"]))
            body = req["body"]
            body["delegation_token"] = a.token
            if st["step"] == "deliver":
                if not a.deliverable_sha256:
                    print("deliver: pass --deliverable-sha256", file=sys.stderr)
                    rc = 1
                    continue
                body["deliverable_sha256"] = a.deliverable_sha256.lower()
                msg = msg.replace("<deliverable_sha256>", body["deliverable_sha256"])
            body["eip191_signature"] = sign(key, msg) if key else "<signature>"
            hdr = {k: (a.token if v == "<delegate_token>" else v) for k, v in req["headers"].items()}
            if a.dry_run or "X-BO-Delegation-Token" not in hdr:
                why = "dry run" if a.dry_run else "not prepaid: send this with your x402 client (402 quote first)"
                print(json.dumps({"note": why, "POST": req["url"], "headers": {**hdr, "X-BO-Delegation-Token": "…"}
                                  if "X-BO-Delegation-Token" in hdr else hdr,
                                  "body": {**body, "delegation_token": "…"}}, indent=1))
                continue
            c, out = _call("POST", req["url"], body, hdr)
            print(f"{st['step']}: {c} {out.get('status') or out.get('error')}")
            rc |= 0 if c in (200, 201, 202) else 1
        else:
            print(f"{st['step']}: {status} {st.get('why', '')}")
    print(f"verify: {info.get('verify')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
