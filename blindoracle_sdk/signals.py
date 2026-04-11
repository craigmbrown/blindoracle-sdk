"""BlindOracle Signals API — market intelligence and prediction signals."""

from typing import Optional, List


class Signal:
    """A BlindOracle market intelligence signal."""
    def __init__(self, data: dict):
        self.id = data.get("id")
        self.signal_type = data.get("signal_type")      # "risk" | "opportunity" | "neutral"
        self.category = data.get("category")
        self.title = data.get("title")
        self.body = data.get("body")
        self.confidence = data.get("confidence")         # 0.0-1.0
        self.related_markets = data.get("related_markets", [])
        self.chainlink_feed = data.get("chainlink_feed")
        self.generated_at = data.get("generated_at")
        self.raw = data

    def __repr__(self):
        return f"<Signal type={self.signal_type!r} confidence={self.confidence} title={self.title!r}>"


class SignalsAPI:
    """
    Market intelligence signals from BlindOracle's 25-agent analysis network.

    Example:
        # Get latest signal
        signal = client.signals.latest()
        print(signal.title, signal.confidence)

        # Get all DeFi risk signals
        signals = client.signals.list(category="defi", signal_type="risk")
    """

    def __init__(self, client):
        self._client = client

    def latest(self, category: Optional[str] = None) -> Signal:
        """
        Get the most recent market signal.

        Args:
            category: "defi" | "ai" | "crypto" | "macro" (optional filter)

        Returns:
            Most recent Signal
        """
        params = {}
        if category:
            params["category"] = category
        data = self._client.get("/signals/latest", params=params or None)
        return Signal(data)

    def list(
        self,
        category: Optional[str] = None,
        signal_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Signal]:
        """
        List recent market signals.

        Args:
            category: "defi" | "ai" | "crypto" | "macro"
            signal_type: "risk" | "opportunity" | "neutral"
            limit: Max results (default 10)

        Returns:
            List of Signal objects ordered by generated_at desc
        """
        params = {"limit": limit}
        if category:
            params["category"] = category
        if signal_type:
            params["signal_type"] = signal_type
        data = self._client.get("/signals", params=params)
        return [Signal(s) for s in data.get("signals", [])]
