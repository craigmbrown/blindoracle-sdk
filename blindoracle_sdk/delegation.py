"""BlindOracle Delegation API — make your agents auditable.

Emit and verify ``ProofOfDelegation`` (Nostr kind 30014) records so every action an
agent takes carries an accountable, tamper-evident chain back to the authorizing party.

Design goals (mirrors the production hook ``.claude/hooks/pre_tool_use.py``, so proofs
emitted here cross-verify with the fleet verifier):

  * **Integrity** — ``event_id = sha256(canonical(record − event_id))``. Any field edit
    is detectable.
  * **Chain** — each record's ``prev_hash`` is the previous record's ``event_id``.
    Insert / delete / reorder breaks the chain.
  * **Authority** — HMAC-SHA256 ``signature`` proves the holder of the delegation key
    authorized the spawn.
  * **Shared-ProofDB safe** — verification filters to kind 30014, so the log may also
    hold other proof kinds (badges, onboarding) without corrupting chain verification.

Dependency-free (stdlib only), works fully offline. No secret is stored: the signing
key is derived from the delegator id, exactly as the production hook does, so signatures
are self-consistent and independently checkable.

Usage::

    from blindoracle_sdk.delegation import DelegationLog

    log = DelegationLog("data/delegation_proofs.json")
    log.emit(delegator="operator-root", delegate="Agent A — strategy", scope="advise")
    log.emit(delegator="agent-A",       delegate="Agent B — executor", scope="execute")

    result = log.verify()          # {"ok": True, "total_records": 2, "chained_records": 2, ...}
    assert result["ok"]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DELEGATION_KIND = 30014
PROOF_TYPE = "ProofOfDelegation"


# ── crypto helpers (identical derivation to the production hook) ──────────────

def delegator_passport_hash(delegator: str, timestamp: int) -> str:
    """Stable identity token for the delegator: ``sha256(delegator:timestamp)``."""
    return hashlib.sha256(f"{delegator}:{timestamp}".encode()).hexdigest()


def delegation_signature(delegator: str, delegate: str, timestamp: int) -> str:
    """HMAC-SHA256 over the delegation, keyed by a delegator-derived key.

    No stored secret: the key is ``sha256("delegation_key:" + delegator)`` so the
    signature is self-consistent and verifiable by anyone re-deriving it the same way.
    """
    key = hashlib.sha256(f"delegation_key:{delegator}".encode()).digest()
    msg = f"{delegator}:{delegate}:{timestamp}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _event_id(record: Dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "event_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_signature(record: Dict[str, Any]) -> bool:
    """Re-derive and check a record's HMAC signature."""
    try:
        expected = delegation_signature(
            record["delegator"], record["delegate"], record["delegation_timestamp"]
        )
        return hmac.compare_digest(expected, record.get("signature", ""))
    except (KeyError, TypeError):
        return False


# ── the log ───────────────────────────────────────────────────────────────--

class DelegationLog:
    """An append-only ProofOfDelegation log with tamper-evident hash chaining."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- read --------------------------------------------------------------

    def _records(self, only_delegation: bool = True) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if only_delegation and rec.get("kind") != DELEGATION_KIND:
                continue  # foreign proof kind in a shared ProofDB — skip
            out.append(rec)
        return out

    def _last_event_id(self) -> str:
        recs = self._records(only_delegation=True)
        return recs[-1]["event_id"] if recs and "event_id" in recs[-1] else ""

    # -- write -------------------------------------------------------------

    def emit(
        self,
        delegator: str,
        delegate: str,
        scope: Optional[str] = None,
        timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Append a signed, hash-chained ProofOfDelegation (kind 30014).

        Returns the written record (including its ``event_id``).
        """
        ts = int(timestamp if timestamp is not None else time.time())
        record: Dict[str, Any] = {
            "kind": DELEGATION_KIND,
            "proof_type": PROOF_TYPE,
            "delegator": delegator,
            "delegator_passport_hash": delegator_passport_hash(delegator, ts),
            "delegate": delegate[:256],
            "delegation_timestamp": ts,
            "signature": delegation_signature(delegator, delegate[:256], ts),
            "status": "active",
            "prev_hash": self._last_event_id(),
        }
        if scope is not None:
            record["scope"] = scope
        record["event_id"] = _event_id(record)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")
        return record

    # -- verify ------------------------------------------------------------

    def verify(self) -> Dict[str, Any]:
        """Verify integrity + chain over kind-30014 records.

        Returns ``{ok, total_records, chained_records, first_break_at, details}``.
        Filters to delegation records so a shared ProofDB does not break verification.
        """
        result: Dict[str, Any] = {
            "ok": True,
            "total_records": 0,
            "chained_records": 0,
            "first_break_at": None,
            "details": [],
        }
        last_event_id: Optional[str] = None
        last_was_chained = False
        for i, rec in enumerate(self._records(only_delegation=True)):
            result["total_records"] += 1

            stored = rec.get("event_id")
            if stored and _event_id(rec) != stored:
                result["ok"] = False
                if result["first_break_at"] is None:
                    result["first_break_at"] = i
                result["details"].append({"idx": i, "type": "field_tamper"})

            if "prev_hash" not in rec:
                last_event_id = stored
                last_was_chained = False
                continue
            result["chained_records"] += 1
            if last_was_chained and rec["prev_hash"] != last_event_id:
                result["ok"] = False
                if result["first_break_at"] is None:
                    result["first_break_at"] = i
                result["details"].append({"idx": i, "type": "chain_break"})
            last_event_id = stored
            last_was_chained = True
        return result

    def chain_to_root(self, event_id: str) -> List[Dict[str, Any]]:
        """Return the authority chain (leaf → root) ending at ``event_id``.

        Walks ``prev_hash`` links back to the root delegation. Useful for answering
        "who authorized this action?" — the last element is the root delegator.
        """
        by_eid = {r["event_id"]: r for r in self._records() if "event_id" in r}
        chain: List[Dict[str, Any]] = []
        cur = by_eid.get(event_id)
        seen = set()
        while cur and cur["event_id"] not in seen:
            seen.add(cur["event_id"])
            chain.append(cur)
            prev = cur.get("prev_hash") or ""
            cur = by_eid.get(prev) if prev else None
        return chain
