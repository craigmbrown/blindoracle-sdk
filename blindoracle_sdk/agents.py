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

    # -- v0.11 (2026-10-30): spend your owner's own USDC without holding a key --
    def topup(self, tx_hash: str, agent: Optional[str] = None) -> dict:
        """Credit a USDC-on-Base transfer to this agent's prepaid balance (``POST /a2a/agents/{id}/topup``).

        The owner sends USDC on Base FROM the wallet registered with ``set_wallet()`` to the
        BlindOracle treasury, then passes the tx hash here. The gateway verifies it on chain,
        checks the sender is the registered wallet, and credits each hash once. The private
        key stays in the owner's wallet app; this agent only ever sees the tx hash.
        """
        who = agent or self._client.agent_id
        if not who:
            raise ValueError("agent id/name required (register first, or pass agent=)")
        return self._client.gw_post(f"/a2a/agents/{who}/topup", {"tx_hash": tx_hash})

    def prepaid_balance(self, agent: Optional[str] = None) -> dict:
        """Starter credit + prepaid USDC balance + recent top-ups (``GET /a2a/agents/{id}/balance``)."""
        who = agent or self._client.agent_id
        if not who:
            raise ValueError("agent id/name required (register first, or pass agent=)")
        return self._client.gw_get(f"/a2a/agents/{who}/balance")

    def buy_with_balance(self, sku_id: str, body: Optional[dict] = None) -> dict:
        """Call a paid SKU and debit the prepaid balance (``POST /v1/services/{sku}``, ``pay_from: balance``).

        Needs the api_key. A refusal (no balance, below price) returns with nothing charged; a
        no-charge result refunds the debit.
        """
        if not self._client.api_key:
            raise ValueError("api_key required: pay_from balance is tied to your agent")
        return self._client.gw_post(f"/v1/services/{sku_id}",
                                    {**(body or {}), "pay_from": "balance"})

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
