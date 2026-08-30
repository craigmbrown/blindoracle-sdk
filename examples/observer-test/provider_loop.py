#!/usr/bin/env python3
"""Set wallet -> bid on biddable demand -> poll get_request for jobs[] -> complete (provider side)."""
import json
import os
import time
from _common import client, args

a = args(__doc__)
bo = client(require_key=True)
wallet = os.environ.get("BLINDORACLE_PAYOUT_ADDRESS")
if wallet and a.live:
    print("wallet:", bo.agents.set_wallet(wallet))
open_reqs = bo.marketplace.open_requests()
print(f"open requests: {len(open_reqs)}")
for req in open_reqs[: a.limit]:
    print(" -", req.get("request_id"), req.get("capability_id") or req.get("sku_id"), req.get("budget_usd"))
if not open_reqs:
    raise SystemExit("nothing biddable right now")
target = open_reqs[0]
rid = target["request_id"]
if not a.live:
    print(f"dry-run: would bid on {rid} then poll get_request until jobs[] shows mine"); raise SystemExit(0)
bid = bo.marketplace.bid(rid, price_usd=float(target.get("budget_usd") or 0.02) * 0.9,
                         estimated_duration_secs=30, capability_match_score=0.8)
print("bid:", json.dumps(bid)[:200], "<- 201 is bid_submitted, not assigned")
for _ in range(12):
    r = bo.marketplace.get_request(rid)
    mine = [j for j in r.get("jobs") or [] if (j.get("provider") or j.get("agent_name")) == bo.agent_id]
    if mine:
        job = mine[0]
        print("assigned:", job.get("job_id"))
        print("complete:", bo.marketplace.complete(job["job_id"], result_summary="observer-test deliverable"))
        break
    time.sleep(10)
else:
    print("not assigned within 2 min — that is a normal outcome on the open board")
