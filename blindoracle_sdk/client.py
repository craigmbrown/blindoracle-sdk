"""
BlindOracle API Client
Core HTTP client with authentication, retries, and x402 payment support.
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional

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
    USER_AGENT = f"blindoracle-sdk-python/0.2.0"

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
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.gateway_base_url = gateway_base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.ecash_token = ecash_token

        # Sub-APIs
        self.markets = MarketsAPI(self)
        self.compliance = ComplianceAPI(self)
        self.signals = SignalsAPI(self)
        self.agents = AgentsAPI(self)
        self.audit = AuditAPI(self)        # verifiable on-chain-anchored audits (v0.2)
        self.privacy = PrivacyAPI(self)    # disclosure modes + ZK claims (v0.2)
        self.metrics = MetricsAPI(self)    # accuracy benchmarks + cost/revenue (v0.2)
        self.introductions = IntroductionsAPI(self)
        self.attestation = AttestationAPI(self)  # Verified Introduction VI-001 (v0.3)

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
                    message = f"HTTP {status}"

                if status == 401:
                    raise AuthenticationError(message, status_code=status)
                elif status == 402:
                    raise PaymentRequiredError(
                        f"x402 payment required. Top up ecash at craigmbrown.com/blindoracle. Detail: {message}",
                        status_code=status,
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
                    time.sleep(2 ** attempt)  # exponential backoff
                    continue
                else:
                    raise BlindOracleError(message, status_code=status)

            except urllib.error.URLError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
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
        return self._request("POST", path, body=body, extra_headers=extra_headers,
                             base=self.gateway_base_url)
