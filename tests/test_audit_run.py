"""RQ-BO-AUDIT-SUBJECT-01 — SDK-side subject collection.

The SDK is the collector; BlindOracle is the analyst. These tests lock the properties
that make that split safe for the buyer:

  * manifest-only by default — source does not leave the buyer's machine
  * recognised secrets are stripped before transmit when contents are opted in
  * subject_digest is computed from ORIGINAL bytes, so the buyer can verify offline
    which version an audit covers, and redaction cannot change it
"""
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from blindoracle_sdk.audit import AuditAPI, redact

MANIFEST_MD = "---\nname: my-agent\ntools: Bash, WebFetch\n---\nbody text\n"
SECRET_FILE = (
    "ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnop1234567890\n"
    "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n"
    "HARMLESS=1\n"
)


@pytest.fixture()
def agent_dir():
    d = Path(tempfile.mkdtemp())
    (d / "my-agent.md").write_text(MANIFEST_MD)
    (d / "config.env").write_text(SECRET_FILE)
    return d


# ------------------------------------------------------------- privacy defaults

def test_contents_are_not_transmitted_by_default(agent_dir):
    payload = AuditAPI.collect([agent_dir])
    assert "artifacts" not in payload
    assert payload["manifest"], "hashes must still be sent"
    assert MANIFEST_MD not in json.dumps(payload)


def test_opt_in_contents_are_redacted_before_transmit(agent_dir):
    payload = AuditAPI.collect([agent_dir], send_contents=True)
    blob = json.dumps(payload)
    assert "sk-ant-abcdefghijklmnop1234567890" not in blob
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in blob
    assert payload["_local"]["redactions"], "redaction must be reported, not silent"


def test_redaction_can_be_disabled_only_explicitly(agent_dir):
    payload = AuditAPI.collect([agent_dir], send_contents=True, redact_contents=False)
    assert "sk-ant-abcdefghijklmnop1234567890" in json.dumps(payload)


@pytest.mark.parametrize("text,label", [
    ("key=sk-ant-abcdefghijklmnopqrst", "ANTHROPIC_KEY"),
    ("t=ghp_ABCDEFGHIJKLMNOPQRSTUV12345", "GITHUB_TOKEN"),
    ("a=AKIAIOSFODNN7EXAMPLE", "AWS_ACCESS_KEY_ID"),
    ("s=xoxb-123456789012-abcdefghijkl", "SLACK_TOKEN"),
    ("PRIVATE_KEY=0x" + "a" * 64, "HEX_PRIVATE_KEY"),
    ("MY_API_SECRET=hunter2hunter2", "ENV_ASSIGNMENT"),
])
def test_redactor_catches_common_credential_shapes(text, label):
    out, found = redact(text)
    assert label in found
    assert "[REDACTED:" in out


def test_redactor_leaves_ordinary_text_alone():
    text = "This agent uses WebFetch and writes to data/out.json. No secrets here."
    out, found = redact(text)
    assert out == text and found == []


# --------------------------------------------------------------- version binding

def test_subject_digest_matches_an_independent_calculation(agent_dir):
    payload = AuditAPI.collect([agent_dir])
    manifest = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(agent_dir.iterdir())}
    canon = json.dumps(sorted(manifest.items()), separators=(",", ":"))
    assert AuditAPI.subject_digest(payload) == hashlib.sha256(canon.encode()).hexdigest()


def test_digest_is_unchanged_by_redaction(agent_dir):
    """Hashes bind the ORIGINAL bytes — otherwise redaction would silently change
    which version the audit claims to cover."""
    a = AuditAPI.subject_digest(AuditAPI.collect([agent_dir]))
    b = AuditAPI.subject_digest(AuditAPI.collect([agent_dir], send_contents=True))
    c = AuditAPI.subject_digest(
        AuditAPI.collect([agent_dir], send_contents=True, redact_contents=False))
    assert a == b == c


