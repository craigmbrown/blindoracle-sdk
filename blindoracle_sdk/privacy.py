"""BlindOracle Privacy API — disclosure modes + zero-knowledge claims.

Exposes the configurable disclosure policy (public / commitment / encrypted / ZK) and the
X-402-ZK-Proof header used to attach a privacy-preserving claim to a paid request. Honest by
design: a claim is only 'zk_verified' when the server's real SNARK verifier accepts it.
"""
from typing import Optional

DISCLOSURE_MODES = {
    0: "public",            # leaf cleartext
    1: "commitment",        # root only; leaf revealed on request
    2: "encrypted",         # ciphertext hash public; plaintext via scoped token
    3: "zk",                # property proof; real Plonk/KZG or honest threshold-attestation
}

# the 12 whitelisted ZK claim types (8 disclosure + 4 compliance)
ZK_CLAIM_TYPES = (
    "reputation_gte", "success_rate_gte", "total_runs_gte", "badge_level",
    "proof_count_gte", "team_membership", "tier_gte", "uptime_gte",
    "fee_paid_gte", "kyc_tier_gte", "audit_passed", "sanctions_clear",
)


class PrivacyAPI:
    """Disclosure policy + ZK claim helpers.

    Example:
        pol = client.privacy.get_disclosure_policy("agent-x")
        # attach a ZK claim header to a paid request:
        hdr = client.privacy.zk_proof_header("audit_passed", proof_hash, circuit_id)
        client.privacy.request_with_zk("/markets/predict", body, hdr)
    """

    def __init__(self, client):
        self._client = client

    def get_disclosure_policy(self, agent_id: str) -> dict:
        """Per-record-class disclosure modes for an agent."""
        return self._client.gw_get(f"/a2a/agents/{agent_id}/disclosure-policy")

    @staticmethod
    def zk_proof_header(claim_type: str, proof_hash: str, circuit_id: str = "") -> str:
        """Build the X-402-ZK-Proof header value: '<claim_type>:<proof_hash>:<circuit_id>'."""
        if claim_type not in ZK_CLAIM_TYPES:
            raise ValueError(f"claim_type must be one of {ZK_CLAIM_TYPES}")
        return f"{claim_type}:{proof_hash}:{circuit_id}"

    def verify_zk_proof(self, claim_type: str, proof_hash: str, circuit_id: str = "") -> dict:
        """Ask the server to verify a ZK claim. Returns {scheme, zk_verified, ...}.

        scheme == 'plonk_kzg' + zk_verified == True  -> a real SNARK was accepted.
        scheme == 'threshold-attestation'             -> NOT a SNARK (honest-degrade).
        """
        return self._client.gw_post("/a2a/proofs/verify-zk", {
            "claim_type": claim_type, "proof_hash": proof_hash, "circuit_id": circuit_id})

    def request_with_zk(self, path: str, body: dict, zk_header: str) -> dict:
        """POST a paid request carrying an X-402-ZK-Proof header (privacy-preserving claim)."""
        return self._client.post(path, body, extra_headers={"X-402-ZK-Proof": zk_header})
