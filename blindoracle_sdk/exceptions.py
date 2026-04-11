"""BlindOracle SDK exceptions."""


class BlindOracleError(Exception):
    """Base exception for all BlindOracle SDK errors."""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class AuthenticationError(BlindOracleError):
    """API key missing, invalid, or expired."""
    pass


class RateLimitError(BlindOracleError):
    """Rate limit exceeded. Upgrade tier or wait for reset."""
    pass


class MarketNotFoundError(BlindOracleError):
    """Requested market ID does not exist."""
    pass


class PaymentRequiredError(BlindOracleError):
    """HTTP 402 — x402 payment required. Top up ecash balance."""
    pass


class ValidationError(BlindOracleError):
    """Request parameters invalid."""
    pass
