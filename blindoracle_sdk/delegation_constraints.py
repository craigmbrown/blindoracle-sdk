"""
delegation_constraints.py — Mastercard-style constraint validator for ProofOfDelegation.

Additive structured `constraints[]` field for kind 30014 records. Backwards-compatible:
free-form `scope` strings (when present) are kept verbatim; structured `constraints[]`
emitted alongside when callers supply them.

Mastercard rule: any unknown constraint type in an OPEN MANDATE (mode='open') MUST be
rejected by the verifier. CLOSED MANDATES may ignore unknown types.

Spec source: v5_memory/knowledge/domains/agentic-commerce-trust-protocols.md
Plan:        specs/plan-verifiable-intent-tap-bridge.md (Phase 2)
Schema:      schemas/delegation_constraints.schema.json

@requirement: REQ-VITAP-101 — Structured constraints[] schema validation
@requirement: REQ-VITAP-102 — Open-mandate unknown-constraint rejection
@requirement: REQ-VITAP-103 — Free-form scope backwards-compat
@BLP: Alignment, Self-Improvement

Copyright (c) 2026 Craig M. Brown. All rights reserved.
"""
# BLP: [A]  # auto-classified design-intent (RQ-244/245)

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KNOWN_TYPES = frozenset({
    "max_amount",
    "time_window",
    "merchant_allow_list",
    "product_category",
    "recurrence_rules",
    "budget_cap",
})

# Required keys per type
_REQUIRED = {
    "max_amount": ("type", "value", "currency"),
    "time_window": ("type", "start", "end"),
    "merchant_allow_list": ("type", "merchants"),
    "product_category": ("type", "categories"),
    "recurrence_rules": ("type", "rrule"),
    "budget_cap": ("type", "value", "period"),
}

_BUDGET_PERIODS = frozenset({"daily", "weekly", "monthly", "yearly"})

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


@dataclass
class ConstraintError(Exception):
    """Raised when a constraint fails validation."""

    type: str
    reason: str
    index: int = -1

    def __str__(self) -> str:
        loc = f"[{self.index}] " if self.index >= 0 else ""
        return f"{loc}{self.type}: {self.reason}"


