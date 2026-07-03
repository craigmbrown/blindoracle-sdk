"""
blindoracle_sdk.skill_marketplace — "skill purchase via x402" reference flow.

@REQ-ID: RQ-YTMEMO-ACT2-XjOLz--C_nQ-001
@BLP: BLP-041 value_creation, BLP-010 autonomy, BLP-023 provenance
Design: specs/design-rq-ytmemo-act2-XjOLz--C_nQ.md

Thin, additive sub-namespace over :class:`~blindoracle_sdk.marketplace.MarketplaceAPI`
that turns a reusable agent capability ("skill") into a **buyable good** — the
[14:35] thesis from the source memo: *"buy the algorithm for a generic agent."*
A skill SKU is an ordinary ``/a2a/capabilities`` record (``category="skill"``,
``capability_id`` prefixed ``skill.``) whose deliverable is a small, portable
JSON "algorithm pack" (prompt template + config + usage note) rather than a
one-off answer. No new gateway endpoint, no new payment rail — it rides the
same ``post_request -> accept -> wait`` buy loop and the same x402 pre-payment
that any other metered SKU uses.

Buyer flow::

    bo = BlindOracleClient(api_key="bo_live_...")
    catalog = bo.marketplace.skills.browse()
    purchase = bo.marketplace.skills.purchase(
        "skill.agent-algorithm-pack", budget_usd=0.05)
    check = bo.marketplace.skills.verify(purchase)   # key-free, local recompute
    assert check["ok"]
    pack = purchase.artifact                          # the portable skill pack

Seller flow::

    bo.marketplace.skills.list_skill(
        "skill.my-niche-pack", "My Niche Algorithm Pack",
        price_usd=0.05,
        skill_manifest={"prompt": "...", "config": {...}, "usage": "..."})

Trust: the purchase receipt binds ``content_sha256`` (plain hash) and a
contents-hiding ``commitment`` (``sha3_256(artifact_bytes || salt)``) over the
delivered artifact bytes. :meth:`SkillMarketplaceAPI.verify` recomputes both
**locally, from only the bytes the buyer received** — no BlindOracle secret or
extra network call is required (the deeper server-side receipt lives on the
internal ``chainlink_job_proof_receipt`` module; this is the buyer-side,
key-free half of that same binding). See docs/marketplace.md
"Buying a skill SKU via x402".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SKILL_CATEGORY = "skill"
SKILL_ID_PREFIX = "skill."
_MANIFEST_MARKER = "skill_manifest="


def _canonical_bytes(payload: Any) -> bytes:
    """Canonical bytes for hashing. dict -> sorted-key JSON; bytes/str passthrough."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pack_manifest(description: str, skill_manifest: Dict[str, Any]) -> str:
    """Pack a one-line description + inline JSON manifest into the SKU's
    ``description`` field (the gateway stores it verbatim; no schema change)."""
    manifest_json = json.dumps(skill_manifest, sort_keys=True, separators=(",", ":"))
    prefix = f"{description.strip()} | " if description.strip() else ""
    return f"{prefix}{_MANIFEST_MARKER}{manifest_json}"


