"""BlindOracle Wallet API — starter-credit token preflight (v0.8).

Verify a bearer ecash token WITHOUT spending it. Wraps the free, read-only
gateway endpoint ``GET /v1/wallet/balance`` (RQ-A2A-EARLY25-05), added after
an external adopter burned three paid attempts discovering a revoked note —
the only way to test a token used to be to spend it.

Example:
    bo = BlindOracleClient(api_key="...", ecash_token=os.environ["BLINDORACLE_ECASH_TOKEN"])
    bal = bo.wallet.balance()
    if bal["status"] == "live":
        print(f"wallet OK: ${bal['remaining_usd']} remaining ({bal['agent']})")
    elif bal["status"] == "revoked":
        raise SystemExit("token is revoked — request a fresh one before any paid call")
"""
from typing import Dict, Optional

_PATH = "/v1/wallet/balance"


class WalletAPI:
    """Starter-credit wallet operations (read-only)."""

    def __init__(self, client):
        self._client = client

    def balance(self, token: Optional[str] = None) -> Dict:
        """Check a starter-credit token's balance — free, never spends.

        Args:
            token: bearer ecash note to check. Defaults to the client's
                   ``ecash_token`` (usually from BLINDORACLE_ECASH_TOKEN).

        Returns a dict with:
            status:        "live" | "revoked" | "unknown"
            agent:         owning agent name (when status == "live")
            budget_usd:    total issued budget (when live)
            remaining_usd: spendable balance (when live; 0.0 when revoked)
            detail:        explanation for revoked/unknown

        Call this BEFORE any paid SKU call — a "revoked" or $0 token will
        never settle, and this tells you in one free round-trip.
        """
        tok = (token or self._client.ecash_token or "").strip()
        if not tok:
            return {"status": "unknown",
                    "detail": "no token: pass token= or set ecash_token / "
                              "BLINDORACLE_ECASH_TOKEN"}
        return self._client._request(
            "GET", _PATH,
            extra_headers={"X-402-Payment": tok},
            base=self._client.gateway_base_url,
        )
