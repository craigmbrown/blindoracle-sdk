#!/usr/bin/env python3
"""Verify us without trusting us: recent settlements resolve and are self-consistent (no spend)."""
import json
from _common import client, args

a = args(__doc__)
bo = client()
proofs = bo.proofs.settlements(a.limit)
bad = 0
for p in proofs:
    one = bo.proofs.settlement(p.get("settlement_ref") or p.get("proof_id") or "")
    consistent = bool(one) and (one.get("settlement_ref") == p.get("settlement_ref"))
    bad += 0 if consistent else 1
    print(("ok  " if consistent else "BAD ") + f"{p.get('task_class')} {p.get('settled_amount_usdc')} {p.get('basescan_url')}")
print(json.dumps({"checked": len(proofs), "inconsistent": bad, "recipe": bo.proofs.verify_recipe()}))
