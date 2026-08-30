"""BlindOracle MCP client — call SKUs over ``POST /v1/mcp`` (v0.10).

The gateway exposes every SKU as an MCP tool (``tool_name_for``: ``.`` → ``_``,
so ``agent.trust-badge`` is ``agent_trust-badge``). Payment carriers, per the
2026-08-29 observer test:

    * USDC x402 payload   -> ``params._meta["x402/payment"]`` (PaymentPayload object)
    * starter-credit note -> ``params._meta["bo/x402-payment"]`` (plain string)
                             or ``arguments.x402_payment``
    * ``arguments._meta`` is NOT honoured.

Identity (2026-08-30): send ``Authorization: Bearer <api_key>`` and the call is
attributed to your passport and limited to the ``tools_needed`` registered for
it — an undeclared tool returns ``tool_not_declared`` and is never charged. A
key that does not resolve is refused (``invalid_api_key``); no key = anonymous.

Example:
    r = bo.mcp.call("agent_trust-badge", {}, x402_payment=os.environ["BLINDORACLE_ECASH_TOKEN"])
    if r["isError"]: print(r["text"])            # a 402 quote, tool_not_declared, ...
    else:            print(r["structured"]["job_id"])
"""
import itertools
from typing import Any, Dict, List, Optional

_ids = itertools.count(1)


def tool_name_for(sku_id: str) -> str:
    """SKU id -> MCP tool name (mirror of the gateway's mapping)."""
    return sku_id.replace(".", "_")


class MCPAPI:
    """Minimal JSON-RPC client for the gateway's MCP surface."""

    PATH = "/v1/mcp"

    def __init__(self, client):
        self._client = client

    def _rpc(self, method: str, params: Optional[Dict] = None) -> Dict:
        body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params or {}}
        # The gateway reads the key from Authorization (set by the client); the
        # starter note must NOT ride on X-402-Payment here — it goes in _meta.
        return self._client.gw_post(self.PATH, body, extra_headers={"X-402-Payment": ""})

    def initialize(self) -> Dict:
        return self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "blindoracle-sdk", "version": "0.10"}})

    def list_tools(self) -> List[Dict]:
        """Every tool with its real ``inputSchema`` (registry-sourced since 2026-08-29)."""
        r = self._rpc("tools/list")
        return list((r.get("result") or {}).get("tools") or [])

    def input_schema(self, sku_or_tool: str) -> Optional[Dict]:
        want = tool_name_for(sku_or_tool)
        for t in self.list_tools():
            if t.get("name") == want:
                return t.get("inputSchema")
        return None

    def call(self, tool: str, arguments: Optional[Dict] = None, *,
             x402_payment: Optional[str] = None, usdc_payment: Optional[Dict] = None) -> Dict:
        """Call one tool. Returns {isError, text, structured, raw}.

        ``x402_payment`` = starter-credit note (string); ``usdc_payment`` = an
        x402 PaymentPayload dict. Pass neither to get the 402 quote (isError=True).
        """
        meta: Dict[str, Any] = {}
        if usdc_payment:
            meta["x402/payment"] = usdc_payment
        elif x402_payment:
            meta["bo/x402-payment"] = x402_payment
        params: Dict[str, Any] = {"name": tool_name_for(tool), "arguments": arguments or {}}
        if meta:
            params["_meta"] = meta
        raw = self._rpc("tools/call", params)
        res = raw.get("result") or {}
        content = res.get("content") or []
        text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return {"isError": bool(res.get("isError")), "text": text,
                "structured": res.get("structuredContent"), "raw": raw}

    def get_result(self, job_id: str) -> Dict:
        return self.call("get_result", {"job_id": job_id})
