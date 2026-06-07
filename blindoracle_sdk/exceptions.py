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


class PassportRequiredError(BlindOracleError):
    """Raised when an attestation credential is requested for an agent that has
    not completed the required flow: onboard + activate an ERC-8004 passport AND
    run a BO audit (ProofOfAuditReport 30105) before requesting the credential."""


class CredentialNotFoundError(BlindOracleError):
    """Raised when no attestation credential exists for the given proof_id yet —
    the audit must be finished and dual-emitted first."""
