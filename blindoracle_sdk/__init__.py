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

__version__ = "0.1.0"
__author__ = "Craig Brown"
__email__ = "craigmbrown@gmail.com"
__url__ = "https://craigmbrown.com/blindoracle"

__all__ = [
    "BlindOracleClient",
    "BlindOracleError",
    "AuthenticationError",
    "RateLimitError",
    "MarketNotFoundError",
]
