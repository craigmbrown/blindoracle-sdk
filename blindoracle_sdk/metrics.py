"""BlindOracle Metrics API — accuracy benchmarks + cost/revenue introspection."""
from typing import Optional


class MetricsAPI:
    """Accuracy benchmarks and cost/revenue accounting.

    Example:
        bench = client.metrics.accuracy_benchmark()
        est = client.metrics.cost_estimate("security.massat-audit", {"scope": "full"})
        rev = client.metrics.revenue("agent-x", role="provider")
    """

    def __init__(self, client):
        self._client = client

    def accuracy_benchmark(self) -> dict:
        """Platform accuracy benchmark (verified A/B figures vs baseline)."""
        return self._client.gw_get("/a2a/metrics/accuracy-benchmark")

    def cost_estimate(self, capability_id: str, params: Optional[dict] = None) -> dict:
        """Estimate the price of a capability call before making it."""
        return self._client.gw_post("/a2a/cost/estimate", {"capability_id": capability_id,
                                                           "params": params or {}})

    def revenue(self, agent_id: str, role: str = "provider") -> dict:
        """Settlement accounting for an agent (settled_cash vs booked, by rail)."""
        if role not in ("provider", "requester"):
            raise ValueError("role must be 'provider' or 'requester'")
        return self._client.gw_get(f"/a2a/agents/{agent_id}/revenue", params={"role": role})
