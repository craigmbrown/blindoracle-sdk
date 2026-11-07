#!/usr/bin/env python3
"""Verify a BlindOracle delegation chain with public documents only.

    pip install cryptography
    python3 verify_chain.py dlg-bf8476c560597afe1f58
    python3 verify_chain.py chain.json --did-doc did.json --no-status     # fully offline
    python3 verify_chain.py vc.json        # one credential (grant, attestation, stop order)

Standalone: one file, stdlib + `cryptography` (Ed25519). It never calls a BlindOracle
verify endpoint. It reads:
  * the chain                 GET https://api.craigmbrown.com/v1/delegations/<id> (or a file)
  * the issuer's key          https://craigmbrown.com/.well-known/did.json
  * the stop/revocation list  https://craigmbrown.com/.well-known/delegation-status.json

Checks, per link: the eddsa-jcs-2022 Data Integrity signature against the did.json key
named by proof.verificationMethod (which must be an assertionMethod of the issuer), and
the validity window at the time the link was issued. Across the chain: links are joined
by credentialSubject.previous.sha256 = sha256(JCS(previous link incl. proof)), the core
links run AgentDelegationRecord -> AgentDelegationAcceptance -> AgentDeliverySeal ->
AgentDelegationClosure (AgentDelegationCountersignature links may sit between them and
must name an earlier accept/deliver link), every link names one delegationId, and the
record's id is not on the signed, unexpired revocation list.

Two proof-configuration forms are accepted, and each link is labelled:
  spec_with_context  W3C vc-di-eddsa (Rec. 15 May 2025) 3.3.1/3.3.2 as written: the proof
                     carries the document @context, and the proof configuration is the
                     whole proof minus proofValue. Issued from 2026-11-07. Any off-the-shelf
                     eddsa-jcs-2022 verifier accepts these.
  legacy_no_context  issued before 2026-11-07: proof config = type, cryptosuite,
                     proofPurpose, verificationMethod, created; publicKeyMultibase and
                     keyAnchor were added after signing, so a spec verifier rejects them.
A proof that carries @context is checked in the spec form only, so a new credential
cannot be downgraded to the legacy check.

Not checked here (the full verifier in the TB repo does these): a person grant embedded
as credentialSubject.directedBy, delegate-wallet EIP-191 / ERC-1271 signatures, and the
on-chain key-anchor fallback for when craigmbrown.com is unreachable.

Exit status: 0 verified, 1 not verified, 2 could not run.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

API = "https://api.craigmbrown.com"
DID_URL = "https://craigmbrown.com/.well-known/did.json"
STATUS_URL = "https://craigmbrown.com/.well-known/delegation-status.json"
UA = "blindoracle-verify-chain/1.0"
CORE = ["AgentDelegationRecord", "AgentDelegationAcceptance", "AgentDeliverySeal",
        "AgentDelegationClosure"]
COUNTERSIGN = "AgentDelegationCountersignature"
LEGACY_FIELDS = ("type", "cryptosuite", "proofPurpose", "verificationMethod", "created")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def jcs(obj) -> bytes:
    """RFC 8785 for these documents: no floats are used, so sorted keys + compact UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def public_key(did_doc: dict, vm_id: str):
    from cryptography.hazmat.primitives.asymmetric import ed25519
    vm = next((m for m in did_doc.get("verificationMethod", []) if m.get("id") == vm_id), None)
    if vm is None:
        raise ValueError(f"{vm_id} not in DID document")
    if vm.get("publicKeyMultibase"):
        raw = b58decode(vm["publicKeyMultibase"][1:])
        raw = raw[2:] if raw[:2] == b"\xed\x01" else raw
    else:
        x = vm["publicKeyJwk"]["x"]
        raw = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


