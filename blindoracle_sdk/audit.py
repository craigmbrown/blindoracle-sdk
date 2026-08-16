"""BlindOracle Audit API — verifiable, on-chain-anchored agent audits.

Exposes the verifiable-anchoring layer (shipped 2026-05-23): retrieve an agent's audit report +
attestation, and INDEPENDENTLY verify it — inclusion proofs are checked client-side (don't trust
the server), anchor receipts via any public RPC / Nostr relay.

RQ-BO-AUDIT-SUBJECT-01 adds the missing half: `run()` submits a subject. Everything here
was previously read-only, so a buyer could read an audit that existed but could not cause
one — and BlindOracle's subject resolver only looked at its own filesystem, so an external
agent could never be audited at all.

`run()` collects the subject on YOUR machine. The default sends a {path: sha256} manifest
and your declared tool line — **not** file contents. That is enough for the capability
scorer, and it means your source never leaves your environment.
"""
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

from blindoracle_sdk._version import user_agent as _user_agent

# public Base RPCs for keyless anchor read-back (fallback chain)
_BASE_MAINNET_RPC = ["https://mainnet.base.org", "https://base.llamarpc.com"]
_BASE_SEPOLIA_RPC = ["https://sepolia.base.org"]
# keccak256("verifyAnchor(bytes32)")[:4] — ProofAnchor on Base mainnet, which is what
# anchors are written to and what the published verification instructions name.
# NOTE: the two anchor contracts expose DISJOINT interfaces, so selector and address
# travel together. Pointing this selector at AuditAnchor (or vice versa) silently
# returns a wrong answer rather than erroring.
#   ProofAnchor 0x62dbc5bB…  verifyAnchor(bytes32) = 0xf32bd282   <- default
#   AuditAnchor 0x3Dc9AF8d…  isAnchored(bytes32)   = 0x4f0b5801
_VERIFY_ANCHOR_SELECTOR = "0xf32bd282"
_IS_ANCHORED_SELECTOR = "0x4f0b5801"

# Base-mainnet deployments. A buyer can hardcode these and check any attestation
# without asking BlindOracle for anything.
PROOF_ANCHOR_BASE_MAINNET = "0x62dbc5bBB356388ce65f0dB591d0aa7B334E8E41"
AUDIT_ANCHOR_BASE_MAINNET = "0x3Dc9AF8dA1056913f6b9d839dc5C73E7fbc5d3D0"
_SELECTOR_FOR = {
    PROOF_ANCHOR_BASE_MAINNET.lower(): _VERIFY_ANCHOR_SELECTOR,
    AUDIT_ANCHOR_BASE_MAINNET.lower(): _IS_ANCHORED_SELECTOR,
}

AUDIT_SKU = "security.massat-audit"
ENTERPRISE_AUDIT_SKU = "security.enterprise-audit"

# Caps so a mis-pointed collect() can never stream a whole repo over the wire.
MAX_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024

# Redaction runs INSIDE the SDK, on the buyer's machine, before anything is sent.
# It is deliberately self-contained: the SDK is installed standalone and cannot import
# BlindOracle's server-side scanner. Treat it as a second line of defence — the first
# is that `send_contents` defaults to False.
_SECRET_PATTERNS = [
    # Most specific first: `sk-ant-...` also matches the generic `sk-` shape, so a
    # generic-first ordering redacts correctly but reports the wrong provider.
    (re.compile(r"(?i)\b(sk-ant-[A-Za-z0-9_\-]{16,})"), "ANTHROPIC_KEY"),
    (re.compile(r"(?i)\b(sk-[A-Za-z0-9_\-]{16,})"), "OPENAI_STYLE_KEY"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})"), "GITHUB_TOKEN"),
    (re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{10,})"), "SLACK_TOKEN"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "AWS_ACCESS_KEY_ID"),
    (re.compile(r"\b(AIza[0-9A-Za-z_\-]{30,})"), "GOOGLE_API_KEY"),
    (re.compile(r"\b(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"), "JWT"),
    (re.compile(r"\b(0x[a-fA-F0-9]{64})\b"), "HEX_PRIVATE_KEY"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL), "PEM_PRIVATE_KEY"),
    (re.compile(r"(?im)^([A-Z][A-Z0-9_]{2,}(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)S?)"
                r"\s*[:=]\s*(?!\s*$)\S+"), "ENV_ASSIGNMENT"),
]


