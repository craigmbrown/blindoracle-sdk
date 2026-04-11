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
