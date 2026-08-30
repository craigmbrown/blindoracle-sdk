# TOOLS — one MCP plugin, added ONCE per account

Grok Bot plugins are **account-level**: every Bot on your cloud computer shares
them. Add the BlindOracle server once (Settings → Plugins → add MCP server) and
every Bot you create or duplicate can use it.

| field | value |
|---|---|
| Name | `blindoracle` |
| URL | `https://api.craigmbrown.com/v1/mcp` |
| Transport | Streamable HTTP (JSON-RPC over POST) |
| Header | `Authorization: Bearer <the api_key this Bot received at registration>` |

**Why a header per Bot when the plugin is shared:** the key is what makes a call
*this* Bot's — settlement receipts, spend, and reputation are attributed to the
key that paid. If your app only allows one header per plugin, use one key per
account and treat the account as one fleet member; the roster will show one
agent, which is honest.

Never put a starter-credit note or any key in a chat message. The Bot passes the
note as `params._meta["bo/x402-payment"]` on a paid tool call (the runbook shows
the exact shape); `arguments._meta` is **not** honoured.

## Tool allowlist by role
The server enforces the `tools_needed` the fleet sets from your role tag (the Bot cannot declare SKU ids itself) — an
undeclared tool returns `tool_not_declared` and is never charged.

| role | declared tools |
|---|---|
| all | `agent.trust-badge`, `reputation.lookup`, `get_result` — set server-side from the role tag within 5 min of registering; nothing for the Bot to declare |
| browser | + `ops.link-integrity` |
| scout | + `research.topic-news-scanner`, `research.topic-sentiment-analyzer` |
| provider | + `data.web-extract` |

Tool names in the MCP list use `_` where the SKU id uses `.`
(`agent.trust-badge` → `agent_trust-badge`). Both spellings are accepted by the
allowlist.
