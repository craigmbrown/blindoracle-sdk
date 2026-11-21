#!/usr/bin/env python3
"""Verify a BlindOracle delegation chain with public documents only.

    pip install cryptography
    python3 verify_chain.py dlg-bf8476c560597afe1f58
    python3 verify_chain.py chain.json --did-doc did.json --no-status     # fully offline
    python3 verify_chain.py vc.json        # one credential (grant, attestation, stop order)
    python3 verify_chain.py verify-order <tx_hash> --order <X-BO-Order value | order.json>

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

Person link (reported, partly checked): a record may embed the person grant that authorized
its delegator (credentialSubject.authorizedBy; records before 2026-11-17 used the key
directedBy for the same thing), and an AgentDelegationDirection link may carry that person's
signature over this delegation id + task hash. `person_link` is "directed", "authorized" or
"none". Checked here with the stdlib: the grant text hashes to grantSha256 and names the
delegator, and the direction's signed text is the exact expected message for this record.
A direction may instead be signed by the person's approval device (approverWallet): the
person wallet named that wallet in a signed link carried on the credential (approverLink).
Checked here: the link text is the expected statement, joins the grant's person wallet to the
approval wallet, was valid when the job was directed, and the direction text names the link.
NOT checked here: the wallet signatures themselves (EIP-191 recovery needs secp256k1; smart
wallets need a Base RPC), so the result says `wallet_signatures_rechecked: false`.

Not checked here (the full verifier in the TB repo does these): delegate-wallet and person-wallet
EIP-191 / ERC-1271 signatures, and the on-chain key-anchor fallback for when craigmbrown.com is
unreachable.

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
DIRECTION = "AgentDelegationDirection"
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
        elif t == DIRECTION:
            pass  # reported by person_link() below
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
    pl = person_link(records[0], [v for v in walked if kind(v) == DIRECTION])
    problems.extend(pl.pop("problems"))
    return {"ok": not problems, "problems": problems, "delegation_id": next(iter(ids)) if len(ids) == 1 else None,
            "stage": stage, "links": links, "status": status,
            "receipt_matches": closure.get("deliverableMatches") if closure else None, **pl}


def person_link(record: dict, directions: list) -> dict:
    """What the chain says about the person behind the delegator, and what was checked here."""
    rs = record.get("credentialSubject") or {}
    key = "authorizedBy" if isinstance(rs.get("authorizedBy"), dict) else "directedBy"
    g = rs.get(key) if isinstance(rs.get(key), dict) else None
    out = {"person_link": "none", "authorized_by": None, "directed_by": None,
           "wallet_signatures_rechecked": False, "problems": []}
    if g is None:
        if directions:
            out["problems"].append(f"{DIRECTION}: the record embeds no person grant")
        return out
    msg = g.get("grantMessage") or ""
    gp = []
    if hashlib.sha256(msg.encode("utf-8")).hexdigest() != g.get("grantSha256"):
        gp.append("grantSha256 does not match grantMessage")
    name = (g.get("agent") or {}).get("name")
    if name and f"Agent: {name} (" not in msg:
        gp.append("grant text does not name this agent")
    wallet = g.get("personWallet") or ""
    if f"Person wallet: {wallet}\n" not in msg:
        gp.append("grant text names a different person wallet")
    out["problems"].extend(f"{key}: {p}" for p in gp)
    out["authorized_by"] = {"person_wallet": wallet, "grant_id": g.get("personGrantId"), "agent": name,
                            "recorded_as": key, "text_checks": "fail" if gp else "pass",
                            "means": "a standing grant authorized the agent; not the person's approval of this job"}
    out["person_link"] = "authorized"
    if len(directions) > 1:
        out["problems"].append(f"{DIRECTION}: more than one direction link")
    if directions:
        s = directions[0].get("credentialSubject") or {}
        expected = (f"BlindOracle job direction\n{rs.get('delegationId')}\n{rs.get('taskSha256')}\n{wallet}\n"
                    "I am the person behind the delegator and I direct this job.")
        dp = []
        approver = s.get("approverWallet")
        link = s.get("approverLink") if isinstance(s.get("approverLink"), dict) else None
        if approver or link:
            # The person wallet named an approval device in a signed link; that device signed this job.
            link = link or {}
            iso = lambda t: datetime.fromtimestamp(int(t or 0), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
            try:
                link_text = ("BlindOracle approval device\n"
                             f"Person wallet: {link.get('personWallet')}\n"
                             f"Approval wallet: {link.get('approvalWallet')}\n"
                             f"Valid: {iso(link.get('notBefore'))} to {iso(link.get('notAfter'))}\n"
                             f"Nonce: {link.get('id')}\n\n"
                             "I hold the person wallet above. I name the approval wallet as my device for approving "
                             "single jobs of agents I have authorized. It cannot grant, spend or change limits. "
                             "Signing moves no funds. I can revoke this at any time by signing a revocation.")
                at = ts(directions[0].get("validFrom")).timestamp()
                in_window = int(link.get("notBefore")) <= at < int(link.get("notAfter"))
            except Exception:  # noqa: BLE001
                link_text, in_window = None, False
            if str(link.get("personWallet") or "").lower() != wallet.lower() or \
                    str(link.get("approvalWallet") or "").lower() != str(approver or "").lower() or not approver:
                dp.append("the approval link does not join this person wallet and approval wallet")
            if link.get("signedMessage") != link_text:
                dp.append("approval link text is not the expected statement")
            if not in_window:
                dp.append("the approval link was not valid when the job was directed")
            expected = (f"BlindOracle job direction\n{rs.get('delegationId')}\n{rs.get('taskSha256')}\n{wallet}\n"
                        f"Approval wallet: {approver}\nApproval link: {link.get('id')}\n"
                        "I am the person behind the delegator and I direct this job from my approval device.")
        if str(s.get("personWallet") or "").lower() != wallet.lower():
            dp.append("signer is not the grant's person wallet")
        if s.get("signedMessage") != expected:
            dp.append("signed text is not the expected direction message for this record")
        if (s.get("directs") or {}).get("sha256") != hashlib.sha256(jcs(record)).hexdigest():
            dp.append("the direction does not name this record")
        out["problems"].extend(f"{DIRECTION}: {p}" for p in dp)
        out["directed_by"] = {"person_wallet": s.get("personWallet"), "signed_at": directions[0].get("validFrom"),
                              "signature_method": s.get("signatureMethod"), "text_checks": "fail" if dp else "pass",
                              **({"approver_wallet": s.get("approverWallet"),
                                  "approver_link_id": (s.get("approverLink") or {}).get("id"),
                                  "human_presence": s.get("humanPresence")} if s.get("approverWallet") else {})}
        if not dp and not gp:
            out["person_link"] = "directed"
    return out


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


# --- verify-order: is an on-chain payment bound to one published order? -------------
# RQ-BO-X402-ORDER-NONCE-01. A BlindOracle buyer on SDK >= 0.12.1 signs the EIP-3009
# nonce as keccak256(JCS(order)). USDC emits AuthorizationUsed(authorizer, nonce) when the
# authorization is used, so the order is checkable from the tx receipt alone.
BASE_RPC = "https://mainnet.base.org"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
       0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
       0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
       0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56],
        [27, 20, 39, 8, 14]]


def keccak256(data: bytes) -> bytes:
    """Pure-python Keccak-256 (Ethereum's hash, not NIST SHA3-256), so this file stays
    stdlib-only for the order check."""
    M = (1 << 64) - 1
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    st = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            st[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        for rnd in range(24):
            c = [st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4] for x in range(5)]
            d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & M)
                 for x in range(5)]
            st = [[st[x][y] ^ d[x] for y in range(5)] for x in range(5)]
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    r = _ROT[x][y]
                    b[y][(2 * x + 3 * y) % 5] = ((st[x][y] << r) | (st[x][y] >> (64 - r))) & M if r else st[x][y]
            st = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)]
                  for x in range(5)]
            st[0][0] ^= _RC[rnd]
    out = b"".join(st[i % 5][i // 5].to_bytes(8, "little") for i in range(rate // 8))
    return out[:32]


AUTH_USED_TOPIC = "0x" + keccak256(b"AuthorizationUsed(address,bytes32)").hex()
TRANSFER_TOPIC = "0x" + keccak256(b"Transfer(address,address,uint256)").hex()


def _order_jcs(order: dict) -> bytes:
    return json.dumps(order, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _load_order(src: str) -> dict:
    """An X-BO-Order header value (b64url(JCS(order)).sig), a JSON file, or inline JSON."""
    try:
        with open(src, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("boOrder", d)
    except (OSError, ValueError):
        pass
    if src.lstrip().startswith("{"):
        d = json.loads(src)
        return d.get("boOrder", d)
    body = src.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def _rpc(url: str, method: str, params: list):
    req = urllib.request.Request(url, data=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())["result"]


def verify_order(receipt: dict, order: dict) -> dict:
    want = "0x" + keccak256(_order_jcs(order)).hex()
    used = [lg for lg in receipt.get("logs") or []
            if (lg.get("address") or "").lower() == USDC_BASE
            and (lg.get("topics") or [None])[0] == AUTH_USED_TOPIC]
    xfers = [lg for lg in receipt.get("logs") or []
             if (lg.get("address") or "").lower() == USDC_BASE
             and (lg.get("topics") or [None])[0] == TRANSFER_TOPIC]
    nonces = [lg["topics"][2].lower() for lg in used if len(lg.get("topics") or []) > 2]
    pay_ok = any("0x" + lg["topics"][2][-40:].lower() == str(order.get("payTo", "")).lower()
                 and int(lg.get("data") or "0x0", 16) == int(order.get("amount") or -1)
                 for lg in xfers if len(lg.get("topics") or []) > 2)
    match = want.lower() in nonces
    return {"ok": bool(match and pay_ok and receipt.get("status") in ("0x1", 1)),
            "order_id": order.get("order_id"), "expected_nonce": want, "onchain_nonces": nonces,
            "nonce_matches_order": match, "transfer_matches_order": pay_ok,
            "tx_status": receipt.get("status"),
            "binds": "this payment pays for this order and no other",
            "does_not_bind": "who submitted the authorization"}


def main_verify_order(argv) -> int:
    ap = argparse.ArgumentParser(prog="verify_chain.py verify-order",
                                 description="Check an on-chain USDC payment is bound to one order.")
    ap.add_argument("tx_hash")
    ap.add_argument("--order", required=True,
                    help="X-BO-Order header value, a JSON file, or inline JSON of the order")
    ap.add_argument("--rpc", default=BASE_RPC)
    ap.add_argument("--receipt", help="tx receipt JSON file instead of calling --rpc")
    a = ap.parse_args(argv)
    try:
        order = _load_order(a.order)
        receipt = (json.load(open(a.receipt, encoding="utf-8")) if a.receipt
                   else _rpc(a.rpc, "eth_getTransactionReceipt", [a.tx_hash]))
        if not receipt:
            raise ValueError("no receipt (tx unknown or pending)")
    except Exception as e:  # noqa: BLE001
        print(f"could not load inputs: {e}", file=sys.stderr)
        return 2
    res = {"tx_hash": a.tx_hash, **verify_order(receipt, order)}
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "verify-order":
        return main_verify_order(argv[1:])
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
