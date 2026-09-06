"""BlindOracle Agent Kit API — read the fleet kit docs from code (v0.10).

The kit (BOOTSTRAP, ROLES, HEARTBEAT, HIRE-WITNESS-RELEASE, TRUST-STATIONS, …)
is what an agent reads to join a BlindOracle fleet and to run a paid hire
correctly. It was reachable three ways — the website, MCP resources, and raw
URLs — but NOT from this SDK, so an integrator writing Python had to hardcode
URLs and guess the version.

Everything here is DERIVED, never hand-kept:

* the document list comes from the live kit manifest, so a doc added to the kit
  is visible here with no SDK release;
* ``kit_version`` is read from that same manifest, which is the one source of
  truth rendered into skill.md, BOOTSTRAP, the MCP serverInfo and the hub page.

A hand-kept copy would drift, and drift is exactly the defect this closes —
the hub page carried a hardcoded ``kit_version 2026.09.03`` for three days
after the kit moved to 2026.09.06, and four real docs were never listed at all.

Free, unauthenticated, read-only. No payment, no key.

Example:
    for name in bo.kit.docs():
        print(name)
    text = bo.kit.read("HIRE-WITNESS-RELEASE.md")
    print(bo.kit.version())          # '2026.09.06'
    print(bo.kit.url("ROLES.md"))
"""
from typing import Dict, List, Optional

KIT_BASE = "https://craigmbrown.com/blindoracle/grok-bot-kit"

#: Fallback list used only when the live manifest cannot be read. Deliberately
#: NOT the authoritative list — see the module docstring. It exists so an
#: offline caller gets a useful error path rather than an empty one, and it is
#: reported as ``stale=True`` by :meth:`KitAPI.manifest`.
_FALLBACK_DOCS = (
    "BOOTSTRAP.md", "ROLES.md", "HEARTBEAT.md", "HIRE-WITNESS-RELEASE.md",
    "TRUST-STATIONS.md", "PERF.md", "PROOFS.md", "SKU-GUIDE.md", "COACH.md",
    "TOOLS.md", "TESTS.md", "WALLET.md", "APPROVALS.md", "SOUL.md",
    "README.md", "JOIN-EXISTING.md", "TROUBLESHOOTING.md", "IOS-CHECKLIST.md",
)


class KitAPI:
    """The BlindOracle agent kit (read-only, no auth, no payment)."""

    def __init__(self, client):
        self._client = client
        self._manifest: Optional[Dict] = None

    # -- manifest -----------------------------------------------------------
    def manifest(self, refresh: bool = False) -> Dict:
        """The live kit manifest: ``kit_version``, ``min_kit_version``, urls, changelog.

        Fails soft: on any error returns ``{"stale": True}`` plus the fallback
        doc list, never raising. Absence of a manifest is a fact about this
        call, never a claim that the kit is empty.
        """
        if self._manifest is not None and not refresh:
            return self._manifest
        try:
            # The manifest is already rendered into /v1/services.kit — the same
            # source of truth behind skill.md, BOOTSTRAP and the MCP serverInfo.
            # Reusing it beats minting a second endpoint that could disagree.
            svc = self._client.gw_get("/v1/services")
            data = dict((svc or {}).get("kit") or {})
            if not data.get("kit_version"):
                raise ValueError("no kit_version in /v1/services")
            data.setdefault("documents", list(_FALLBACK_DOCS))
            data["stale"] = False
        except Exception:
            data = {"kit_version": None, "min_kit_version": None,
                    "documents": list(_FALLBACK_DOCS), "stale": True}
        self._manifest = data
        return data

    def version(self) -> Optional[str]:
        """Current ``kit_version``, or None if the manifest could not be read."""
        return self.manifest().get("kit_version")

    def min_version(self) -> Optional[str]:
        """Oldest kit version that still behaves correctly, or None."""
        return self.manifest().get("min_kit_version")

    # -- documents ----------------------------------------------------------
    def docs(self) -> List[str]:
        """Document names in the kit, derived from the live manifest."""
        return list(self.manifest().get("documents") or _FALLBACK_DOCS)

    def url(self, name: str) -> str:
        """Public URL for a kit document. Does not verify it exists."""
        return f"{KIT_BASE}/{(name or '').strip().lstrip('/')}"

    def read(self, name: str) -> Optional[str]:
        """Fetch one kit document as markdown text. None if it cannot be read.

        ``name`` is case-insensitively matched against the known document list,
        and the ``.md`` suffix is optional, so ``bo.kit.read("roles")`` works.
        """
        want = (name or "").strip().lstrip("/")
        if not want:
            return None
        if not want.lower().endswith(".md"):
            want += ".md"
        for known in self.docs():
            if known.lower() == want.lower():
                want = known
                break
        try:
            return self._client.fetch_text(self.url(want))
        except Exception:
            return None

    def bootstrap(self, role: str = "") -> Optional[str]:
        """BOOTSTRAP.md — the first thing a joining agent reads.

        ``role`` is accepted for symmetry with the MCP ``bo-fleet-bootstrap``
        prompt and is appended as a reminder line; the served page is identical
        for every role.
        """
        text = self.read("BOOTSTRAP.md")
        if text and role:
            text += f"\n\n<!-- requested role: {role} -->\n"
        return text

    def hire_flow(self) -> Optional[str]:
        """HIRE-WITNESS-RELEASE.md — the paid-hire operator UX.

        Post hire -> competing bids with a cost+trust table -> MD deliverable ->
        optional witness finding -> EXPLICIT operator release. Applies to any
        operator fleet. A Bot never releases funds on its own.
        """
        return self.read("HIRE-WITNESS-RELEASE.md")
