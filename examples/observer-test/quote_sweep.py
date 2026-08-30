#!/usr/bin/env python3
"""Every SKU must answer an unpaid POST with HTTP 402 and a real price (no spend)."""
import json
import urllib.request
from _common import client, args

a = args(__doc__)
bo = client()
rows = bo.gw_get("/v1/services").get("services") or []
ok = quote_only = retired = 0
for r in rows:
    sku = r["sku_id"]
    req = urllib.request.Request(f"{bo.gateway_base_url}/v1/services/{sku}", data=b"{}",
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30); status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    if status == 402:
        ok += 1
    elif r.get("price_usd") in (0, 0.0):
        retired += 1
    else:
        quote_only += 1
        print(f"  unexpected {status} for {sku}")
print(json.dumps({"skus": len(rows), "quote_402": ok, "retired_or_free": retired, "other": quote_only}))
