"""
BlindOracle API Client
Core HTTP client with authentication, retries, and x402 payment support.
"""

import json
import os
import random
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional


from blindoracle_sdk._version import user_agent as _user_agent
from blindoracle_sdk.x402 import PAYMENT_HEADER as _X402_HEADER


def _env_float(name: str) -> Optional[float]:
    """Read a float cap from the environment. A malformed value is ignored
    rather than silently treated as zero or unlimited."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


from blindoracle_sdk.exceptions import (
    BlindOracleError,
    AuthenticationError,
    RateLimitError,
    MarketNotFoundError,
    PaymentRequiredError,
    ValidationError,
)
from blindoracle_sdk.markets import MarketsAPI
from blindoracle_sdk.compliance import ComplianceAPI
from blindoracle_sdk.signals import SignalsAPI
from blindoracle_sdk.agents import AgentsAPI
from blindoracle_sdk.audit import AuditAPI
from blindoracle_sdk.privacy import PrivacyAPI
from blindoracle_sdk.metrics import MetricsAPI
from blindoracle_sdk.introductions import IntroductionsAPI
from blindoracle_sdk.attestation import AttestationAPI
from blindoracle_sdk.marketplace import MarketplaceAPI
from blindoracle_sdk.wallet import WalletAPI


class BlindOracleClient:
    """
    BlindOracle API client for autonomous agents.

    Args:
        api_key: Your BlindOracle API key. Get one at craigmbrown.com/blindoracle
        base_url: API base URL. Defaults to production.
        timeout: Request timeout in seconds (default 30).
        max_retries: Number of retries on 429/5xx (default 3).
        ecash_token: Optional x402 Fedimint ecash token for micropayments.

    Example:
        client = BlindOracleClient(api_key="bo_live_...")

        # Free tier — no api_key needed for public endpoints
        client = BlindOracleClient()
        markets = client.markets.list(status="active")
    """

    DEFAULT_BASE_URL = "https://api.craigmbrown.com/v1"
    # RQ-BO-SKU-DOGFOOD-01: derived, never a literal. Three hardcoded User-Agent
    # strings across this SDK ("…/0.8.0", "…/1.x", "…/0.2") meant the gateway
    # could not attribute a call to the SDK build that made it.
    USER_AGENT = _user_agent()

    # Full-jitter exponential backoff (AWS "Exponential Backoff And Jitter").
    # A whole fleet of agents retrying in lockstep is a thundering herd; jitter
    # spreads the retries. Server-directed 429 Retry-After still takes precedence.
    BACKOFF_BASE = 0.5
    BACKOFF_CAP = 20.0

    # v0.2 audit/privacy/metrics live on the a2a marketplace gateway (distinct from /blindoracle/v1)
    DEFAULT_GATEWAY_URL = "https://api.craigmbrown.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
        max_retries: int = 3,
        ecash_token: Optional[str] = None,
        gateway_base_url: str = DEFAULT_GATEWAY_URL,
        wallet_key: Optional[str] = None,
        max_payment_usd: Optional[float] = None,
        session_budget_usd: Optional[float] = None,
    ):
        # Env fallback (matches the LangChain/CrewAI/AutoGen integrations): a bare
        # BlindOracleClient() picks up BLINDORACLE_API_KEY / BLINDORACLE_ECASH_TOKEN.
        self.api_key = api_key or os.environ.get("BLINDORACLE_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.gateway_base_url = gateway_base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.ecash_token = ecash_token or os.environ.get("BLINDORACLE_ECASH_TOKEN")

        # RQ-BO-SDK-X402-PAY-01 — real-funds x402 payment (EIP-3009 on Base).
        # The key is held here only to sign locally; it is never transmitted,
        # logged, or placed in an exception. Caps have NO unlimited default:
        # signing a transfer authorization the caller never bounded is a
        # liability, so an unset cap refuses rather than pays.
        self.wallet_key = wallet_key or os.environ.get("BLINDORACLE_WALLET_KEY")
        self.max_payment_usd = (
            max_payment_usd if max_payment_usd is not None
            else _env_float("BLINDORACLE_MAX_PAYMENT_USD")
        )
        self.session_budget_usd = (
            session_budget_usd if session_budget_usd is not None
            else _env_float("BLINDORACLE_SESSION_BUDGET_USD")
        )
        self.session_spent_usd = 0.0
        #: Append-only record of settled payments this session (no key material).
        self.payments = []

        # Sub-APIs
        self.markets = MarketsAPI(self)
        self.compliance = ComplianceAPI(self)
        self.signals = SignalsAPI(self)
        self.agents = AgentsAPI(self)
        self.audit = AuditAPI(self)  # verifiable on-chain-anchored audits (v0.2)
        self.privacy = PrivacyAPI(self)  # disclosure modes + ZK claims (v0.2)
        self.metrics = MetricsAPI(self)  # accuracy benchmarks + cost/revenue (v0.2)
        self.introductions = IntroductionsAPI(self)
        self.marketplace = MarketplaceAPI(self)  # create/accept SKUs (v0.4)
        self.wallet = WalletAPI(self)  # free token preflight (v0.8)
        self.attestation = AttestationAPI(self)  # Verified Introduction VI-001 (v0.3)
        self.registration = None  # set by BlindOracleClient.register()
        self.agent_id = None

    @classmethod
    def register(
        cls,
        name: str,
        capabilities: list,
        evm_address: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
    ) -> "BlindOracleClient":
        """Self-serve onboarding in one line — mint an ERC-8004 passport + API key
        and return a ready, authenticated client (observer tier).

            bo = BlindOracleClient.register("my-agent", ["verified-introduction"])
            print(bo.agent_id)              # your ERC-8004 agent id
            bo.introductions.request(...)   # already authed

        The raw response (api_key, tier, erc8004_identity) is on ``bo.registration``.
        """
        body = json.dumps(
            {"name": name, "capabilities": capabilities, "evm_address": evm_address}
        ).encode("utf-8")
        url = f"{base_url.rstrip('/')}/agents/register"
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": cls.USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                reg = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise BlindOracleError(
                f"registration failed (HTTP {e.code}): {e.read().decode('utf-8')[:160]}",
                status_code=e.code,
            )
        if reg.get("error") and not reg.get("api_key"):
            raise BlindOracleError(f"registration failed: {reg['error']}")
        client = cls(api_key=reg.get("api_key"), base_url=base_url, timeout=timeout)
        client.registration = reg
        client.agent_id = reg.get("agent_id")
        return client

    def _backoff(self, attempt: int) -> float:
        """Seconds to sleep before retry `attempt` — full jitter, capped."""
        return random.uniform(0.0, min(self.BACKOFF_CAP, self.BACKOFF_BASE * (2**attempt)))

    # --- x402 v2 real-funds payment (RQ-BO-SDK-X402-PAY-01) -----------------

    def _x402_pay(self, body, headers) -> Optional[str]:
        """Parse a 402 challenge, enforce caps, sign, and return the header value.

        Returns ``None`` when this client cannot or must not pay, so the caller
        falls through to the normal :class:`PaymentRequiredError` path with an
        informative message. A cap breach is deliberately re-raised rather than
        swallowed: silently not-paying a call the caller asked for would look
        like a server failure.
        """
        from blindoracle_sdk import x402 as _x402

        try:
            challenge = _x402.parse_challenge(body=body, headers=headers)
        except _x402.UnsupportedPaymentError:
            return None  # message surfaced by _payment_help

        header_value, payload = _x402.build_payment_header(
            challenge,
            private_key=self.wallet_key,
            max_payment_usd=self.max_payment_usd,
            session_budget_usd=self.session_budget_usd,
            session_spent_usd=self.session_spent_usd,
        )
        self.session_spent_usd += challenge.amount_usd
        # Record the authorization, never the key or the signature's provenance.
        self.payments.append({
            "amount_usd": challenge.amount_usd,
            "asset": challenge.asset,
            "network": challenge.network,
            "pay_to": challenge.pay_to,
            "resource": challenge.resource_url,
            "nonce": payload["payload"]["authorization"]["nonce"],
            "valid_before": payload["payload"]["authorization"]["validBefore"],
        })
        return header_value

    def _payment_help(self, detail: str) -> str:
        """A 402 message that names the actual blocker.

        The pre-2026-08-16 message told every caller to "top up ecash", which was
        a dead end for an agent holding a funded Base wallet — the SDK had no
        real-funds path at all (finding F4).
        """
        if not self.wallet_key:
            hint = ("no wallet key configured. For real-funds payment set "
                    "BLINDORACLE_WALLET_KEY (or wallet_key=) to a Base wallet "
                    "holding USDC, and install the signing extra: "
                    "pip install 'blindoracle-sdk[x402]'. Alternatively set "
                    "BLINDORACLE_ECASH_TOKEN for a starter-credit note.")
        elif self.max_payment_usd is None or self.session_budget_usd is None:
            hint = ("a wallet key is configured but spend caps are not. Set "
                    "max_payment_usd and session_budget_usd (or "
                    "BLINDORACLE_MAX_PAYMENT_USD / BLINDORACLE_SESSION_BUDGET_USD) "
                    "— this client will not sign an unbounded transfer authorization.")
        else:
            hint = ("payment was attached but the gateway did not accept it. "
                    "Check the wallet's USDC balance on Base and that the "
                    "authorization had not expired.")
        return f"x402 payment required — {hint} Detail: {detail}"

    def _request(
        self,
        method: str,
        path: str,
        params: dict = None,
        body: dict = None,
        extra_headers: dict = None,
        base: str = None,
    ) -> dict:
        """
        Make an authenticated HTTP request to the BlindOracle API.
        Handles retries, rate limits, and x402 payment headers.
        ``extra_headers`` supports per-request headers like X-402-ZK-Proof (privacy claims).
        ``base`` overrides the base URL (e.g. the a2a gateway for v0.2 audit/privacy/metrics).
        """
        url = f"{(base or self.base_url).rstrip('/')}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.ecash_token:
            headers["X-402-Payment"] = self.ecash_token
        if extra_headers:
            headers.update(extra_headers)

        data = json.dumps(body).encode("utf-8") if body else None

        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, data=data, method=method.upper())
            for k, v in headers.items():
                req.add_header(k, v)

            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                return json.loads(resp.read().decode("utf-8"))

            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    body_text = e.read().decode("utf-8")
                    err_data = json.loads(body_text)
                    message = err_data.get("error", err_data.get("message", body_text))
                except Exception:
                    body_text, err_data = "", {}
                    message = f"HTTP {status}"

                # RQ-BO-SDK-X402-PAY-01 — real-funds x402 v2 (EIP-3009 on Base).
                # Exactly ONE paid attempt: `_x402_paid` short-circuits so a
                # settlement is never retried, which could double-pay.
                if status == 402 and self.wallet_key and not headers.get(_X402_HEADER):
                    paid_header = self._x402_pay(err_data, e.headers)
                    if paid_header:
                        headers[_X402_HEADER] = paid_header
                        continue

                if status == 401:
                    raise AuthenticationError(message, status_code=status)
                elif status == 402:
                    raise PaymentRequiredError(
                        self._payment_help(message), status_code=status,
                    )
                elif status == 404:
                    raise MarketNotFoundError(message, status_code=status)
                elif status == 422:
                    raise ValidationError(message, status_code=status)
                elif status == 429:
                    retry_after = int(e.headers.get("Retry-After", 5))
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise RateLimitError(
                        f"Rate limit exceeded. Retry after {retry_after}s. "
                        f"Upgrade tier at craigmbrown.com/blindoracle",
                        status_code=status,
                    )
                elif status >= 500 and attempt < self.max_retries - 1:
                    time.sleep(self._backoff(attempt))  # full-jitter backoff
                    continue
                else:
                    raise BlindOracleError(message, status_code=status)

            except urllib.error.URLError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self._backoff(attempt))
                    continue
                raise BlindOracleError(f"Network error: {e}")

        raise BlindOracleError("Max retries exceeded")

    def get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict = None, extra_headers: dict = None) -> dict:
        return self._request("POST", path, body=body, extra_headers=extra_headers)

    def patch(self, path: str, body: dict = None) -> dict:
        return self._request("PATCH", path, body=body)

    # --- a2a marketplace gateway (v0.2 audit/privacy/metrics) ---
    def gw_get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params, base=self.gateway_base_url)

    def gw_post(self, path: str, body: dict = None, extra_headers: dict = None) -> dict:
        return self._request(
            "POST", path, body=body, extra_headers=extra_headers, base=self.gateway_base_url
        )
