"""BlindOracle Compliance API — DeFi protocol stress-testing and risk scoring."""

from typing import Optional, List


SUPPORTED_PROTOCOLS = [
    "aave-v3", "uniswap-v4", "compound-v3",
    "curve", "lido", "maker-dao",
]


class ComplianceResult:
    """Result of a DeFi protocol compliance check."""
    def __init__(self, data: dict):
        self.protocol = data.get("protocol")
        self.address = data.get("address")
        self.risk_score = data.get("risk_score")       # 0-100 (100 = safest)
        self.tail_risk_pct = data.get("tail_risk_pct") # % probability of >10% drawdown
        self.findings = data.get("findings", [])
        self.chainlink_feed = data.get("chainlink_feed")
        self.verified_at = data.get("verified_at")
        self.cost_usd = data.get("cost_usd", 0.50)
        self.raw = data

    def is_safe(self, min_score: int = 70) -> bool:
        """Returns True if risk_score >= min_score."""
        return (self.risk_score or 0) >= min_score

    def __repr__(self):
        return (
            f"<ComplianceResult protocol={self.protocol!r} "
            f"score={self.risk_score} tail_risk={self.tail_risk_pct}%>"
        )


class ComplianceAPI:
    """
    DeFi compliance and risk scoring via Chainlink oracles.

    Pricing:
        - Single check: $0.50/call (x402 micropayment)
        - Bundle (6 protocols): $2.00 flat
        - Monthly: $99/mo (unlimited checks)
        - Enterprise: $499/mo (custom protocols + SLA)

    Example:
        # Check one protocol
        result = client.compliance.check("aave-v3")
        print(result.risk_score, result.tail_risk_pct)

        # Bundle check all 6 protocols
        results = client.compliance.check_all()
        for r in results:
            if not r.is_safe():
                print(f"WARNING: {r.protocol} risk score {r.risk_score}")
    """

    def __init__(self, client):
        self._client = client

    def check(
        self,
        protocol: str,
        address: Optional[str] = None,
    ) -> ComplianceResult:
        """
        Run a compliance check on a single DeFi protocol.

        Args:
            protocol: Protocol name (e.g. "aave-v3") or contract address
            address: Optional — specific contract address to check

        Returns:
            ComplianceResult with risk_score, tail_risk, findings

        Cost:
            $0.50 per call (x402 micropayment)
            Free if subscribed to $99/mo or $499/mo tier.
        """
        body = {"protocol": protocol}
        if address:
            body["address"] = address
        data = self._client.post("/compliance/check", body=body)
        return ComplianceResult(data)

    def check_all(self) -> List[ComplianceResult]:
        """
        Bundle check all 6 monitored DeFi protocols.

        Returns:
            List of ComplianceResult for each protocol

        Cost:
            $2.00 flat (vs. $3.00 for 6 individual checks)
        """
        data = self._client.post("/compliance/check-all", body={})
        return [ComplianceResult(r) for r in data.get("results", [])]

    def get_supported_protocols(self) -> List[str]:
        """List all protocols currently supported for compliance checks."""
        data = self._client.get("/compliance/protocols")
        return data.get("protocols", SUPPORTED_PROTOCOLS)

    def get_history(
        self,
        protocol: Optional[str] = None,
        limit: int = 10,
    ) -> List[ComplianceResult]:
        """
        Get historical compliance check results.

        Args:
            protocol: Filter by protocol name
            limit: Max results (default 10)

        Returns:
            List of ComplianceResult ordered by verified_at desc
        """
        params = {"limit": limit}
        if protocol:
            params["protocol"] = protocol
        data = self._client.get("/compliance/history", params=params)
        return [ComplianceResult(r) for r in data.get("results", [])]