def test_digest_changes_when_the_agent_changes(agent_dir):
    before = AuditAPI.subject_digest(AuditAPI.collect([agent_dir]))
    (agent_dir / "my-agent.md").write_text(MANIFEST_MD + "\nnew capability\n")
    assert AuditAPI.subject_digest(AuditAPI.collect([agent_dir])) != before


def test_digest_is_none_for_an_empty_subject():
    assert AuditAPI.subject_digest({}) is None
    assert AuditAPI.subject_digest({"declared_tools": "Bash"}) is None


# ---------------------------------------------------------------------- limits

def test_oversize_files_are_skipped_and_reported():
    d = Path(tempfile.mkdtemp())
    (d / "huge.md").write_text("x" * (300 * 1024))
    (d / "small.md").write_text(MANIFEST_MD)
    payload = AuditAPI.collect([d])
    assert "huge.md" not in payload["manifest"]
    assert "small.md" in payload["manifest"]
    assert any(s["reason"] == "over_max_file_bytes" for s in payload["_local"]["skipped"])


def test_unreadable_and_missing_paths_do_not_raise():
    payload = AuditAPI.collect(["/nonexistent/path/xyz"])
    assert payload["manifest"] == {}


def test_declared_only_subject_needs_no_files():
    payload = AuditAPI.collect([], declared_tools="Bash, WebFetch")
    assert payload["declared_tools"] == "Bash, WebFetch"
    assert payload["manifest"] == {}


# ------------------------------------------------------------- request shaping

class _FakeClient:
    """Captures what run() would POST, without touching the network."""
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply or {}

    def post(self, path, body=None, extra_headers=None):
        self.calls.append((path, body))
        return dict(self.reply)


def test_run_posts_to_the_correct_sku_and_never_sends_local_metadata(agent_dir):
    c = _FakeClient()
    AuditAPI(c).run(agent="my-agent", paths=[agent_dir])
    path, body = c.calls[0]
    assert path == "/v1/services/security.massat-audit"
    assert body["target"] == "my-agent"
    assert "_local" not in body["subject"], "client-side bookkeeping must not be transmitted"


def test_enterprise_flag_selects_the_enterprise_sku(agent_dir):
    c = _FakeClient()
    AuditAPI(c).run(agent="my-agent", paths=[agent_dir], enterprise=True)
    assert c.calls[0][0] == "/v1/services/security.enterprise-audit"


def test_run_verifies_the_returned_digest_against_a_local_recompute(agent_dir):
    payload = AuditAPI.collect([agent_dir])
    good = AuditAPI.subject_digest(payload)

    c = _FakeClient(reply={"status": "completed", "subject_digest": good})
    assert AuditAPI(c).run(agent="my-agent", paths=[agent_dir])["_subject_digest_verified"]

    bad = _FakeClient(reply={"status": "completed", "subject_digest": "0" * 64})
    assert not AuditAPI(bad).run(agent="my-agent", paths=[agent_dir])["_subject_digest_verified"]


def test_anchor_defaults_off(agent_dir):
    """On-chain anchoring spends real gas — it must never be implicit."""
    c = _FakeClient()
    AuditAPI(c).run(agent="my-agent", paths=[agent_dir])
    assert c.calls[0][1]["anchor"] is False


# ------------------------------------------------- anchor verification (network)

SEPOLIA_ATT = {
    "root_commitment": "ab" * 32,
    "witnesses": {"base_sepolia": {"contract": "0x7c5Da1253D42124A8104d2Aa0fEfE954517c33f0"},
                  "nostr": {"status": "ok"}},
}


def test_sepolia_anchor_is_resolved_not_reported_as_missing():
    """The orchestrator anchors under `base_sepolia`; the verifier previously looked
    only for `base_mainnet` and defaulted to the mainnet RPC, so every genuinely
    anchored audit reported "no root_commitment / mainnet contract in attestation"."""
    out = AuditAPI.verify_anchor_receipt(SEPOLIA_ATT)
    assert out.get("witness") == "base_sepolia"
    assert out.get("network") == "base-sepolia"
    assert "no root_commitment" not in str(out.get("error", ""))