def proof_variant(vc: dict, did_doc: dict):
    """(variant, problem). variant is spec_with_context | legacy_no_context | None."""
    proof = vc.get("proof") or {}
    if proof.get("type") != "DataIntegrityProof" or proof.get("cryptosuite") != "eddsa-jcs-2022":
        return None, "not a DataIntegrityProof / eddsa-jcs-2022 proof"
    issuer = vc.get("issuer")
    issuer = issuer.get("id") if isinstance(issuer, dict) else issuer
    vm = proof.get("verificationMethod", "")
    if did_doc.get("id") != issuer or not vm.startswith(issuer + "#"):
        return None, f"verificationMethod {vm} is not controlled by issuer {issuer}"
    if vm not in (did_doc.get("assertionMethod") or []):
        return None, f"{vm} is not an assertionMethod of {issuer}"
    try:
        pub = public_key(did_doc, vm)
        sig = b58decode(proof["proofValue"][1:])  # multibase 'z' = base58-btc
    except Exception as e:  # noqa: BLE001
        return None, f"unusable key or proofValue: {e}"
    unsecured = {k: v for k, v in vc.items() if k != "proof"}
    options = {k: v for k, v in proof.items() if k != "proofValue"}

    def ok(config: dict, doc: dict) -> bool:
        try:
            pub.verify(sig, hashlib.sha256(jcs(config)).digest() + hashlib.sha256(jcs(doc)).digest())
            return True
        except Exception:  # noqa: BLE001
            return False

    if "@context" in options:  # vc-di-eddsa 3.3.2 step 4
        pc = options["@context"] if isinstance(options["@context"], list) else [options["@context"]]
        dc = unsecured.get("@context")
        dc = dc if isinstance(dc, list) else [dc]
        if dc[:len(pc)] != pc:
            return None, "document @context does not start with proof @context"
        unsecured["@context"] = options["@context"]
        return ("spec_with_context", None) if ok(options, unsecured) else (None, "signature does not verify")
    legacy = {k: proof[k] for k in LEGACY_FIELDS if k in proof}
    if ok(legacy, unsecured) or ok(options, unsecured):
        return "legacy_no_context", None
    return None, "signature does not verify"


def window_problem(vc: dict, at: datetime):
    try:
        if vc.get("validFrom") and at < ts(vc["validFrom"]):
            return "not yet valid"
        if vc.get("validUntil") and at > ts(vc["validUntil"]):
            return "expired"
    except ValueError as e:
        return f"unparseable validity window: {e}"
    return None


def status_of(record: dict, status_doc: dict, did_doc: dict) -> str:
    if "AgentDelegationStatusList" not in (status_doc.get("type") or []):
        return "unknown (not a status list)"
    variant, prob = proof_variant(status_doc, did_doc)
    if variant is None:
        return f"unknown (status list does not verify: {prob})"
    if window_problem(status_doc, datetime.now(timezone.utc)):
        return "unknown (status list is stale)"
    for r in (status_doc.get("credentialSubject") or {}).get("revokedCredentials", []):
        if r.get("credentialId") == record.get("id"):
            return f"revoked by {r.get('order')}: {r.get('reason')}"
    return "active"


