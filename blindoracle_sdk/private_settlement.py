"""BlindOracle SDK — Private Settlement: get keys, seal, and audit private jobs.

A *private* BlindOracle job seals its terms + deliverable (X25519 + ChaCha20-
Poly1305, the `age` primitives) to an auditor's key and anchors only a
contents-hiding commitment on-chain. This module lets an agent or a human:

  1. generate_auditor_key()  — make an age keypair (private stays local, public
                               is what you register as an authorized auditor)
  2. seal()                  — encrypt a settlement to one or more auditor pubkeys
  3. audit()                 — decrypt + verify every sealed settlement with a key

Confidentiality rests entirely on the age PRIVATE key. The sealed blob is safe to
store or even publish; only a holder of a matching private key can read it, and a
wrong key can neither read nor forge (ChaCha20-Poly1305 InvalidTag).

This feature needs the `cryptography` package:  pip install "blindoracle-sdk[privacy]"
The rest of the SDK stays zero-dependency.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]


def _require_crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import (  # noqa: F401
            X25519PrivateKey, X25519PublicKey)
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305  # noqa: F401
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: F401
        from cryptography.hazmat.primitives import hashes  # noqa: F401
        return True
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Private settlement needs the 'cryptography' package. "
            'Install with:  pip install "blindoracle-sdk[privacy]"') from e


# ---------------------------------------------------------------- bech32 (age)
def _polymod(values):
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= _GEN[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert(data, frm, to, pad=True):
    acc = bits = 0
    out = []
    maxv = (1 << to) - 1
    for b in data:
        acc = (acc << frm) | b
        bits += frm
        while bits >= to:
            bits -= to
            out.append((acc >> bits) & maxv)
    if pad and bits:
        out.append((acc << (to - bits)) & maxv)
    return out


def _bech32_encode(hrp: str, data: bytes) -> str:
    vals = _convert(list(data), 8, 5)
    poly = _polymod(_hrp_expand(hrp) + vals + [0] * 6) ^ 1
    cs = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_B32[d] for d in vals + cs)


def _bech32_decode(s: str) -> bytes:
    s2 = s.lower()
    pos = s2.rfind("1")
    data = [_B32.index(c) for c in s2[pos + 1:]]
    return bytes(_convert(data[:-6], 5, 8, pad=False))


# ---------------------------------------------------------------- key lifecycle
def generate_auditor_key(path: str | Path) -> dict:
    """Generate an age keypair. Writes the SECRET key to `path` (mode 0600) and
    returns {public, path}. Register `public` (age1…) as an authorized auditor;
    keep `path` private and backed up — losing it makes sealed jobs unrecoverable.
    """
    _require_crypto()
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    sk = X25519PrivateKey.generate()
    secret = _bech32_encode("AGE-SECRET-KEY-", sk.private_bytes_raw()).upper()
    public = _bech32_encode("age", sk.public_key().public_bytes_raw())
    p = Path(path)
    p.write_text(f"# BlindOracle auditor key — KEEP SECRET\n# public: {public}\n{secret}\n")
    os.chmod(p, 0o600)
    return {"public": public, "path": str(p)}


def public_from_key_file(path: str | Path) -> str:
    """Derive the age public recipient (age1…) from a secret key file."""
    _require_crypto()
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    for line in Path(path).read_text().splitlines():
        if line.strip().upper().startswith("AGE-SECRET-KEY-"):
            sk = X25519PrivateKey.from_private_bytes(_bech32_decode(line.strip()))
            return _bech32_encode("age", sk.public_key().public_bytes_raw())
    raise ValueError("no AGE-SECRET-KEY line in key file")


# ---------------------------------------------------------------- seal / audit
def _kdf(shared: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"bo-private-settlement").derive(shared)


def commitment(raw: bytes, salt: bytes | None = None) -> dict:
    salt = salt or os.urandom(16)
    return {"commitment": "0x" + hashlib.sha3_256(raw + salt).hexdigest(), "salt": "0x" + salt.hex()}


def seal(artifact: dict, recipient_pub: str) -> dict:
    """Encrypt `artifact` to an age public key. Returns {public: commitment, sealed}."""
    _require_crypto()
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    raw = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    pub = X25519PublicKey.from_public_bytes(_bech32_decode(recipient_pub))
    eph = X25519PrivateKey.generate()
    key = _kdf(eph.exchange(pub))
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, raw, b"bo-private")
    return {"public": commitment(raw),
            "sealed": {"eph_pub": eph.public_key().public_bytes_raw().hex(),
                       "nonce": nonce.hex(), "ciphertext": ct.hex(),
                       "alg": "x25519+chacha20poly1305"}}


def _unseal(sealed: dict, key_file: str | Path) -> dict:
    _require_crypto()
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    sk = None
    for line in Path(key_file).read_text().splitlines():
        if line.strip().upper().startswith("AGE-SECRET-KEY-"):
            sk = X25519PrivateKey.from_private_bytes(_bech32_decode(line.strip()))
            break
    if sk is None:
        raise ValueError("no AGE-SECRET-KEY in key file")
    eph = X25519PublicKey.from_public_bytes(bytes.fromhex(sealed["eph_pub"]))
    key = _kdf(sk.exchange(eph))
    raw = ChaCha20Poly1305(key).decrypt(bytes.fromhex(sealed["nonce"]),
                                        bytes.fromhex(sealed["ciphertext"]), b"bo-private")
    return json.loads(raw)


def _verify(artifact: dict, public: dict) -> bool:
    raw = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    salt = bytes.fromhex(public["salt"][2:])
    return ("0x" + hashlib.sha3_256(raw + salt).hexdigest()) == public["commitment"]


def audit(ledger: str | Path, key_file: str | Path) -> list[dict]:
    """Decrypt + verify every sealed settlement in `ledger` (JSONL of seal() output)
    using `key_file`. Each row: {commitment, decrypted, commitment_verified, artifact|error}.
    A wrong key yields decrypted=False with error='InvalidTag' — it cannot read or forge.
    """
    rows = []
    for line in Path(ledger).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        row = {"commitment": rec["public"]["commitment"], "decrypted": False,
               "commitment_verified": False}
        try:
            art = _unseal(rec["sealed"], key_file)
            row.update(decrypted=True, commitment_verified=_verify(art, rec["public"]), artifact=art)
        except Exception as e:  # wrong key / tampered blob
            row["error"] = type(e).__name__
        rows.append(row)
    return rows
