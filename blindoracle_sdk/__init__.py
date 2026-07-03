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
from blindoracle_sdk.aio import AsyncBlindOracleClient
from blindoracle_sdk.markets import Market
from blindoracle_sdk.exceptions import (
    BlindOracleError,
    AuthenticationError,
    RateLimitError,
    MarketNotFoundError,
    PaymentRequiredError,
    ValidationError,
    PassportRequiredError,
    CredentialNotFoundError,
)
from blindoracle_sdk.audit import AuditAPI, AuditAttestation, verify_inclusion, verify_anchor
from blindoracle_sdk.marketplace import MarketplaceAPI, ServiceRequest, Job
from blindoracle_sdk.skill_marketplace import SkillMarketplaceAPI, SkillPurchase
from blindoracle_sdk.privacy import PrivacyAPI, DISCLOSURE_MODES, ZK_CLAIM_TYPES
from blindoracle_sdk import private_settlement
from blindoracle_sdk.private_settlement import generate_auditor_key, seal as seal_private, audit as audit_private, public_from_key_file
from blindoracle_sdk.metrics import MetricsAPI
from blindoracle_sdk.delegation import (
    DelegationLog,
    verify_signature,
    delegation_signature,
    delegator_passport_hash,
    DELEGATION_KIND,
)

__version__ = "0.7.0"
__author__ = "Craig Brown"
__email__ = "craigmbrown@gmail.com"
__url__ = "https://craigmbrown.com/blindoracle"

# Imported AFTER __version__ is set — pitch.py reads __version__ at import time.
from blindoracle_sdk import pitch  # noqa: E402
from blindoracle_sdk.pitch import (  # noqa: E402
    render_pitch_prompt,
    capabilities_catalog,
    post_install_message,
    BO_PITCH_PROMPT,
    EXAMPLE_PITCH,
)

__all__ = [
    "BlindOracleClient",
    "AsyncBlindOracleClient",
    "Market",
    "BlindOracleError",
    "AuthenticationError",
    "RateLimitError",
    "MarketNotFoundError",
    "PaymentRequiredError",
    "ValidationError",
    "PassportRequiredError",
    "CredentialNotFoundError",
    "AuditAPI",
    "AuditAttestation",
    "MarketplaceAPI",
    "ServiceRequest",
    "Job",
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
    "pitch",
    "render_pitch_prompt",
    "capabilities_catalog",
    "post_install_message",
    "BO_PITCH_PROMPT",
    "EXAMPLE_PITCH",
]
