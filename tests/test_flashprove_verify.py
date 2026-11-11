"""Verdict parsing for examples/flashprove/verify_inference_proof.py (no cp_verify needed)."""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "examples" / "flashprove" / "verify_inference_proof.py"
_spec = importlib.util.spec_from_file_location("verify_inference_proof", _P)
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

ID = "79a5a2bc7a469b40df73dedf40abeb740671e8ae8077738bd3743897aeb22183"


def test_accepted_exact_match():
    out = f"covered: r=60\nresult-v1 status=0 claim=exact-match id={ID} bits=128\nYES\n"
    r = v.parse_verdict(0, out)
    assert r["verdict"] == "accepted" and r["claim"] == "exact-match"
    assert r["result_v1"]["id"] == ID and r["covered"].startswith("covered:")


def test_accepted_clipped_gap():
    r = v.parse_verdict(0, "WITHIN LIMITS: clipped-gap C=1 theta=2 cap=1 s=15 sh=8\n")
    assert r["verdict"] == "accepted" and r["claim"] == "clipped-gap"


def test_refused_reason():
    r = v.parse_verdict(1, "NO: reply-differs\n")
    assert r["verdict"] == "refused" and r["reason"] == "reply-differs"


def test_exit_zero_without_yes_is_not_accepted():
    # An exit code alone is never the answer.
    assert v.parse_verdict(0, "something else\n")["verdict"] == "no_verdict"


def test_yes_with_nonzero_exit_is_not_accepted():
    assert v.parse_verdict(1, "YES\n")["verdict"] == "no_verdict"


def test_not_checked_and_not_a_verification():
    assert v.parse_verdict(5, "NOT CHECKED: internal-stage\n")["verdict"] == "no_verdict"
    r = v.parse_verdict(14, "NOT-A-VERIFICATION\n")
    assert r["verdict"] == "no_verdict" and r["exit_meaning"] == "not_a_verification"


def test_empty_output():
    assert v.parse_verdict(0, "")["verdict"] == "no_verdict"


def test_bad_commitment_id_refused_before_running(tmp_path):
    r = v.run_verify(tmp_path / "cp_verify", tmp_path, tmp_path, tmp_path, tmp_path,
                     tmp_path, "NOT-HEX")
    assert r["verdict"] == "no_verdict" and "64 lowercase hex" in r["last_line"]


def test_missing_binary_is_no_verdict(tmp_path):
    r = v.run_verify(tmp_path / "missing", tmp_path, tmp_path, tmp_path, tmp_path,
                     tmp_path, ID)
    assert r["verdict"] == "no_verdict" and "build.sh" in r["last_line"]