def _validate_one(constraint: Dict[str, Any], index: int = -1) -> None:
    if not isinstance(constraint, dict):
        raise ConstraintError(type="?", reason="not an object", index=index)
    ctype = constraint.get("type")
    if not isinstance(ctype, str) or not ctype:
        raise ConstraintError(type="?", reason="missing 'type'", index=index)
    if ctype not in KNOWN_TYPES:
        raise ConstraintError(type=ctype, reason="unknown constraint type", index=index)

    for k in _REQUIRED[ctype]:
        if k not in constraint:
            raise ConstraintError(type=ctype, reason=f"missing required key '{k}'", index=index)

    # Per-type semantic checks
    if ctype == "max_amount":
        v = constraint["value"]
        if not isinstance(v, (int, float)) or v <= 0:
            raise ConstraintError(type=ctype, reason="value must be > 0", index=index)
        cur = constraint["currency"]
        if not isinstance(cur, str) or not (3 <= len(cur) <= 8):
            raise ConstraintError(type=ctype, reason="currency must be 3-8 chars", index=index)

    elif ctype == "time_window":
        for k in ("start", "end"):
            s = constraint[k]
            if not isinstance(s, str) or not _ISO_RE.match(s):
                raise ConstraintError(type=ctype, reason=f"{k} not ISO-8601", index=index)
        # Optional sanity: start <= end (don't reject on parse errors, just on order)
        try:
            s = datetime.fromisoformat(constraint["start"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(constraint["end"].replace("Z", "+00:00"))
            if s >= e:
                raise ConstraintError(type=ctype, reason="start must be < end", index=index)
        except ValueError:
            pass

    elif ctype == "merchant_allow_list":
        ms = constraint["merchants"]
        if not isinstance(ms, list) or not ms:
            raise ConstraintError(type=ctype, reason="merchants must be non-empty list", index=index)
        if not all(isinstance(m, str) and m for m in ms):
            raise ConstraintError(type=ctype, reason="merchants entries must be non-empty strings", index=index)

    elif ctype == "product_category":
        cs = constraint["categories"]
        if not isinstance(cs, list) or not cs:
            raise ConstraintError(type=ctype, reason="categories must be non-empty list", index=index)
        if not all(isinstance(c, str) and c for c in cs):
            raise ConstraintError(type=ctype, reason="categories entries must be non-empty strings", index=index)

    elif ctype == "recurrence_rules":
        r = constraint["rrule"]
        if not isinstance(r, str) or not r:
            raise ConstraintError(type=ctype, reason="rrule must be non-empty string", index=index)

    elif ctype == "budget_cap":
        v = constraint["value"]
        if not isinstance(v, (int, float)) or v <= 0:
            raise ConstraintError(type=ctype, reason="value must be > 0", index=index)
        p = constraint["period"]
        if p not in _BUDGET_PERIODS:
            raise ConstraintError(type=ctype, reason=f"period must be one of {sorted(_BUDGET_PERIODS)}", index=index)

    # Reject extra keys (additionalProperties: false in the schema)
    expected = set(_REQUIRED[ctype])
    extra = set(constraint.keys()) - expected
    if extra:
        raise ConstraintError(
            type=ctype, reason=f"unexpected keys: {sorted(extra)}", index=index
        )


def validate_constraints(
    constraints: List[Dict[str, Any]],
    *,
    mode: str = "open",
) -> Tuple[bool, Optional[str]]:
    """Validate a constraints[] list.

    Args:
      constraints: list of constraint objects.
      mode: 'open' (Mastercard open-mandate semantics; unknown type → reject) or
            'closed' (legacy / strict-allowlist mandates; unknown type → reject too
            but per Mastercard rule the difference matters only for soft-warn vs hard-fail).

    Returns:
      (ok, error_message). error_message is None on success.
    """
    if not isinstance(constraints, list):
        return False, "constraints must be a list"
    if mode not in ("open", "closed"):
        return False, f"mode must be 'open' or 'closed', got {mode!r}"

    for i, c in enumerate(constraints):
        try:
            _validate_one(c, index=i)
        except ConstraintError as e:
            return False, str(e)
    return True, None


def build_delegation_extras(
    *,
    scope: Optional[str] = None,
    constraints: Optional[List[Dict[str, Any]]] = None,
    mode: str = "open",
) -> Dict[str, Any]:
    """Return the additive fields to merge into a ProofOfDelegation record.

    Both scope and constraints are optional. Backwards-compat: if neither is supplied,
    returns {} and the existing record schema is unchanged.

    Raises ConstraintError if constraints fail validation.
    """
    extras: Dict[str, Any] = {}
    if scope is not None:
        if not isinstance(scope, str):
            raise ConstraintError(type="scope", reason="must be string")
        extras["scope"] = scope
    if constraints is not None:
        ok, err = validate_constraints(constraints, mode=mode)
        if not ok:
            raise ConstraintError(type="constraints", reason=err or "validation failed")
        extras["constraints"] = constraints
        extras["constraint_mode"] = mode
    return extras


# ---------------------------------------------------------------------------
# CLI helper for quick validation
# ---------------------------------------------------------------------------


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Validate a delegation constraints JSON file")
    ap.add_argument("path", type=Path, help="path to a JSON file containing a list of constraints")
    ap.add_argument("--mode", default="open", choices=("open", "closed"))
    args = ap.parse_args()

    data = json.loads(args.path.read_text())
    ok, err = validate_constraints(data, mode=args.mode)
    if ok:
        print(f"OK: {len(data)} constraints valid in mode={args.mode}")
        return 0
    print(f"FAIL: {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
