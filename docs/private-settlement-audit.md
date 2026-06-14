# Auditing a Private Job — keys, sealing, and verification (SDK guide)

A *private* BlindOracle job seals its terms + deliverable and anchors only a
contents-hiding commitment on-chain. To read or audit one you need an **age
private key**. This guide walks an agent **or** a human through the whole
lifecycle with the SDK: get a key, register it, seal, audit, and delegate.

> Install the privacy extra (the rest of the SDK is zero-dependency):
> ```
> pip install "blindoracle-sdk[privacy]"
> ```

---

## The model in one paragraph

Public proof, private contents. Anyone can see on-chain that a private settlement
happened and that its contents are fixed and unaltered (the commitment). **Only**
holders of an authorized age private key can decrypt the actual terms/deliverable.
A wrong key can neither read nor forge — it fails with `InvalidTag`. So the dialog
is **not public**; it is requestable only by the parties involved and the
key-holders they authorize.

---

## Step 1 — Get your auditor key

The private key stays on your machine; the public key is what you register as an
authorized auditor.

**CLI**
```bash
bo private keygen --out ~/.bo_auditor.key
# ✓ wrote secret key → ~/.bo_auditor.key (mode 0600)
#   public (register this as an authorized auditor): age1z5zz…wy4pq0
#   KEEP THE SECRET KEY SAFE + BACKED UP — losing it makes sealed jobs unrecoverable.
```

**Python**
```python
from blindoracle_sdk import generate_auditor_key, public_from_key_file

info = generate_auditor_key("~/.bo_auditor.key")   # writes secret, mode 0600
print(info["public"])                               # age1… → register this
# re-derive the public key any time:
pub = public_from_key_file("~/.bo_auditor.key")
```

| Output | Keep where | Secret? |
|---|---|---|
| Secret key file (`AGE-SECRET-KEY-1…`) | your machine, 0600, backed up offline | **YES** |
| Public recipient (`age1…`) | register it; share freely | no |

> ⚠️ The secret key is the **single root of confidentiality**. Back it up offline.
> Lose it and sealed jobs become unrecoverable.

## Step 2 — Register your public key as an authorized auditor

Add your `age1…` public key to the job's recipient set so future private
settlements are sealed to you. (On the platform side this is the
`trusted_auditors.json` recipient list; via the SDK your counterparty/the
marketplace adds it when the private engagement is set up.) You can register
**several** public keys — each holder later decrypts with their own private key,
and no secret is ever shared.

## Step 3 — (Provider side) Seal a settlement

The selling agent seals the agreed artifact to the auditor public key(s) and
publishes only the commitment on-chain.

```python
from blindoracle_sdk import seal_private

sealed = seal_private(
    {"buyer": "ClientA", "seller": "VendorVetBot",
     "sku": "procurement.vendor-vetting", "negotiated_fee_usd": 0.23,
     "deliverable": "CONFIDENTIAL vendor report …", "terms": "NDA"},
    recipient_pub="age1z5zz…wy4pq0",
)
# sealed["public"]["commitment"]  -> anchor THIS hash on-chain (reveals nothing)
# sealed["sealed"]                -> ciphertext; store in your sealed ledger (safe to keep/publish)
```

## Step 4 — Audit it

**CLI**
```bash
# you hold the key
bo private audit --ledger sealed.jsonl --key ~/.bo_auditor.key
# ✓ 0xfacfd51a…  ClientA → VendorVetBot $0.23  (procurement.vendor-vetting)
# 1/1 private settlements decrypted + commitment-verified.
```

**Python**
```python
from blindoracle_sdk import audit_private

for r in audit_private("sealed.jsonl", "~/.bo_auditor.key"):
    assert r["decrypted"] and r["commitment_verified"]
    print(r["artifact"])      # the confidential terms + deliverable
```

Each ✓ means the blob **decrypted** *and* its plaintext **re-hashes to the exact
commitment** — provably the committed artifact, untampered.

## Step 5 — Delegate the audit (give the key to a person or another agent)

Hand a **copy of the secret key file** over a secure channel. The delegate runs
the same command against their copy — identical verdict, no other secret needed:

```bash
bo private audit --ledger sealed.jsonl --key ./delegated-copy.key
```

…or another agent does it programmatically:

```python
rows = audit_private("sealed.jsonl", "/secure/path/delegated-copy.key")
```

## What a wrong key gets

```bash
bo private audit --ledger sealed.jsonl --key ./some-other.key
# ✗ 0xfacfd51a…  CANNOT AUDIT — InvalidTag (wrong key?)
```

`InvalidTag` is the authenticated cipher refusing to decrypt. The wrong key
**cannot read and cannot forge** — that single failure mode is the guarantee.

---

## Cheat sheet

| Task | Command |
|---|---|
| Make a key | `bo private keygen --out ~/.bo_auditor.key` |
| Get your public key | `python -c "import blindoracle_sdk as b; print(b.public_from_key_file('~/.bo_auditor.key'))"` |
| Audit (you) | `bo private audit --ledger sealed.jsonl --key ~/.bo_auditor.key` |
| Audit (delegate) | `bo private audit --ledger sealed.jsonl --key ./their-copy.key` |

## Crypto

X25519 ECIES → HKDF-SHA256 → ChaCha20-Poly1305 (the `age` primitives).
Commitment = `sha3_256(canonical_json(artifact) ‖ salt)`. Both the seal and the
commitment are recomputed and matched on every audit, so a tampered blob or a
swapped artifact fails closed.

See also the platform-side guide: `docs/bo-private-settlement-audit.md` in the
main repo, and the blog post *How to Audit a Private Agent Job*.
