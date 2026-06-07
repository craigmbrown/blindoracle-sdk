"""
delegation_associativity.py — Delegation Chain Associativity Check (RQ-171).

Verifies two coupled invariants over a ProofOfDelegation (kind 30014) chain:

  Invariant A — Algebraic associativity:
    (a ⊗ b) ⊗ c == a ⊗ (b ⊗ c)  over the chain's authority objects.
    Proves the compose operator is well-formed and effective authority is
    grouping-independent ("fulcrum consistency").

  Invariant B — Monotone narrowing:
    For each consecutive (parent, child): child_grant ⊑ parent_auth.
    A child that broadens scope or loosens a constraint is a privilege escalation
    — maps to OWASP P-ASI03-B.

Run order: integrity verify() first, then verify_associativity().

@requirement: REQ-RQ171-001 — Authority meet operator ⊗
@requirement: REQ-RQ171-002 — verify_associativity: fold left/right must agree
@requirement: REQ-RQ171-003 — Monotone narrowing: child_grant ⊑ parent_auth
@requirement: REQ-RQ171-004 — CLI + result schema; exit 0/1/2
@BLP: Alignment, Durability, Self-Improvement, Self-Organization

Copyright (c) 2026 Craig M. Brown. All rights reserved.
"""
# BLP: [A, D, SI, SO]

from __future__ import annotations

import sys

import json
import re
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from blindoracle_sdk.delegation_constraints import KNOWN_TYPES

DELEGATION_KIND = 30014


# ---------------------------------------------------------------------------
# Authority data model  (REQ-RQ171-001)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Authority:
    """
    Authority object for a delegation link.

    scope=None → ⊤ (unspecified/unrestricted).
    constraints=() → ⊤ (no restrictions).

    Note: constraints is a tuple of dicts; Authority objects are NOT hashable
    when constraints is non-empty (dict is unhashable). Use == for comparison only.
    """
    scope: Optional[frozenset]   # frozenset[str] | None; None = ⊤
    constraints: tuple           # tuple[dict, ...]; sorted by type for canonical equality

    @classmethod
    def top(cls) -> "Authority":
        """The top element ⊤ — fully unrestricted authority."""
        return cls(scope=None, constraints=())

    @classmethod
    def from_record(cls, rec: Dict[str, Any]) -> "Authority":
        """Construct Authority from a kind-30014 record. @requirement: REQ-RQ171-001"""
        raw_scope = rec.get("scope")
        if raw_scope and isinstance(raw_scope, str) and raw_scope.strip():
            tokens = frozenset(
                t for t in re.split(r'[\s,]+', raw_scope.strip()) if t
            )
            scope: Optional[frozenset] = tokens if tokens else None
        else:
            scope = None

        raw_constr = rec.get("constraints") or []
        if isinstance(raw_constr, list):
            valid: List[dict] = []
            for c in raw_constr:
                if not isinstance(c, dict) or c.get("type") not in KNOWN_TYPES:
                    continue
                c_norm = dict(c)
                # Normalize list values to sorted form for canonical equality
                if c.get("type") == "merchant_allow_list" and isinstance(c.get("merchants"), list):
                    c_norm["merchants"] = sorted(c["merchants"])
                elif c.get("type") == "product_category" and isinstance(c.get("categories"), list):
                    c_norm["categories"] = sorted(c["categories"])
                valid.append(c_norm)
            constraints: tuple = tuple(sorted(valid, key=lambda c: c.get("type", "")))
        else:
            constraints = ()

        return cls(scope=scope, constraints=constraints)

    def leq(self, other: "Authority") -> bool:
        """Return True iff self ⊑ other (self is no broader than other).
        @requirement: REQ-RQ171-001"""
        return self == meet(self, other)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": sorted(self.scope) if self.scope is not None else None,
            "constraints": list(self.constraints),
        }


# ---------------------------------------------------------------------------
# Meet operator ⊗  (REQ-RQ171-001)
# ---------------------------------------------------------------------------

def meet(a: Authority, b: Authority) -> Authority:
    """
    Meet (greatest lower bound) of two Authority objects.

    scope:       intersection (None = ⊤, so ⊤ ⊗ S = S)
    constraints: per-type tightening

    The meet is associative, commutative for most types, and idempotent.
    @requirement: REQ-RQ171-001
    """
    if a.scope is None and b.scope is None:
        new_scope: Optional[frozenset] = None
    elif a.scope is None:
        new_scope = b.scope
    elif b.scope is None:
        new_scope = a.scope
    else:
        new_scope = a.scope & b.scope

    new_constraints = _tighten_constraints(a.constraints, b.constraints)
    return Authority(scope=new_scope, constraints=new_constraints)