def verify_chain(vcs: list, did_doc: dict, status_doc=None) -> dict:
    problems, links = [], []
    sha = {hashlib.sha256(jcs(v)).hexdigest(): v for v in vcs}
    kind = lambda v: (v.get("type") or [None])[-1]  # noqa: E731
    records = [v for v in vcs if kind(v) == CORE[0]]
    if len(records) != 1:
        return {"ok": False, "problems": [f"{len(records)} AgentDelegationRecord links (need 1)"]}
    nxt = {}
    for v in vcs:
        p = ((v.get("credentialSubject") or {}).get("previous") or {}).get("sha256")
        if p:
            if p not in sha:
                problems.append(f"{kind(v)}: previous.sha256 matches no link in this chain")
            if p in nxt:
                problems.append("two links claim the same previous link")
            nxt[p] = v
    walked, cur = [], records[0]
    while cur is not None and len(walked) <= len(vcs):
        walked.append(cur)
        cur = nxt.get(hashlib.sha256(jcs(cur)).hexdigest())
    if len(walked) != len(vcs):
        problems.append(f"{len(vcs) - len(walked)} link(s) not reachable from the record")
    core_i, seen, ids = 0, {}, set()
    for v in walked:
        t, subj = kind(v), v.get("credentialSubject") or {}
        if t == COUNTERSIGN:
            tgt = seen.get((subj.get("countersigns") or {}).get("sha256") or "")
            if tgt is None or kind(tgt) not in CORE[1:3]:
                problems.append(f"{t}: countersigns no earlier accept or deliver link")
        elif core_i < len(CORE) and t == CORE[core_i]:
            core_i += 1
        else:
            problems.append(f"unexpected {t} at core position {core_i + 1}")
        variant, prob = proof_variant(v, did_doc)
        if prob:
            problems.append(f"{t}: {prob}")
        try:
            w = window_problem(v, ts(v["validFrom"]))
        except Exception:  # noqa: BLE001
            w = "no validFrom"
        if w:
            problems.append(f"{t}: {w}")
        ids.add(subj.get("delegationId"))
        seen[hashlib.sha256(jcs(v)).hexdigest()] = v
        links.append({"type": t, "id": v.get("id"), "proof_config_variant": variant})
    if len(ids) != 1 or None in ids:
        problems.append(f"links name {len(ids)} delegation ids")
    status = None
    if status_doc is not None:
        status = status_of(records[0], status_doc, did_doc)
        if status.startswith("revoked"):
            problems.append(f"record {status}")
    stage = CORE[core_i - 1] if core_i else None
    closure = (walked[-1].get("credentialSubject") or {}) if kind(walked[-1]) == CORE[-1] else {}
    return {"ok": not problems, "problems": problems, "delegation_id": next(iter(ids)) if len(ids) == 1 else None,
            "stage": stage, "links": links, "status": status,
            "receipt_matches": closure.get("deliverableMatches") if closure else None}


def verify_one(vc: dict, did_doc: dict, status_doc=None) -> dict:
    """One credential: signature, validity window now, and (with a list) revocation/stop."""
    problems = []
    variant, prob = proof_variant(vc, did_doc)
    if prob:
        problems.append(prob)
    w = window_problem(vc, datetime.now(timezone.utc))
    if w:
        problems.append(w)
    status = None
    if status_doc is not None and vc.get("credentialStatus"):
        status = status_of(vc, status_doc, did_doc)
        agent = (vc.get("credentialSubject") or {}).get("agentName")
        for r in (status_doc.get("credentialSubject") or {}).get("stoppedAgents", []):
            if agent and r.get("agent") == agent and status == "active":
                status = f"stopped by {r.get('order')}: {r.get('reason')}"
        if status.startswith(("revoked", "stopped")):
            problems.append(status)
    return {"ok": not problems, "problems": problems, "type": (vc.get("type") or [None])[-1],
            "id": vc.get("id"), "proof_config_variant": variant, "status": status}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="delegation id (dlg-...) or a JSON file: one credential, "
                    "a list of credentials, or {credentials: [...]}")
    ap.add_argument("--did-doc", help="did.json file instead of fetching it")
    ap.add_argument("--status", help="delegation-status.json file instead of fetching it")
    ap.add_argument("--no-status", action="store_true", help="skip the revocation check")
    ap.add_argument("--api", default=API)
    a = ap.parse_args(argv)
    try:
        if a.src.startswith("dlg-"):
            data = get_json(f"{a.api}/v1/delegations/{a.src}")
        else:
            with open(a.src, encoding="utf-8") as fh:
                data = json.load(fh)
        vcs = data.get("credentials") if isinstance(data, dict) else data
        did_doc = json.load(open(a.did_doc, encoding="utf-8")) if a.did_doc else get_json(DID_URL)
        status_doc = None
        if not a.no_status:
            status_doc = (json.load(open(a.status, encoding="utf-8")) if a.status
                          else get_json(f"{STATUS_URL}?cb={int(time.time())}"))
    except Exception as e:  # noqa: BLE001
        print(f"could not load inputs: {e}", file=sys.stderr)
        return 2
    if isinstance(data, dict) and "proof" in data and "credentials" not in data:
        res = verify_one(data, did_doc, status_doc)  # a single credential (grant, attestation, ...)
    else:
        res = verify_chain(vcs or [], did_doc, status_doc)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