def redact(text: str) -> tuple:
    """Return (redacted_text, [labels_found]). Never returns the secret value."""
    found = []
    out = text
    for rx, label in _SECRET_PATTERNS:
        if rx.search(out):
            found.append(label)
            if label == "ENV_ASSIGNMENT":
                out = rx.sub(lambda m: f"{m.group(1)}=[REDACTED:{label}]", out)
            else:
                out = rx.sub(f"[REDACTED:{label}]", out)
    return out, sorted(set(found))


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
                "content-type": "application/json", "User-Agent": _user_agent()})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode()).get("result")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"all RPCs failed: {last}")


def verify_anchor(root_commitment_hex: str, contract: str = PROOF_ANCHOR_BASE_MAINNET,
                  network: str = "base-mainnet") -> dict:
    """Independently confirm a state-anchor root on a public RPC. No keys, no spend.

    Defaults to ProofAnchor on Base mainnet — the contract anchors are written to and
    the one the published verification instructions name — so a buyer holding only a
    root commitment can verify without being told where to look. The selector is chosen
    from the contract address, because ProofAnchor.verifyAnchor and
    AuditAnchor.isAnchored are different functions and a mismatched pair returns a
    wrong answer rather than an error.
    """
    urls = _BASE_MAINNET_RPC if network == "base-mainnet" else _BASE_SEPOLIA_RPC
    selector = _SELECTOR_FOR.get(str(contract).lower(), _VERIFY_ANCHOR_SELECTOR)
    data = selector + root_commitment_hex.removeprefix("0x").rjust(64, "0")
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

    # ---- submit a subject (RQ-BO-AUDIT-SUBJECT-01) ----
    @staticmethod
    def collect(paths: Iterable, declared_tools: str = "", capabilities: Optional[list] = None,
                send_contents: bool = False, redact_contents: bool = True) -> dict:
        """Build an audit subject payload from local files — runs entirely on your machine.

        Returns the exact dict that will be transmitted, so you can inspect it before
        sending. `run()` calls this for you; call it directly when you want to see or
        edit the payload first.

        paths           files/dirs describing the agent (manifest, system prompt, tool config)
        declared_tools  the agent's tool line, e.g. "Bash, WebFetch, Write"
        send_contents   False (default) sends ONLY {path: sha256} hashes. Your source
                        does not leave this machine. True sends file text as well, which
                        upgrades the audit's evidence class from notarized to observed.
        redact_contents strip recognised secrets from contents before transmit (default on)

        Hashes are of the ORIGINAL bytes, so the digest you can recompute offline is
        stable regardless of redaction.
        """
        files = []
        for p in paths or []:
            p = Path(p).expanduser()
            if p.is_dir():
                files.extend(sorted(f for f in p.rglob("*") if f.is_file()))
            elif p.is_file():
                files.append(p)
        manifest, artifacts, redactions, skipped = {}, {}, [], []
        total = 0
        for f in files[:MAX_FILES]:
            try:
                raw = f.read_bytes()
            except Exception as e:  # noqa: BLE001
                skipped.append({"path": str(f), "reason": f"unreadable:{type(e).__name__}"})
                continue
            if len(raw) > MAX_FILE_BYTES:
                skipped.append({"path": str(f), "reason": "over_max_file_bytes"})
                continue
            if total + len(raw) > MAX_TOTAL_BYTES:
                skipped.append({"path": str(f), "reason": "over_max_total_bytes"})
                continue
            total += len(raw)
            rel = f.name
            # hash the ORIGINAL bytes — this is what binds the version
            manifest[rel] = hashlib.sha256(raw).hexdigest()
            if send_contents:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    skipped.append({"path": str(f), "reason": "not_utf8_text"})
                    continue
                if redact_contents:
                    text, found = redact(text)
                    if found:
                        redactions.append({"path": rel, "redacted": found})
                artifacts[rel] = text
        if len(files) > MAX_FILES:
            skipped.append({"path": f"+{len(files) - MAX_FILES} more", "reason": "over_max_files"})
        payload = {"manifest": manifest}
        if artifacts:
            payload["artifacts"] = artifacts
        if declared_tools:
            payload["declared_tools"] = declared_tools
        if capabilities:
            payload["capabilities"] = list(capabilities)
        payload["_local"] = {"files_collected": len(manifest), "sent_contents": bool(artifacts),
                             "redactions": redactions, "skipped": skipped}
        return payload

    @staticmethod
    def subject_digest(payload: dict) -> Optional[str]:
        """Recompute the subject_digest locally — confirms which version an audit covers.

        Verify BlindOracle's binding without trusting it: this must equal the
        `subject_digest` on the returned attestation.
        """
        manifest = dict(payload.get("manifest") or {})
        for rel, content in (payload.get("artifacts") or {}).items():
            manifest.setdefault(rel, hashlib.sha256(content.encode("utf-8")).hexdigest())
        if not manifest:
            return None
        canon = json.dumps(sorted(manifest.items()), separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()

    def run(self, agent: str, paths: Optional[Iterable] = None, declared_tools: str = "",
            capabilities: Optional[list] = None, send_contents: bool = False,
            redact_contents: bool = True, scope: str = "full", anchor: bool = False,
            enterprise: bool = False, subject: Optional[dict] = None) -> dict:
        """Audit an agent by submitting a locally-collected subject. Returns the deliverable.

        Example:
            bo.audit.run(agent="my-agent", paths=["agents/my-agent.md"])

        The audit is version-bound: check `subject_digest` against
        `AuditAPI.subject_digest(payload)` computed on your own machine.

        A subject with no auditable surface returns status `insufficient_subject` with
        `risk_score: None` — that is N/A, NOT a low score, and it is not charged.
        """
        payload = subject if subject is not None else self.collect(
            paths or [], declared_tools=declared_tools, capabilities=capabilities,
            send_contents=send_contents, redact_contents=redact_contents)
        local = payload.pop("_local", {}) if isinstance(payload, dict) else {}
        body = {"target": agent, "scope": scope, "anchor": bool(anchor), "subject": payload}
        sku = ENTERPRISE_AUDIT_SKU if enterprise else AUDIT_SKU
        result = self._client.post(f"/v1/services/{sku}", body=body)
        if isinstance(result, dict):
            result["_local"] = local
            expected = self.subject_digest(payload)
            got = result.get("subject_digest")
            result["_subject_digest_verified"] = bool(expected and got and expected == got)
            result["_subject_digest_local"] = expected
        return result

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
    def verify_anchor_receipt(attestation, network: Optional[str] = None) -> dict:
        """Confirm an attestation's root is anchored on-chain via a public RPC.

        Accepts an AuditAttestation or a dict with root_commitment + witness contract.

        The network is read from the attestation's own witness block rather than
        assumed. This previously defaulted to base-mainnet and looked only for a
        `base_mainnet` witness, while the audit orchestrator anchors under
        `base_sepolia` — so verification returned "no root_commitment / mainnet
        contract in attestation" for every genuinely anchored audit. Pass `network`
        explicitly only to override what the attestation says.
        """
        att = attestation.raw if isinstance(attestation, AuditAttestation) else attestation
        root = att.get("root_commitment")
        witnesses = att.get("witnesses") or {}
        # witness key -> RPC network id, most-trusted first
        for key, net in (("base_mainnet", "base-mainnet"), ("base_sepolia", "base-sepolia")):
            w = witnesses.get(key)
            contract = w.get("contract") if isinstance(w, dict) else None
            if contract:
                resolved = network or net
                out = verify_anchor(root, contract, resolved) if root else {
                    "exists": False, "error": "no root_commitment in attestation"}
                out["witness"] = key
                # A testnet anchor is not the same assurance as a mainnet one. Say so
                # rather than letting "exists: true" imply mainnet finality.
                out["assurance"] = ("mainnet" if resolved == "base-mainnet"
                                    else "testnet — NOT mainnet finality")
                return out
        contract = att.get("mainnet_contract")
        if root and contract:
            out = verify_anchor(root, contract, network or "base-mainnet")
            out["witness"] = "mainnet_contract"
            return out
        return {"exists": False,
                "error": "attestation carries no anchor witness (was it anchored?)",
                "anchored": False}
