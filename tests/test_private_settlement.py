import json
import pytest

from blindoracle_sdk import private_settlement as ps


def test_keygen_and_roundtrip(tmp_path):
    k = ps.generate_auditor_key(tmp_path / "auditor.key")
    assert k["public"].startswith("age1")
    # public derivable from the secret file
    assert ps.public_from_key_file(k["path"]) == k["public"]
    sealed = ps.seal({"buyer": "A", "seller": "B", "amount_usd": 0.23}, k["public"])
    led = tmp_path / "sealed.jsonl"
    led.write_text(json.dumps(sealed) + "\n")
    rows = ps.audit(led, k["path"])
    assert rows[0]["decrypted"] and rows[0]["commitment_verified"]
    assert rows[0]["artifact"]["amount_usd"] == 0.23


def test_wrong_key_cannot_read_or_forge(tmp_path):
    right = ps.generate_auditor_key(tmp_path / "right.key")
    wrong = ps.generate_auditor_key(tmp_path / "wrong.key")
    led = tmp_path / "sealed.jsonl"
    led.write_text(json.dumps(ps.seal({"x": 1}, right["public"])) + "\n")
    rows = ps.audit(led, wrong["path"])
    assert not rows[0]["decrypted"]
    assert rows[0]["error"] == "InvalidTag"


def test_commitment_hides_contents(tmp_path):
    k = ps.generate_auditor_key(tmp_path / "k.key")
    a = ps.seal({"x": 1}, k["public"])
    b = ps.seal({"x": 2}, k["public"])
    assert a["public"]["commitment"] != b["public"]["commitment"]


def test_seal_to_multiple_via_separate_records(tmp_path):
    # two standing auditors: seal a record to each pubkey; each audits with own key
    a1 = ps.generate_auditor_key(tmp_path / "a1.key")
    a2 = ps.generate_auditor_key(tmp_path / "a2.key")
    art = {"deal": "confidential"}
    led = tmp_path / "sealed.jsonl"
    with led.open("w") as f:
        f.write(json.dumps(ps.seal(art, a1["public"])) + "\n")
        f.write(json.dumps(ps.seal(art, a2["public"])) + "\n")
    # a1 reads row 0, a2 reads row 1
    assert ps.audit(led, a1["path"])[0]["decrypted"]
    assert ps.audit(led, a2["path"])[1]["decrypted"]
