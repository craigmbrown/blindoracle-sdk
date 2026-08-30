#!/usr/bin/env python3
"""Claim starter credit -> balance -> buy the cheapest SKU -> verify its settlement proof."""
import json
import os
from _common import client, args

a = args(__doc__)
bo = client(require_key=True)
if not bo.ecash_token:
    if not a.live:
        print("dry-run: would POST /a2a/agents/<me>/starter-credit (one per agent, ever)"); raise SystemExit(0)
    r = bo.agents.claim_starter_credit()
    note = r.get("starter_credit_note")
    if not note:
        print("claim refused:", json.dumps({k: v for k, v in r.items() if k != "starter_credit_note"})); raise SystemExit(1)
    bo.ecash_token = note
    print("claimed: store this note in BLINDORACLE_ECASH_TOKEN (shown once):", note[:12] + "…")
print("balance:", bo.wallet.balance())
if not a.live:
    print(f"dry-run: would call {a.sku} over /v1/mcp with the note in _meta"); raise SystemExit(0)
res = bo.mcp.call(a.sku, {}, x402_payment=bo.ecash_token)
print("result:", "ERROR " + res["text"][:120] if res["isError"] else json.dumps(res["structured"])[:300])
sc = res.get("structured") or {}
ref = (sc.get("payment") or {}).get("tx_hash") or sc.get("job_id")
if ref:
    print("proof:", json.dumps(bo.proofs.settlement(ref) or {"pending": ref})[:300])
print("balance after:", bo.wallet.balance())
