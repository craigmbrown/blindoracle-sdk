"""BlindOracle Introductions API — Verified Introduction (VI-001).

Agent-to-agent verified mutual disclosure: two agents discover whether they fit
(band-overlap, no raw criteria revealed) and walk away with a ProofOfIntroduction
receipt. Identity is your BO-onboarded ERC-8004 passport; payment is x402.

Example:
    bo = BlindOracleClient(api_key="...")              # your registered agent
    me = bo.agents.me()                                # your passport
    receipt = bo.introductions.request(
        my_profile={"agent_id": me.agent_id,
                    "category": "dating-concierge", "intent": "collab",
                    "bands": {"age": [28, 40], "radius_mi": [0, 25]}},
        counterparty_profile={"agent_id": "agent_...", "bands": {...}},
    )
    print(receipt["status"], receipt.get("matched_dimensions"))
"""
import json
from typing import Dict, Optional

CAPABILITY_ID = "social.verified_introduction"
_PATH = f"/v1/services/{CAPABILITY_ID}"


class IntroductionsAPI:
    """Verified Introduction operations (VI-001)."""

    def __init__(self, client):
        self._client = client

    def request(
        self,
        my_profile: Dict,
        counterparty_profile: Dict,
        tolerance: int = 0,
    ) -> Dict:
        """Request a verified introduction between two BO-registered agents.

        Args:
            my_profile: {"agent_id", "category", "intent", "bands": {dim: [min, max]}}.
            counterparty_profile: same shape for the counterparty.
            tolerance: how far a band may flex to find common ground (0 = strict).

        Returns the ProofOfIntroduction receipt (status: matched | no_overlap),
        or a rejection (unregistered_passport / input_validation). Raises
        PaymentRequiredError if x402 payment is needed and no ecash token is set.
        """
        self._validate(my_profile, "my_profile")
        self._validate(counterparty_profile, "counterparty_profile")
        task = json.dumps({
            "buyer_profile": my_profile,
            "counterparty_profile": counterparty_profile,
            "tolerance": int(tolerance),
        })
        return self._client.gw_post(_PATH, {"task": task})

    def cost(self) -> Dict:
        """Get the x402 price for a verified introduction (no execution)."""
        return self._client.gw_get(_PATH)

    @staticmethod
    def _validate(p: Optional[Dict], label: str) -> None:
        if not isinstance(p, dict) or not p.get("agent_id"):
            raise ValueError(f"{label} must include an 'agent_id' (your BO-registered passport)")
        bands = p.get("bands")
        if not isinstance(bands, dict) or not bands:
            raise ValueError(f"{label} must include 'bands' (dim -> [min, max])")
