#!/usr/bin/env python3
"""Check a FlashProve proof of inference on your own machine, and read the verdict safely.

FlashProve (Anthropic, Apache 2.0, https://github.com/anthropics/FlashProve) lets a model
provider prove that a reply came from the weights behind a published commitment ID,
without revealing the weights. The provider proves on a GPU. Anyone verifies on a CPU.

This file wraps FlashProve's own C++ verifier, `cp_verify`, and adds nothing to the
cryptography. It does three things:

  * runs `cp_verify` and turns its exit code + last line into one JSON verdict;
  * refuses to treat anything other than exit 0 with `YES` / `WITHIN LIMITS:` as accepted;
  * `--selftest` re-runs the repository's 4 published example proofs (expect accepted) and
    3 tampered copies we make locally (expect refused), so you can see the verifier rejects
    a forgery on your machine before you trust it with a real proof.

Standalone: stdlib only, no BlindOracle call, no network.

    git clone https://github.com/anthropics/FlashProve && cd FlashProve
    git checkout 9e2bdd8ff5bf9c62f18263d7dac189b0400b260c     # v0.16.0, the tree we tested
    verifier/build.sh                                          # 1-2 min, g++ 12.2 worked for us
    python3 verify_inference_proof.py --flashprove-dir . --selftest

    python3 verify_inference_proof.py --flashprove-dir . \\
        --config CONFIG_DIR --ivk PUBLIC_KEY_DIR --request REQ --tokens Y --proof PROOF \\
        --id <64-hex commitment ID>  [--policy clipped-gap,C,theta,cap,s,sh]

THE ONE RULE (from FlashProve's own docs): take the commitment ID from a party you trust,
never from the server whose reply you are checking and never from files sent with the
proof. A proof only says "the weights behind THIS ID produced THIS reply". If the ID came
from the same server, a valid proof tells you nothing about which model it is.

What a YES does not tell you: that the provider serves this model to everyone, that the
weights are safe, or anything about replies that were not proved. FlashProve v0.16.0
covers Llama 4 Maverick's shape, greedy decoding, contexts up to 1,024 tokens.

Exit code: 0 accepted, 1 refused, 2 no verdict (bad call, missing binary, not checked).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

# cp_verify exit codes (verifier/docs/output.md in the FlashProve tree).
_EXIT_MEANING = {
    0: "accepted",
    1: "refused",
    5: "not_checked",
    14: "not_a_verification",
}


def parse_verdict(returncode: int, stdout: str) -> dict:
    """Map cp_verify's exit code and output to a verdict. Pure; never raises.

    Accepted only when BOTH the exit code is 0 AND the last line is `YES` or starts with
    `WITHIN LIMITS:`. Any disagreement between the two is reported as no verdict, not as
    accepted: an exit code alone is not the answer (FlashProve's docs say read both)."""
    lines = [ln.rstrip() for ln in (stdout or "").splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    result_v1 = next((ln for ln in reversed(lines) if ln.startswith("result-v1 ")), None)
    covered = next((ln for ln in reversed(lines) if ln.startswith("covered:")), None)
    fields = {}
    if result_v1:
        for tok in result_v1.split()[1:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                fields[k] = v

    if returncode == 0 and (last == "YES" or last.startswith("WITHIN LIMITS:")):
        verdict = "accepted"
        claim = "exact-match" if last == "YES" else "clipped-gap"
    elif returncode == 1 and last.startswith("NO:"):
        verdict, claim = "refused", None
    else:
        verdict, claim = "no_verdict", None

    return {
        "verdict": verdict,
        "claim": claim,
        "exit_code": returncode,
        "exit_meaning": _EXIT_MEANING.get(returncode, "bad_call_or_file"),
        "last_line": last,
        "reason": last[3:].strip() if last.startswith("NO:") else None,
        "result_v1": fields or None,
        "covered": covered,
    }


def run_verify(cp_verify: Path, config: Path, ivk: Path, request: Path, tokens: Path,
               proof: Path, commitment_id: str, policy: str | None = None,
               timeout: int = 600) -> dict:
    if not _HEX64.match(commitment_id or ""):
        return {"verdict": "no_verdict", "exit_code": None,
                "last_line": "commitment ID must be 64 lowercase hex digits"}
    cmd = [str(cp_verify), str(config), str(ivk), str(request), str(tokens), str(proof),
           "-id", commitment_id, "-q"]
    if policy:
        cmd += ["-policy", policy]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"verdict": "no_verdict", "exit_code": None,
                "last_line": f"cp_verify not found at {cp_verify}; run verifier/build.sh"}
    except subprocess.TimeoutExpired:
        return {"verdict": "no_verdict", "exit_code": None, "last_line": "timeout"}
    # The verdict is read from stdout only; stderr is kept apart so a trailing warning can
    # never become the "last line". With no stdout at all (bad call), fall back to stderr.
    out = parse_verdict(p.returncode, p.stdout if p.stdout.strip() else p.stderr)
    if p.stderr.strip():
        out["stderr_tail"] = p.stderr.strip().splitlines()[-1][:300]
    out["commitment_id"] = commitment_id
    out["policy"] = policy or "exact-match"
    return out


def _example_policy(example_dir: Path) -> str | None:
    """The clipped-gap examples need the full policy tuple from their README."""
    if "clipped-gap" not in example_dir.name:
        return None
    m = re.search(r"clipped-gap,\d+,\d+,\d+,\d+,\d+",
                  (example_dir / "README.md").read_text(errors="replace"))
    return m.group(0) if m else None


def selftest(fp: Path) -> int:
    cp = fp / "bin" / "cp_verify"
    ex = fp / "examples"
    rows = []
    for name in ("accepted-proof", "accepted-proof-clipped-gap",
                 "full-size", "full-size-clipped-gap"):
        d = ex / name
        if not d.is_dir():
            rows.append((name, "accepted", {"verdict": "no_verdict", "last_line": "missing"}))
            continue
        r = run_verify(cp, d / "config", d / "ivk", d / "example.req", d / "example.y",
                       d / "example.proof", (d / "ID.txt").read_text().strip(),
                       _example_policy(d))
        rows.append((name, "accepted", r))

    d = ex / "accepted-proof"
    good_id = (d / "ID.txt").read_text().strip()
    with tempfile.TemporaryDirectory() as tmp:
        bad_proof = Path(tmp) / "flipped.proof"
        shutil.copy(d / "example.proof", bad_proof)
        with open(bad_proof, "r+b") as fh:          # flip one byte in the middle
            fh.seek(4000)
            b = fh.read(1)
            fh.seek(4000)
            fh.write(bytes([b[0] ^ 0xFF]))
        bad_tok = Path(tmp) / "other.y"
        bad_tok.write_bytes(b"\x07\x00\x00\x00")    # a different next token
        other_id = (ex / "full-size" / "ID.txt").read_text().strip()
        base = (cp, d / "config", d / "ivk", d / "example.req")
        rows.append(("tampered: one proof byte flipped", "refused",
                     run_verify(*base, d / "example.y", bad_proof, good_id)))
        rows.append(("tampered: wrong commitment ID", "refused",
                     run_verify(*base, d / "example.y", d / "example.proof", other_id)))
        rows.append(("tampered: different reply token", "refused",
                     run_verify(*base, bad_tok, d / "example.proof", good_id)))

    ok = True
    for name, want, r in rows:
        good = r["verdict"] == want
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {name:36s} want={want:8s} got={r['verdict']:10s} "
              f"{r.get('last_line', '')[:70]}")
    print("selftest:", "all as expected" if ok else "UNEXPECTED RESULT, do not trust this build")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--flashprove-dir", type=Path, required=True,
                    help="a FlashProve checkout where verifier/build.sh has run")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--ivk", type=Path, help="the provider's public key directory")
    ap.add_argument("--request", type=Path, help="request file (build it yourself)")
    ap.add_argument("--tokens", type=Path, help="the reply token file")
    ap.add_argument("--proof", type=Path)
    ap.add_argument("--id", dest="commitment_id",
                    help="commitment ID from a party you trust, not from the server")
    ap.add_argument("--policy", help="e.g. clipped-gap,C,theta,cap,s,sh (default exact-match)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.flashprove_dir)
    need = [a.config, a.ivk, a.request, a.tokens, a.proof, a.commitment_id]
    if any(x is None for x in need):
        ap.error("--config --ivk --request --tokens --proof --id are required (or --selftest)")
    r = run_verify(a.flashprove_dir / "bin" / "cp_verify", a.config, a.ivk, a.request,
                   a.tokens, a.proof, a.commitment_id, a.policy)
    print(json.dumps(r, indent=2))
    return {"accepted": 0, "refused": 1}.get(r["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