def test_testnet_anchor_is_labelled_as_testnet():
    """`exists: true` on a testnet must not read as mainnet finality."""
    out = AuditAPI.verify_anchor_receipt(SEPOLIA_ATT)
    assert "testnet" in out["assurance"].lower()
    assert "NOT mainnet" in out["assurance"]


def test_mainnet_witness_is_preferred_when_present():
    att = dict(SEPOLIA_ATT)
    att["witnesses"] = dict(att["witnesses"])
    att["witnesses"]["base_mainnet"] = {"contract": "0x" + "1" * 40}
    out = AuditAPI.verify_anchor_receipt(att)
    assert out["witness"] == "base_mainnet"
    assert out["assurance"] == "mainnet"


def test_selectors_match_their_contracts():
    """The two anchor contracts expose DISJOINT interfaces, so a selector paired with
    the wrong address returns a wrong answer rather than an error."""
    from eth_utils import keccak  # noqa: PLC0415
    from blindoracle_sdk import audit as A
    assert A._VERIFY_ANCHOR_SELECTOR == "0x" + keccak(text="verifyAnchor(bytes32)")[:4].hex()
    assert A._IS_ANCHORED_SELECTOR == "0x" + keccak(text="isAnchored(bytes32)")[:4].hex()
    assert A._SELECTOR_FOR[A.PROOF_ANCHOR_BASE_MAINNET.lower()] == A._VERIFY_ANCHOR_SELECTOR
    assert A._SELECTOR_FOR[A.AUDIT_ANCHOR_BASE_MAINNET.lower()] == A._IS_ANCHORED_SELECTOR


def test_verify_anchor_defaults_to_the_published_contract():
    """A buyer holding only a root commitment must be able to verify without being
    told where to look — and the default must be the contract the published
    verification instructions name (ProofAnchor on Base mainnet)."""
    from blindoracle_sdk import audit as A
    import inspect
    sig = inspect.signature(A.verify_anchor)
    assert sig.parameters["contract"].default == A.PROOF_ANCHOR_BASE_MAINNET
    assert sig.parameters["network"].default == "base-mainnet"


def test_selector_is_chosen_from_the_contract_not_hardcoded():
    """Passing AuditAnchor must switch the selector, or the call silently misreads."""
    from blindoracle_sdk import audit as A
    captured = {}

    def fake_rpc(urls, method, params, timeout=15):
        captured["data"] = params[0]["data"]
        return "0x" + "0" * 63 + "1"

    orig = A._rpc
    try:
        A._rpc = fake_rpc
        A.verify_anchor("ab" * 32, A.AUDIT_ANCHOR_BASE_MAINNET)
        assert captured["data"].startswith(A._IS_ANCHORED_SELECTOR)
        A.verify_anchor("ab" * 32)
        assert captured["data"].startswith(A._VERIFY_ANCHOR_SELECTOR)
    finally:
        A._rpc = orig


def test_verify_reads_only_the_first_word_of_a_multi_value_return():
    """ProofAnchor.verifyAnchor returns (anchored, anchorId, timestamp) — 96 bytes.
    Decoding the whole return as one integer yields a false NEGATIVE on a genuinely
    anchored root (measured against the live contract 2026-08-16)."""
    from blindoracle_sdk import audit as A
    three_words = ("0x" + "0" * 63 + "1"      # anchored = true
                   + "0" * 62 + "27"           # anchorId = 39
                   + "0" * 56 + "6a80ffb9")    # timestamp
    orig = A._rpc
    try:
        A._rpc = lambda *a, **k: three_words
        assert A.verify_anchor("ab" * 32)["exists"] is True
    finally:
        A._rpc = orig


def test_unanchored_attestation_says_so_plainly():
    out = AuditAPI.verify_anchor_receipt({"root_commitment": "ab" * 32})
    assert out["exists"] is False and out["anchored"] is False
    assert "anchor" in out["error"].lower()
