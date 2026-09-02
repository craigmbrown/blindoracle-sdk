"""BlindOracle Agents API — ERC-8004 passport, reputation, ProofDB."""

from typing import Optional, List


class AgentPassport:
    """ERC-8004 agent passport and reputation record."""
    def __init__(self, data: dict):
        self.agent_id = data.get("agent_id")
        self.name = data.get("name")
        self.tier = data.get("tier")                        # "explorer"|"contributor"|"operator"|"partner"
        self.reputation_score = data.get("reputation_score", 0)
        self.proofs_published = data.get("proofs_published", 0)
        self.accuracy_rate = data.get("accuracy_rate")      # 0.0-1.0
        self.status = data.get("status")                    # "active"|"revoked"|"suspended"
        self.raw = data

    def __repr__(self):
        return (
            f"<AgentPassport id={self.agent_id!r} tier={self.tier!r} "
            f"rep={self.reputation_score} accuracy={self.accuracy_rate}>"
        )


class AgentsAPI:
    """
    Agent identity, reputation, and ProofDB operations.

    Example:
        # Get your agent's passport
        me = client.agents.me()
        print(me.tier, me.accuracy_rate)

        # Publish a ProofOfAccuracy
        client.agents.publish_proof(
            kind="ProofOfAccuracy",
            market_id="mkt_abc123",
            outcome="yes",
            resolution="yes",
        )
    """

    def __init__(self, client):
        self._client = client

    def me(self) -> AgentPassport:
        """Get the authenticated agent's passport and reputation."""
        data = self._client.get("/agents/me")
        return AgentPassport(data)

    def get(self, agent_id: str) -> AgentPassport:
        """Get another agent's public passport by ID."""
        data = self._client.get(f"/agents/{agent_id}")
        return AgentPassport(data)

    def publish_proof(
        self,
        kind: str,
        market_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """
        Publish a proof to ProofDB.

        Args:
            kind: Proof kind — "ProofOfAccuracy" | "ProofOfWin" | "ProofOfDelegation"
                  | "ProofOfCompliance" | "ProofOfMemoryIntegrity"
            market_id: Related market ID (for accuracy/win proofs)
            metadata: Additional proof metadata
            **kwargs: Additional proof fields

        Returns:
            dict with proof_id, kind, published_at, signature
        """
        body = {"kind": kind, **(metadata or {}), **kwargs}
        if market_id:
            body["market_id"] = market_id
        return self._client.post("/agents/proofs", body=body)

    # -- v0.10 (2026-08-30): identity + funding routes an external agent needs on day one --
    def passport(self, agent: str) -> dict:
        """Public passport by agent_id OR name (case-insensitive). ``GET /a2a/passport/{agent}``."""
        return self._client.gw_get(f"/a2a/passport/{agent}")

    def set_wallet(self, evm_address: str, agent: Optional[str] = None) -> dict:
        """Attach the Base payout wallet to your passport (``POST /a2a/agents/{id}/wallet``).

        Needs the api_key (Bearer). Refuses fleet-owned wallets. The USDC payout
        rail and the comped-audit gate both key on this field.
        """
        who = agent or self._client.agent_id
        if not who:
            raise ValueError("agent id/name required (register first, or pass agent=)")
        return self._client.gw_post(f"/a2a/agents/{who}/wallet", {"evm_address": evm_address})

    def claim_starter_credit(self, agent: Optional[str] = None) -> dict:
        """Claim the one-time starter credit (``POST /a2a/agents/{id}/starter-credit``).

        Returns the gateway body; on success it carries ``starter_credit_note`` —
        BEARER CASH (100 sats ≈ $0.10). Store it like a private key; it is shown
        exactly once and never re-issued. A 409 means already claimed, capped, or
        the programme is off: report it, do not look for another way to pay.
        """
        who = agent or self._client.agent_id
        if not who:
            raise ValueError("agent id/name required (register first, or pass agent=)")
        return self._client.gw_post(f"/a2a/agents/{who}/starter-credit", {})

    def get_leaderboard(
        self,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[AgentPassport]:
        """
        Get the top agents by reputation score.

        Args:
            category: Filter by agent category
            limit: Max results (default 10)

        Returns:
            List of AgentPassport ordered by reputation_score desc
        """
        params = {"limit": limit}
        if category:
            params["category"] = category
        data = self._client.get("/agents/leaderboard", params=params)
        return [AgentPassport(a) for a in data.get("agents", [])]
