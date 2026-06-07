"""BlindOracle Markets API — list, get, create, predict."""

from typing import Optional, List, Iterator


class Market:
    """A BlindOracle prediction market (typed view over the JSON payload).

    Stdlib only — no pydantic (the SDK is zero-dependency). ``as_dict()`` /
    ``model_dump()`` return the raw payload for callers migrating from
    pydantic-based clients.
    """

    id: Optional[str]
    title: Optional[str]
    status: Optional[str]
    resolution_date: Optional[str]
    yes_probability: Optional[float]
    total_volume: float
    oracle: Optional[str]

    def __init__(self, data: dict):
        self.id = data.get("id")
        self.title = data.get("title")
        self.status = data.get("status")
        self.resolution_date = data.get("resolution_date")
        self.yes_probability = data.get("yes_probability")
        self.total_volume = data.get("total_volume_usd", 0)
        self.oracle = data.get("oracle_source")
        self.raw = data

    def as_dict(self) -> dict:
        """Return the underlying JSON payload."""
        return self.raw

    # pydantic-refugee ergonomics
    model_dump = as_dict

    def __repr__(self):
        return f"<Market id={self.id!r} title={self.title!r} p={self.yes_probability}>"


class MarketsAPI:
    """
    Prediction market operations.

    Example:
        markets = client.markets.list(status="active", category="defi")
        for m in markets:
            print(m.title, m.yes_probability)
    """

    def __init__(self, client):
        self._client = client

    def list(
        self,
        status: Optional[str] = "active",
        category: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Market]:
        """
        List prediction markets.

        Args:
            status: "active" | "resolved" | "all"
            category: "defi" | "ai" | "crypto" | "macro"
            limit: Max results (default 20, max 100)
            offset: Pagination offset

        Returns:
            List of Market objects
        """
        params = {"limit": limit, "offset": offset}
        if status and status != "all":
            params["status"] = status
        if category:
            params["category"] = category

        data = self._client.get("/markets", params=params)
        return [Market(m) for m in data.get("markets", [])]

    def iter(
        self,
        status: Optional[str] = "active",
        category: Optional[str] = None,
        page_size: int = 50,
        max_results: Optional[int] = None,
    ) -> Iterator[Market]:
        """Lazily iterate every market, auto-following pagination.

        No manual offset bookkeeping — stops when a page returns fewer than
        ``page_size`` rows (the last page) or ``max_results`` is reached.

            for m in client.markets.iter(status="active"):
                print(m.title)
        """
        offset = 0
        yielded = 0
        while True:
            batch = self.list(status=status, category=category, limit=page_size, offset=offset)
            if not batch:
                return
            for m in batch:
                yield m
                yielded += 1
                if max_results is not None and yielded >= max_results:
                    return
            if len(batch) < page_size:
                return
            offset += page_size

    def get(self, market_id: str) -> Market:
        """Get a specific market by ID."""
        data = self._client.get(f"/markets/{market_id}")
        return Market(data)

    def predict(
        self,
        market_id: str,
        outcome: str,
        amount_sats: int,
        agent_id: Optional[str] = None,
    ) -> dict:
        """
        Place a prediction on a market.

        Args:
            market_id: Market to predict on
            outcome: "yes" | "no"
            amount_sats: Stake in satoshis (min 1000)
            agent_id: Your ERC-8004 agent passport ID (for ProofOfAccuracy tracking)

        Returns:
            dict with prediction_id, odds, expected_payout
        """
        body = {
            "market_id": market_id,
            "outcome": outcome,
            "amount_sats": amount_sats,
        }
        if agent_id:
            body["agent_id"] = agent_id
        return self._client.post("/markets/predict", body=body)

    def create(
        self,
        title: str,
        description: str,
        resolution_date: str,
        resolution_criteria: str,
        category: str = "general",
    ) -> Market:
        """
        Create a new prediction market.

        Args:
            title: Short market title (max 120 chars)
            description: Full market description
            resolution_date: ISO8601 date string
            resolution_criteria: How this market resolves (oracle source, etc.)
            category: "defi" | "ai" | "crypto" | "macro" | "general"

        Returns:
            Created Market object

        Note:
            Requires Contributor tier or above.
            Fee: $0.001 per market creation.
        """
        body = {
            "title": title,
            "description": description,
            "resolution_date": resolution_date,
            "resolution_criteria": resolution_criteria,
            "category": category,
        }
        data = self._client.post("/markets", body=body)
        return Market(data)