def _tighten_constraints(a: tuple, b: tuple) -> tuple:
    """Meet of two constraint tuples: greatest lower bound per type."""
    a_by: Dict[str, dict] = {c["type"]: c for c in a if isinstance(c, dict) and "type" in c}
    b_by: Dict[str, dict] = {c["type"]: c for c in b if isinstance(c, dict) and "type" in c}

    result: List[dict] = []
    for ctype in sorted(set(a_by) | set(b_by)):
        ca, cb = a_by.get(ctype), b_by.get(ctype)
        if ca is None:
            result.append(cb)       # type: ignore[arg-type]
        elif cb is None:
            result.append(ca)
        else:
            result.append(_tighten_one(ctype, ca, cb))

    return tuple(sorted(result, key=lambda c: c.get("type", "")))


def _tighten_one(ctype: str, a: dict, b: dict) -> dict:
    """Tighten one constraint pair to their greatest lower bound."""
    if ctype == "max_amount":
        return {**a, "value": min(a["value"], b["value"])}
    if ctype == "budget_cap":
        if a.get("period") == b.get("period"):
            return {**a, "value": min(a["value"], b["value"])}
        return a  # incomparable periods — keep parent's (conservative)
    if ctype == "time_window":
        return {**a, "start": max(a["start"], b["start"]), "end": min(a["end"], b["end"])}
    if ctype == "merchant_allow_list":
        return {**a, "merchants": sorted(set(a.get("merchants", [])) & set(b.get("merchants", [])))}
    if ctype == "product_category":
        return {**a, "categories": sorted(set(a.get("categories", [])) & set(b.get("categories", [])))}
    if ctype == "recurrence_rules":
        return b  # keep child; equality checked in monotone pass; associative: always yields rightmost
    return a  # unknown type — keep parent's


# ---------------------------------------------------------------------------
# Fold helpers
# ---------------------------------------------------------------------------

def _fold_left(auths: List[Authority]) -> Authority:
    """((a ⊗ b) ⊗ c) ..."""
    return reduce(meet, auths) if auths else Authority.top()


def _fold_right(auths: List[Authority]) -> Authority:
    """... (a ⊗ (b ⊗ c))"""
    # reversed yields [c, b, a]; lambda swaps args so meet(b,c) then meet(a, b⊗c)
    return reduce(lambda x, y: meet(y, x), reversed(auths)) if auths else Authority.top()


# ---------------------------------------------------------------------------
# Monotone narrowing checker  (REQ-RQ171-003)
# ---------------------------------------------------------------------------

def _check_monotone(
    records: List[Dict[str, Any]],
    auths: List[Authority],
    *,
    strict_scope: bool = False,
) -> Tuple[List[dict], bool]:
    """Check monotone narrowing link-by-link. Returns (violations, has_hard_violation)."""
    violations: List[dict] = []
    has_hard = False
    acc = auths[0]

    for i in range(1, len(auths)):
        p_eid = records[i - 1].get("event_id", "")
        c_eid = records[i].get("event_id", "")
        child = auths[i]

        # Scope check
        if acc.scope is not None:
            if child.scope is None:
                sev = "hard" if strict_scope else "advisory"
                violations.append({
                    "link_idx": i - 1, "parent": p_eid, "child": c_eid,
                    "type": "scope_expansion", "severity": sev,
                    "detail": "child has no scope restriction but parent had one",
                })
                if strict_scope:
                    has_hard = True
            else:
                expanded = child.scope - acc.scope
                if expanded:
                    sev = "hard" if strict_scope else "advisory"
                    violations.append({
                        "link_idx": i - 1, "parent": p_eid, "child": c_eid,
                        "type": "scope_expansion", "severity": sev,
                        "detail": f"child adds scope tokens not in parent: {sorted(expanded)}",
                    })
                    if strict_scope:
                        has_hard = True

        # Constraint check
        cv, ew = _check_constraint_link(acc.constraints, child.constraints, i - 1, p_eid, c_eid)
        violations.extend(cv)
        if ew:
            violations.append(ew)
        if any(v["severity"] == "hard" for v in cv) or ew:
            has_hard = True

        acc = meet(acc, child)

    return violations, has_hard


