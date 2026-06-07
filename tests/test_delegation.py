"""Tests for blindoracle_sdk.delegation — the agent-auditability helper."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from blindoracle_sdk.delegation import (  # noqa: E402
    DelegationLog,
    verify_signature,
    delegation_signature,
    DELEGATION_KIND,
)


@pytest.fixture
def log(tmp_path):
    return DelegationLog(tmp_path / "deleg.jsonl")


def test_emit_writes_kind_30014(log):
    rec = log.emit("operator-root", "Agent A")
    assert rec["kind"] == DELEGATION_KIND
    assert rec["proof_type"] == "ProofOfDelegation"
    assert rec["delegator"] == "operator-root"
    assert rec["event_id"] and rec["signature"]
    assert rec["prev_hash"] == ""  # root has empty prev_hash


def test_chain_links_prev_hash(log):
    r1 = log.emit("operator-root", "Agent A")
    r2 = log.emit("agent-A", "Agent B")
    assert r2["prev_hash"] == r1["event_id"]


def test_verify_intact_chain(log):
    log.emit("operator-root", "Agent A")
    log.emit("agent-A", "Agent B")
    log.emit("agent-B", "Agent C")
    res = log.verify()
    assert res["ok"] is True
    assert res["total_records"] == 3
    assert res["chained_records"] == 3
    assert res["first_break_at"] is None


def test_signature_roundtrip(log):
    rec = log.emit("operator-root", "Agent A")
    assert verify_signature(rec) is True
    rec2 = dict(rec)
    rec2["delegate"] = "Agent EVIL"
    assert verify_signature(rec2) is False


def test_field_tamper_detected(log):
    log.emit("operator-root", "Agent A")
    log.emit("agent-A", "Agent B")
    rows = [json.loads(l) for l in log.path.read_text().splitlines()]
    rows[1]["scope"] = "TAMPERED"  # change a field without recomputing event_id
    log.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    res = log.verify()
    assert res["ok"] is False
    assert res["first_break_at"] == 1


def test_reorder_breaks_chain(log):
    log.emit("operator-root", "Agent A")
    log.emit("agent-A", "Agent B")
    log.emit("agent-B", "Agent C")
    rows = [json.loads(l) for l in log.path.read_text().splitlines()]
    rows[1], rows[2] = rows[2], rows[1]  # swap records
    log.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert log.verify()["ok"] is False


def test_shared_proofdb_kind_filter(log):
    log.emit("operator-root", "Agent A")
    log.emit("agent-A", "Agent B")
    # a foreign proof kind co-habits the log (badges / onboarding)
    with open(log.path, "a") as f:
        f.write(json.dumps({"kind": 30016, "proof_type": "ProofOfBadge"}) + "\n")
    res = log.verify()
    assert res["ok"] is True
    assert res["total_records"] == 2  # foreign kind ignored


def test_chain_to_root(log):
    log.emit("operator-root", "Agent A")
    log.emit("agent-A", "Agent B")
    leaf = log.emit("agent-B", "Agent C")
    chain = log.chain_to_root(leaf["event_id"])
    assert len(chain) == 3
    assert chain[0]["delegator"] == "agent-B"      # leaf
    assert chain[-1]["delegator"] == "operator-root"  # root


def test_deterministic_signature():
    a = delegation_signature("op", "Agent A", 1000)
    b = delegation_signature("op", "Agent A", 1000)
    assert a == b
    assert a != delegation_signature("op", "Agent A", 1001)


def test_empty_log_verifies(log):
    res = log.verify()
    assert res["ok"] is True
    assert res["total_records"] == 0


# REQ-RQ171-005: SDK verify_associativity parity

def test_verify_associativity_intact(log):
    """Clean narrowing chain passes associativity + monotone checks (REQ-RQ171-005)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    log.emit("operator-root", "Agent A", scope="read write execute")
    log.emit("agent-A",       "Agent B", scope="read write")
    leaf = log.emit("agent-B", "Agent C", scope="read")
    result = log.verify_associativity(leaf["event_id"])
    assert result["ok"] is True
    assert result["associative"] is True
    assert result["monotone"] is True
    assert result["violations"] == []
    assert set(result["effective_authority"]["scope"]) == {"read"}


def test_detects_escalation(log):
    """Child that adds scope token is flagged as scope_expansion (REQ-RQ171-005)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    log.emit("operator-root", "Agent A", scope="read")
    leaf = log.emit("agent-A", "Agent B", scope="read write")  # 'write' not in parent
    result = log.verify_associativity(leaf["event_id"])
    assert any(v["type"] == "scope_expansion" for v in result["violations"])
    # advisory by default — ok stays True
    assert result["ok"] is True
