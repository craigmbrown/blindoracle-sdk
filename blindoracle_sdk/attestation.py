"""BlindOracle Attestation API — request a portable W3C Verifiable Credential
for a finished agent-security audit, via the public MCP endpoint.

REQUIRED FLOW (enforced server-side; this client surfaces it):
    1. Onboard + activate the agent  -> ERC-8004 passport  (client.agents)
    2. Run a BlindOracle audit        -> ProofOfAuditReport kind 30105
    3. request_credential(proof_id)   -> W3C VC (this module)

A credential is ONLY issued/served when the audited agent holds an activated,
non-revoked passport AND a real audit proof exists. Skipping step 1 or 2 raises
PassportRequiredError / CredentialNotFoundError.
"""
import json
import urllib.request
import urllib.error

from blindoracle_sdk.exceptions import (
    PassportRequiredError,
    CredentialNotFoundError,
    BlindOracleError,
)

DEFAULT_MCP_URL = "https://api.craigmbrown.com/mcp/attestation"


class AttestationAPI:
    """Client for the BlindOracle Attestation MCP endpoint (get_audit_credential)."""

    def __init__(self, client, mcp_url: str = DEFAULT_MCP_URL):
        self._client = client
        self._mcp_url = mcp_url

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                           "params": params or {}}).encode()
        req = urllib.request.Request(
            self._mcp_url, data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": "blindoracle-sdk/1.x"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=getattr(self._client, "timeout", 30)) as r:
                return json.loads(r.read())
        except urllib.error.URLError as e:  # noqa: BLE001
            raise BlindOracleError(f"attestation endpoint unreachable: {e}")

    def list_tools(self) -> list:
        """MCP tools/list — discover the attestation tools."""
        return self._rpc("tools/list").get("result", {}).get("tools", [])

    def request_credential(self, proof_id: str) -> dict:
        """Return the W3C Verifiable Credential for a finished audit's proof_id.

        Raises:
            PassportRequiredError  — agent lacks an activated ERC-8004 passport.
            CredentialNotFoundError — no credential for proof_id yet (run the audit).
        """
        if not proof_id:
            raise ValueError("proof_id is required")
        resp = self._rpc("tools/call", {"name": "get_audit_credential",
                                        "arguments": {"proof_id": proof_id}})
        if "error" in resp:
            raise BlindOracleError(f"attestation error: {resp['error']}")
        result = resp.get("result", {})
        text = (result.get("content") or [{}])[0].get("text", "")
        if result.get("isError"):
            low = text.lower()
            if "no credential found" in low or "not found" in low:
                raise CredentialNotFoundError(text)
            if "passport" in low:
                raise PassportRequiredError(text)
            raise CredentialNotFoundError(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise BlindOracleError(f"unexpected attestation response: {text[:160]}")

    # alias — the name external callers expect
    get_audit_credential = request_credential
