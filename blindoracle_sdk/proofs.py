"""BlindOracle Proofs API — verify a settlement without trusting us (v0.10).

Wraps the free, unauthenticated proof surface shipped 2026-08-29
(RQ-BO-PUBLIC-PROOF-01):

    GET /v1/proofs/settlements?limit=N     recent ProofOfSettledOutcome rows
    GET /v1/proofs/settlement/{ref}        one proof by settlement tx / job ref

A proof binds a payment to the work: ``settlement_ref`` must equal the tx you
can open on basescan, and ``task_class``/``ts`` must match what you bought.
It proves payment, integrity and linkage — it does NOT prove the work was
correct; quality is a separate question.

Example:
    for p in bo.proofs.settlements(limit=5):
        print(p["task_class"], p["settled_amount_usdc"], p["basescan_url"])
    one = bo.proofs.settlement("0x32041ae3…")
    assert one["settlement_ref_resolved"]
"""
from typing import Dict, List, Optional


class ProofsAPI:
    """Public settlement proofs (read-only, no auth, no payment)."""

    def __init__(self, client):
        self._client = client

    def settlements(self, limit: int = 10) -> List[Dict]:
        """Recent settlement proofs, newest first. Synthetic rows are excluded server-side."""
        data = self._client.gw_get("/v1/proofs/settlements", params={"limit": int(limit)})
        return list(data.get("proofs") or [])

    def settlement(self, ref: str) -> Optional[Dict]:
        """One proof by settlement reference (Base tx hash or job/settlement id). None if unknown."""
        ref = (ref or "").strip()
        if not ref:
            return None
        data = self._client.gw_get(f"/v1/proofs/settlement/{ref}")
        if not isinstance(data, dict):
            return None
        proofs = data.get("proofs")
        if isinstance(proofs, list) and proofs:      # live shape: {"count": 1, "proofs": [ {...} ]}
            return proofs[0]
        if data.get("proof_id"):                      # tolerate a bare proof object
            return data
        return data.get("proof") or None

    @staticmethod
    def verify_recipe() -> List[str]:
        """The three human-checkable steps the gateway publishes with every listing."""
        return [
            "1. Open basescan_url and confirm the USDC amount and recipient on Base mainnet.",
            "2. GET /v1/proofs/settlement/<tx>: settlement_ref must equal that tx; task_class/ts must match what you bought.",
            "3. This proves payment, integrity and linkage — not that the work was correct.",
        ]