def _unpack_manifest(description: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of the inline manifest packed by :func:`_pack_manifest`."""
    if not description or _MANIFEST_MARKER not in description:
        return None
    _, _, raw = description.partition(_MANIFEST_MARKER)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def compute_commitment(payload: Any, salt: bytes) -> str:
    """``sha3_256(payload_bytes || salt)`` — the same contents-hiding fingerprint
    algo used by the server-side receipt (``disclosure.commitment``), so a
    buyer's local recompute matches the seller-issued receipt byte-for-byte."""
    return "0x" + hashlib.sha3_256(_canonical_bytes(payload) + salt).hexdigest()


def compute_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


@dataclass
class SkillPurchase:
    """A completed skill purchase: the underlying marketplace ``Job`` plus the
    parsed skill artifact and (if present) its purchase receipt block."""

    job: Any  # blindoracle_sdk.marketplace.Job
    capability_id: str
    artifact: Dict[str, Any] = field(default_factory=dict)
    receipt: Optional[Dict[str, Any]] = None

    @property
    def job_id(self) -> Optional[str]:
        return getattr(self.job, "job_id", None)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<SkillPurchase {self.capability_id} job={self.job_id}>"


class SkillMarketplaceAPI:
    """``bo.marketplace.skills`` — buy/sell reusable agent-skill SKUs.

    Delegates every network call to the wrapped :class:`MarketplaceAPI` — no
    new HTTP plumbing. Reachable as ``bo.marketplace.skills`` once wired onto
    :class:`~blindoracle_sdk.marketplace.MarketplaceAPI`.
    """

    def __init__(self, market):
        self._m = market

    # -- seller -------------------------------------------------------------
    def list_skill(
        self,
        capability_id: str,
        display_name: str,
        *,
        price_usd: float,
        skill_manifest: Dict[str, Any],
        description: str = "",
        tags: Optional[List[str]] = None,
        visibility: str = "open",
    ) -> dict:
        """Publish a buyable skill SKU (``category="skill"``).

        ``skill_manifest`` is the portable capability pack itself (prompt
        template / config / usage note) — packed inline into the catalog
        record's ``description`` field so no gateway schema change is needed.
        """
        if not capability_id.startswith(SKILL_ID_PREFIX):
            capability_id = f"{SKILL_ID_PREFIX}{capability_id}"
        return self._m.register_sku(
            capability_id,
            display_name,
            price_per_call_usd=price_usd,
            description=_pack_manifest(description, skill_manifest),
            category=SKILL_CATEGORY,
            tags=[SKILL_CATEGORY, *(tags or [])],
            visibility=visibility,
        )

    # -- buyer ----------------------------------------------------------------
    def browse(self, *, tag: Optional[str] = SKILL_CATEGORY) -> List[dict]:
        """The skill catalog — ``list_skus()`` filtered to buyable skill SKUs."""
        skus = self._m.list_skus()
        out = []
        for sku in skus:
            is_skill = (
                sku.get("category") == SKILL_CATEGORY
                or str(sku.get("capability_id", "")).startswith(SKILL_ID_PREFIX)
                or (tag and tag in (sku.get("tags") or []))
            )
            if not is_skill:
                continue
            manifest = _unpack_manifest(sku.get("description", ""))
            out.append({**sku, "skill_manifest": manifest})
        return out

    def purchase(
        self,
        capability_id: str,
        *,
        budget_usd: float,
        task: str = "deliver skill pack",
        wait_timeout: float = 300.0,
    ) -> SkillPurchase:
        """Buy a skill SKU: ``post_request -> accept best bid -> wait``.

        x402 pre-payment for the metered SKU rides the client's existing
        auth/pre-pay path (unchanged from any other marketplace purchase).
        Raises the same errors as :meth:`MarketplaceAPI.accept` when the
        budget can't cover any bid (``ValueError: no bids on request ...``).
        """
        req = self._m.post_request(
            capability_id, task, budget_usd=budget_usd,
            tags=[SKILL_CATEGORY], sla_max_latency_secs=wait_timeout,
        )
        job = self._m.accept(req.request_id)
        job = self._m.wait(job.job_id, timeout=wait_timeout)
        artifact = self._parse_artifact(job)
        receipt = artifact.pop("_receipt", None) if isinstance(artifact, dict) else None
        return SkillPurchase(job=job, capability_id=capability_id,
                              artifact=artifact, receipt=receipt)

    @staticmethod
    def _parse_artifact(job) -> Dict[str, Any]:
        """Parse the delivered skill pack out of the job's result summary.
        Sellers deliver JSON via ``complete(result_summary=json.dumps(...))``;
        fall back to a raw-text wrapper if it isn't JSON."""
        raw = getattr(job, "result_summary", "") or ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"pack": parsed}
        except (json.JSONDecodeError, TypeError):
            return {"pack": raw}

    # -- trust ----------------------------------------------------------------
    def receipt(self, purchase: SkillPurchase, *, cross_check: bool = False) -> Optional[dict]:
        """The purchase's key-free receipt block, if the seller embedded one
        in the delivered artifact (``_receipt``). ``cross_check=True`` also
        calls ``MarketplaceAPI.verify(job_id)`` against the gateway (optional,
        not required for the buyer's own content-integrity check)."""
        receipt = purchase.receipt
        if cross_check and purchase.job_id:
            gw = self._m.verify(purchase.job_id)
            if receipt is None:
                receipt = {}
            receipt = {**receipt, "gateway_verify": gw}
        return receipt

    def verify(self, purchase: SkillPurchase) -> dict:
        """KEY-FREE: recompute ``content_sha256`` + ``commitment`` over the
        delivered artifact bytes and compare against the purchase's receipt.
        Pure — no BlindOracle secret, no server round-trip. Fails closed
        (``ok: False``) when the receipt is missing or bytes were tampered."""
        receipt = purchase.receipt or {}
        deliverable = receipt.get("deliverable", receipt)
        expected_sha256 = deliverable.get("content_sha256")
        expected_commitment = deliverable.get("commitment")
        salt_hex = (deliverable.get("salt") or "0x")[2:]

        checks: Dict[str, bool] = {}
        if not expected_sha256 or not expected_commitment or not salt_hex:
            return {"ok": False, "reason": "no receipt on purchase", "checks": {}}

        artifact_bytes = _canonical_bytes(purchase.artifact)
        checks["content_sha256"] = (
            hashlib.sha256(artifact_bytes).hexdigest() == expected_sha256
        )
        try:
            salt = bytes.fromhex(salt_hex)
            recomputed = compute_commitment(purchase.artifact, salt)
        except ValueError:
            recomputed = ""
        checks["commitment"] = (recomputed == expected_commitment)

        return {"ok": all(checks.values()), "job_id": purchase.job_id, "checks": checks}
