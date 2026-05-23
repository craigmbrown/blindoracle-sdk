"""BlindOracle Audit API — verifiable, on-chain-anchored agent audits.

Exposes the verifiable-anchoring layer (shipped 2026-05-23): retrieve an agent's audit report +
attestation, and INDEPENDENTLY verify it — inclusion proofs are checked client-side (don't trust
the server), anchor receipts via any public RPC / Nostr relay.
"""
import hashlib
import json
import urllib.request
from typing import Optional

# public Base RPCs for keyless anchor read-back (fallback chain)
_BASE_MAINNET_RPC = ["https://mainnet.base.org", "https://base.llamarpc.com"]
_BASE_SEPOLIA_RPC = ["https://sepolia.base.org"]
_VERIFY_ANCHOR_SELECTOR = "0x9f3f8a13"  # keccak256("verifyAnchor(bytes32)")[:4]


class AuditAttestation:
    """An agent's 'VERIFIABLY-AUDITED' attestation (lives in its passport)."""
    def __init__(self, data: dict):
        self.audit_id = data.get("audit_id")
        self.risk_score = data.get("risk_score")
        self.risk_level = data.get("risk_level")
        self.findings_count = data.get("findings_count")
        self.audit_hash = data.get("audit_hash")
        self.proof_of_audit_id = data.get("proof_of_audit_id")        # kind 30105
        self.state_anchor_proof_id = data.get("state_anchor_proof_id")  # kind 30106
        self.merkle_root = data.get("merkle_root")
        self.root_commitment = data.get("root_commitment")
        self.witnesses = data.get("witnesses", {})
        self.badge = data.get("badge")
        self.raw = data

    def __repr__(self):
        return (f"<AuditAttestation {self.audit_id!r} risk={self.risk_score} "
                f"badge={self.badge!r} anchored={bool(self.state_anchor_proof_id)}>")


def _sorted_pair(a_hex: str, b_hex: str) -> str:
    a, b = bytes.fromhex(a_hex), bytes.fromhex(b_hex)
    lo, hi = (a, b) if a <= b else (b, a)
    return hashlib.sha256(lo + hi).hexdigest()


def verify_inclusion(leaf_hex: str, proof_path: list, merkle_root_hex: str) -> bool:
    """Client-side inclusion check (sorted-pair Merkle). No network, no trust in the server.

    Fold the leaf with each sibling in ``proof_path`` and compare to ``merkle_root_hex``.
    """
    acc = leaf_hex
    for sib in proof_path:
        acc = _sorted_pair(acc, sib)
    return acc == merkle_root_hex


def _rpc(urls, method, params, timeout=15):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, data=body, headers={
                "content-type": "application/json", "User-Agent": "blindoracle-sdk/0.2"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode()).get("result")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"all RPCs failed: {last}")


def verify_anchor(root_commitment_hex: str, contract: str, network: str = "base-mainnet") -> dict:
    """Independently confirm a state-anchor root via ProofAnchor.verifyAnchor on a public RPC.

    Returns {"exists": bool, "network", "contract"}. No keys, no spend.
    """
    urls = _BASE_MAINNET_RPC if network == "base-mainnet" else _BASE_SEPOLIA_RPC
    data = _VERIFY_ANCHOR_SELECTOR + root_commitment_hex.removeprefix("0x").rjust(64, "0")
    out = _rpc(urls, "eth_call", [{"to": contract, "data": data}, "latest"])
    exists = bool(out) and out != "0x" and int(out[2:66], 16) == 1
    return {"exists": exists, "network": network, "contract": contract}


class AuditAPI:
    """Retrieve + independently verify agent audits.

    Example:
        att = client.audit.get_attestation("agent-x")
        # don't trust — verify:
        ok = client.audit.verify_anchor_receipt(att)
        incl = client.audit.verify_inclusion_proof(leaf, proof_path, att.merkle_root)
    """

    def __init__(self, client):
        self._client = client

    def get_report(self, agent_id: str) -> dict:
        """Full audit report JSON for an agent (findings, risk, audit_hash, proof ids)."""
        return self._client.gw_get(f"/a2a/agents/{agent_id}/audit-report")

    def get_attestation(self, agent_id: str) -> AuditAttestation:
        """The passport-level 'VERIFIABLY-AUDITED' attestation (lighter than the full report)."""
        data = self._client.gw_get(f"/a2a/agents/{agent_id}/audit-attestation")
        return AuditAttestation(data)

    def list_anchor_receipts(self, limit: int = 20) -> list:
        """Recent state-anchor receipts (root_commitment + witness tx/event ids)."""
        return self._client.gw_get("/a2a/anchor-receipts", params={"limit": limit}).get("entries", [])

    # ---- independent verification (client-side / keyless) ----
    @staticmethod
    def verify_inclusion_proof(leaf_hex: str, proof_path: list, merkle_root_hex: str) -> bool:
        """Verify a single record belongs to the committed set — locally, no server trust."""
        return verify_inclusion(leaf_hex, proof_path, merkle_root_hex)

    @staticmethod
    def verify_anchor_receipt(attestation, network: str = "base-mainnet") -> dict:
        """Confirm an attestation's root is anchored on-chain via a public RPC.

        Accepts an AuditAttestation or a dict with root_commitment + witness contract.
        """
        att = attestation.raw if isinstance(attestation, AuditAttestation) else attestation
        root = att.get("root_commitment")
        witnesses = att.get("witnesses", {})
        contract = (witnesses.get("base_mainnet") or {}).get("contract") if isinstance(
            witnesses.get("base_mainnet"), dict) else att.get("mainnet_contract")
        if not (root and contract):
            return {"exists": False, "error": "no root_commitment / mainnet contract in attestation"}
        return verify_anchor(root, contract, network)