def _check_constraint_link(
    parent_c: tuple,
    child_c: tuple,
    link_idx: int,
    p_eid: str,
    c_eid: str,
) -> Tuple[List[dict], Optional[dict]]:
    """Check one link for constraint loosening or empty time window."""
    p_by = {c["type"]: c for c in parent_c if isinstance(c, dict) and "type" in c}
    c_by = {c["type"]: c for c in child_c  if isinstance(c, dict) and "type" in c}

    violations: List[dict] = []
    empty_window: Optional[dict] = None

    for ctype, pc in p_by.items():
        cc = c_by.get(ctype)
        if cc is None:
            violations.append({
                "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                "type": "constraint_loosening", "severity": "hard",
                "detail": f"child drops parent constraint type '{ctype}'",
            })
            continue

        if ctype in ("max_amount", "budget_cap"):
            pv, cv = pc.get("value", 0), cc.get("value", 0)
            if isinstance(cv, (int, float)) and isinstance(pv, (int, float)) and cv > pv:
                label = pc.get("currency") or pc.get("period", "?")
                violations.append({
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "constraint_loosening", "severity": "hard",
                    "detail": f"child raises {ctype} from {pv} to {cv} ({label})",
                })

        elif ctype == "time_window":
            ps, pe = pc.get("start", ""), pc.get("end", "")
            cs, ce = cc.get("start", ""), cc.get("end", "")
            if cs and ps and cs < ps:
                violations.append({
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "constraint_loosening", "severity": "hard",
                    "detail": f"child time_window starts before parent: {cs} < {ps}",
                })
            if ce and pe and ce > pe:
                violations.append({
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "constraint_loosening", "severity": "hard",
                    "detail": f"child time_window ends after parent: {ce} > {pe}",
                })
            eff_start = max(cs, ps) if (cs and ps) else (cs or ps)
            eff_end   = min(ce, pe) if (ce and pe) else (ce or pe)
            if eff_start and eff_end and eff_start >= eff_end:
                empty_window = {
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "empty_time_window", "severity": "hard",
                    "detail": f"intersection of [{ps}, {pe}] and [{cs}, {ce}] is empty",
                }

        elif ctype == "merchant_allow_list":
            p_set = set(pc.get("merchants", []))
            c_set = set(cc.get("merchants", []))
            added = sorted(c_set - p_set)
            if added:
                violations.append({
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "constraint_loosening", "severity": "hard",
                    "detail": f"child merchant_allow_list adds: {added}",
                })

        elif ctype == "product_category":
            p_set = set(pc.get("categories", []))
            c_set = set(cc.get("categories", []))
            added = sorted(c_set - p_set)
            if added:
                violations.append({
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "constraint_loosening", "severity": "hard",
                    "detail": f"child product_category adds: {added}",
                })

        elif ctype == "recurrence_rules":
            if pc.get("rrule") != cc.get("rrule"):
                violations.append({
                    "link_idx": link_idx, "parent": p_eid, "child": c_eid,
                    "type": "constraint_loosening", "severity": "advisory",
                    "detail": (
                        f"child recurrence_rules differ from parent: "
                        f"'{pc.get('rrule')}' vs '{cc.get('rrule')}'"
                    ),
                })

    return violations, empty_window


# ---------------------------------------------------------------------------
# Main verify_associativity  (REQ-RQ171-002 + REQ-RQ171-003 + REQ-RQ171-004)
# ---------------------------------------------------------------------------

