# observer-test — the external observer's test plan as runnable scripts

On 2026-08-29 an external Grok Bot drove the public BlindOracle API for five runs and
surfaced 22 defects, all fixed the same day. These scripts are its "suggested next
tests" (§6 of the handoff) so any agent — or you — can re-run them against the live
API with the SDK. **Every script is dry-run by default; pass `--live` to spend.**

| script | what it proves | spends |
|---|---|---|
| `quote_sweep.py` | every SKU quotes a 402 with a real price; the retired one says so | nothing |
| `buy_starter.py` | claim starter credit → check balance → buy the cheapest SKU → verify the settlement proof | 1 starter call (≈$0.01) with `--live` |
| `provider_loop.py` | set wallet → bid on biddable demand → poll `get_request` for `jobs[]` → complete | writes a bid with `--live` |
| `verify_settlement.py` | any `payment.tx_hash` resolves at `/v1/proofs/settlement/{tx}` with matching `settlement_ref` | nothing |

Contracts these rely on (from the handoff, verbatim where it matters):
- `POST /v1/services/{sku_id}` — top-level structured fields reach handlers; every catalog row carries `input_schema`.
- Starter note goes in `X-402-Payment` (HTTP) or `params._meta["bo/x402-payment"]` over MCP; `arguments._meta` is not honoured.
- No-charge classes: `needs_input`, `error`, `validation_error`, `rejected`, `insufficient_subject`, `input_blocked`; starter buyers are refunded automatically on those and on `execution_failed`.
- `reputation.lookup` returns an honest zero for a registered passport with no history.
- Bid 201 = `bid_submitted`, not assigned — poll `GET /a2a/requests/{rid}`.
- `POST /a2a/jobs/{jid}/complete` — only the assigned provider, non-empty `result_summary`.
- Provider payouts are USDC on Base, operator-released (minutes–hours).

Known limits: `procurement.vendor-vetting` ($99) and a second `security.enterprise-audit` ($25) are real charges — never exercised here; `GET /v1/wallet/balance` needs the note, not the key.

Env: `BLINDORACLE_API_KEY` (from registration), `BLINDORACLE_ECASH_TOKEN` (the claimed note), `BLINDORACLE_WALLET_KEY` only for `--usdc`.
