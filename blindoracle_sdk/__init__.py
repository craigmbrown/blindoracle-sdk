"""
BlindOracle SDK
Chainlink-verified prediction markets for autonomous agents.

Usage:
    from blindoracle_sdk import BlindOracleClient

    client = BlindOracleClient(api_key="your_key")

    # Get active markets
    markets = client.markets.list()

    # Run DeFi compliance check
    result = client.compliance.check("0xProtocolAddress")

    # Get market signal
    signal = client.signals.latest()
"""

from blindoracle_sdk.client import BlindOracleClient
from blindoracle_sdk.exceptions import (
    BlindOracleError,
    AuthenticationError,
    RateLimitError,
    MarketNotFoundError,
)
from blindoracle_sdk.audit import AuditAPI, AuditAttestation, verify_inclusion, verify_anchor
from blindoracle_sdk.privacy import PrivacyAPI, DISCLOSURE_MODES, ZK_CLAIM_TYPES
from blindoracle_sdk.metrics import MetricsAPI
from blindoracle_sdk.delegation import (
    DelegationLog,
    verify_signature,
    delegation_signature,
    delegator_passport_hash,
    DELEGATION_KIND,
)

__version__ = "0.3.0"
__author__ = "Craig Brown"
__email__ = "craigmbrown@gmail.com"
__url__ = "https://craigmbrown.com/blindoracle"

__all__ = [
    "BlindOracleClient",
    "BlindOracleError",
    "AuthenticationError",
    "RateLimitError",
    "MarketNotFoundError",
    "AuditAPI",
    "AuditAttestation",
    "verify_inclusion",
    "verify_anchor",
    "PrivacyAPI",
    "DISCLOSURE_MODES",
    "ZK_CLAIM_TYPES",
    "MetricsAPI",
    "DelegationLog",
    "verify_signature",
    "delegation_signature",
    "delegator_passport_hash",
    "DELEGATION_KIND",
]