def verify_associativity(
    records: List[Dict[str, Any]],
    *,
    strict_scope: bool = False,
) -> Dict[str, Any]:
    """
    Verify authority associativity (invariant A) and monotone narrowing (invariant B)
    over a root→leaf ordered list of kind-30014 records.

    Precondition: records have already passed DelegationLog.verify().

    @requirement: REQ-RQ171-002
    @requirement: REQ-RQ171-003
    @requirement: REQ-RQ171-004
    """
    if not records:
        return {
            "ok": True, "chain_length": 0, "associative": True, "monotone": True,
            "effective_authority": Authority.top().to_dict(),
            "root_event_id": "", "leaf_event_id": "", "violations": [],
        }

    auths = [Authority.from_record(r) for r in records]

    # Invariant A: left-fold must equal right-fold
    left_eff  = _fold_left(auths)
    right_eff = _fold_right(auths)
    associative = (left_eff == right_eff)

    violations: List[dict] = []
    if not associative:
        for i in range(len(auths) - 2):
            a, b, c = auths[i], auths[i + 1], auths[i + 2]
            if meet(meet(a, b), c) != meet(a, meet(b, c)):
                violations.append({
                    "link_idx": i,
                    "parent": records[i].get("event_id", ""),
                    "child": records[i + 2].get("event_id", ""),
                    "type": "non_associative", "severity": "hard",
                    "detail": (
                        f"(auth[{i}] ⊗ auth[{i+1}]) ⊗ auth[{i+2}] "
                        f"≠ auth[{i}] ⊗ (auth[{i+1}] ⊗ auth[{i+2}])"
                    ),
                })
                break

    # Invariant B: monotone narrowing
    b_violations, has_hard = _check_monotone(records, auths, strict_scope=strict_scope)
    violations.extend(b_violations)

    monotone = not has_hard
    ok = associative and monotone

    return {
        "ok": ok,
        "chain_length": len(records),
        "associative": associative,
        "monotone": monotone,
        "effective_authority": left_eff.to_dict(),
        "root_event_id": records[0].get("event_id", ""),
        "leaf_event_id": records[-1].get("event_id", ""),
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# Chain loading helpers
# ---------------------------------------------------------------------------

def _load_kind30014(log_path: Path) -> List[Dict[str, Any]]:
    """Load kind-30014 records from a JSONL file, filtering foreign kinds."""
    if not log_path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("kind") == DELEGATION_KIND:
            records.append(rec)
    return records


def load_chain(log_path: Path, leaf_event_id: str) -> List[Dict[str, Any]]:
    """
    Return root→leaf chain for a given leaf event_id.

    Mirrors DelegationLog.chain_to_root() traversal but inline (stdlib-only).
    """
    records = _load_kind30014(log_path)
    by_eid: Dict[str, Dict[str, Any]] = {
        r["event_id"]: r for r in records if "event_id" in r
    }

    chain: List[Dict[str, Any]] = []
    cur = by_eid.get(leaf_event_id)
    seen: set = set()
    while cur and cur["event_id"] not in seen:
        seen.add(cur["event_id"])
        chain.append(cur)
        prev = cur.get("prev_hash") or ""
        cur = by_eid.get(prev) if prev else None

    chain.reverse()  # root→leaf
    return chain


# ---------------------------------------------------------------------------
# Sweep — audit ALL chains across the known delegation logs (RQ-171 wiring)
# ---------------------------------------------------------------------------

# Default logs scanned by --sweep. Order is irrelevant; missing paths are skipped.
DEFAULT_SWEEP_GLOBS = (
    "data/delegation_proofs.json",
    "data/proof_run_*/delegation_proofs.jsonl",
)
SWEEP_AUDIT_LOG = Path("/home/craigmbrown/Project/data/delegation_associativity_audit.jsonl")


def find_leaves(records: List[Dict[str, Any]]) -> List[str]:
    """Leaf = an event_id that is no other record's prev_hash (a chain tip)."""
    eids = {r["event_id"] for r in records if "event_id" in r}
    prevs = {r.get("prev_hash") for r in records if r.get("prev_hash")}
    return sorted(eids - prevs)


def sweep_logs(
    log_paths: List[Path],
    *,
    strict_scope: bool = False,
) -> Dict[str, Any]:
    """
    Walk every chain (one per leaf) across `log_paths`, run verify_associativity
    on each, and aggregate. Hard violations = privilege escalation (P-ASI03-B).

    Returns a summary dict. Pure (no I/O side effects); caller persists it.
    """
    chains_checked = 0
    hard_violations: List[Dict[str, Any]] = []
    advisory_count = 0
    non_associative: List[str] = []
    per_log: List[Dict[str, Any]] = []

    for lp in log_paths:
        records = _load_kind30014(lp)
        if not records:
            continue
        leaves = find_leaves(records)
        log_hard = 0
        for leaf in leaves:
            chain = load_chain(lp, leaf)
            if not chain:
                continue
            chains_checked += 1
            res = verify_associativity(chain, strict_scope=strict_scope)
            if not res["associative"]:
                non_associative.append(leaf)
            for v in res["violations"]:
                if v["severity"] == "hard":
                    log_hard += 1
                    hard_violations.append({
                        "log": str(lp), "leaf": leaf,
                        "link_idx": v["link_idx"], "type": v["type"],
                        "detail": v["detail"],
                    })
                else:
                    advisory_count += 1
        per_log.append({"log": str(lp), "leaves": len(leaves), "hard": log_hard})

    return {
        "logs_scanned": len(per_log),
        "chains_checked": chains_checked,
        "hard_violations": hard_violations,
        "hard_violation_count": len(hard_violations),
        "advisory_count": advisory_count,
        "non_associative_leaves": non_associative,
        "per_log": per_log,
        "ok": not hard_violations and not non_associative,
    }


def _resolve_sweep_logs(globs) -> List[Path]:
    root = Path("/home/craigmbrown/Project")
    out: List[Path] = []
    for g in globs:
        out.extend(sorted(root.glob(g)) if ("*" in g or "?" in g) else [root / g])
    # de-dupe, keep only existing
    seen, uniq = set(), []
    for p in out:
        if p.exists() and str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _run_sweep(globs, *, strict_scope: bool, as_json: bool) -> int:
    from datetime import datetime, timezone
    logs = _resolve_sweep_logs(globs)
    summary = sweep_logs(logs, strict_scope=strict_scope)
    summary["ts"] = datetime.now(timezone.utc).isoformat()
    summary["strict_scope"] = strict_scope

    # Append audit record (P-ASI10 — autonomous action leaves a trail).
    try:
        SWEEP_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SWEEP_AUDIT_LOG.open("a") as fh:
            fh.write(json.dumps(summary) + "\n")
    except OSError as e:
        sys.stderr.write(f"WARN: could not write sweep audit log: {e}\n")

    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        status = "OK" if summary["ok"] else "FAIL"
        print(f"[{status}] delegation associativity sweep — "
              f"{summary['chains_checked']} chain(s) across "
              f"{summary['logs_scanned']} log(s)")
        print(f"  hard violations (privilege escalation): "
              f"{summary['hard_violation_count']}")
        print(f"  advisory scope notes: {summary['advisory_count']}")
        if summary["non_associative_leaves"]:
            print(f"  ⚠ non-associative chains: "
                  f"{len(summary['non_associative_leaves'])}")
        for v in summary["hard_violations"][:10]:
            print(f"    !! {v['type']} @ link={v['link_idx']} "
                  f"leaf={v['leaf'][:12]}: {v['detail']}")

    return 2 if not summary["ok"] else 0


# ---------------------------------------------------------------------------
# CLI  (REQ-RQ171-004)
# ---------------------------------------------------------------------------

def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=(
            "Verify delegation chain associativity (invariant A) and "
            "monotone narrowing / no privilege escalation (invariant B). "
            "Run DelegationLog.verify() for integrity BEFORE this check."
        )
    )
    ap.add_argument("--sweep", action="store_true",
                    help="Audit ALL chains across the known delegation logs "
                         "(daily-cron mode). Ignores --log/--leaf.")
    ap.add_argument("--log", type=Path, required=False,
                    help="Path to delegation proof log (JSONL with kind-30014 records).")
    ap.add_argument("--leaf", type=str, required=False,
                    help="event_id of the leaf delegation record to check.")
    ap.add_argument("--strict-scope", action="store_true",
                    help="Treat scope_expansion violations as hard failures.")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON result instead of human-readable output.")
    args = ap.parse_args()

    if args.sweep:
        return _run_sweep(DEFAULT_SWEEP_GLOBS,
                          strict_scope=args.strict_scope,
                          as_json=args.json)

    if not args.log or not args.leaf:
        sys.stderr.write("ERROR: --log and --leaf are required unless --sweep is set\n")
        return 1

    chain = load_chain(args.log, args.leaf)
    if not chain:
        sys.stderr.write(
            f"ERROR: no kind-30014 chain ending at leaf={args.leaf!r} in {args.log}\n"
        )
        return 1

    result = verify_associativity(chain, strict_scope=args.strict_scope)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_human(result)

    if not result["ok"]:
        if any(v["severity"] == "hard" for v in result["violations"]):
            return 2
    return 0


def _print_human(result: Dict[str, Any]) -> None:
    status = "OK" if result["ok"] else "FAIL"
    print(f"[{status}] chain_length={result['chain_length']}  "
          f"associative={result['associative']}  monotone={result['monotone']}")
    r, l = result["root_event_id"], result["leaf_event_id"]
    print(f"  root: {r[:16]}{'...' if len(r) > 16 else ''}")
    print(f"  leaf: {l[:16]}{'...' if len(l) > 16 else ''}")
    eff = result["effective_authority"]
    scope_str = ", ".join(eff["scope"]) if eff["scope"] else "⊤ (unrestricted)"
    constr_str = f"{len(eff['constraints'])} constraint(s)" if eff["constraints"] else "none"
    print(f"  scope:       {scope_str}")
    print(f"  constraints: {constr_str}")
    if result["violations"]:
        print(f"  violations ({len(result['violations'])}):")
        for v in result["violations"]:
            icon = "!!" if v["severity"] == "hard" else "??"
            print(f"    [{icon} {v['severity']}] link={v['link_idx']} "
                  f"type={v['type']}: {v['detail']}")


if __name__ == "__main__":
    raise SystemExit(_main())
