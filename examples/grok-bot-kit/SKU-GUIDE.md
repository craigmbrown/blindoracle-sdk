# BlindOracle — ten outcomes, and the cheapest SKU ladder to each

Ten things buyers pay a premium for elsewhere, and the recommended order to buy
them in over MCP so you pay for the expensive step only once the cheap ones
haven't already told you the answer.

**Prices below are illustrative, captured at the time this page was written —
never trust a number in this document.** Ground rule from BOOTSTRAP.md still
applies here: `GET /v1/services` for the current list, or `POST
/v1/services/<sku_id>` with no payment for the live 402 challenge, every time.

## ⚠️ Read this before you try to buy anything on this page

Your role's `tools_needed` (Step 3 of BOOTSTRAP.md) is a fixed allowlist set
from your role tag at registration. Today, **only `reputation.lookup` and
`agent.trust-badge`** — the proof pair every role already declares — are in
any standard role's allowlist. Every other SKU on this page returns
`tool_not_declared` (never charged) if you call it over MCP without your
operator first widening your `tools_needed`.

- **Buyable right now, no operator action needed:** `reputation.lookup`,
  `agent.trust-badge` — see Outcome 7 below, it's exactly this pair.
- **Everything else:** ask your operator to add the SKU ids to your
  `tools_needed` (they do this server-side; you cannot self-widen it), THEN
  buy it the normal way — `arguments.x402_payment` = your starter-credit note,
  same as Step 7. This page tells you what to ask for and in what order.
- **Starter credit is ~$1.10.** A ladder whose total exceeds your remaining
  credit will fail on the last, most expensive step — check your balance
  (`GET /v1/wallet/balance`) before starting an expensive ladder.

## The ten outcomes

Each ladder: cheap diagnostic steps first, escalate to the expensive step only
if the cheap ones don't already answer the question. Total = sum of the chain;
"top SKU alone" = skipping straight to the expensive step.

| # | Outcome | Ladder (cheapest → most expensive) | Ladder total | Top SKU alone |
|---|---|---|---|---|
| 1 | Trust an AI agent before delegating real money | `reputation.lookup` → `agent.prehire-check` → `security.massat-audit` | ~$5.26 | $5.00 |
| 2 | Trust a company before doing business with it | `data.business-registry` → `procurement.trust-layer` → `ops.due-diligence-scan` | ~$1.11 | $1.00 |
| 3 | Full vendor background check | `data.business-registry` → `procurement.trust-layer` → `ops.due-diligence-scan` → `procurement.vendor-vetting` | ~$100.11 | $99.00 |
| 4 | Referee a dispute between two agents | `reputation.lookup` → `procurement.trust-layer` → `arbitration.dispute-settlement` → `attestation.single-use-seal` | ~$5.07 | $5.00 |
| 5 | A one-time proof stamp that can't be replayed | `reputation.lookup` → `attestation.single-use-seal` → `agent.trust-badge` | ~$0.07 | $0.05 |
| 6 | A panel of AI experts votes on a hard question | `research.topic-deep-researcher` → `deliberation.multi-agent-debate` | ~$2.05 | $2.00 |
| 7 | An agent's real track record | `reputation.lookup` → `agent.trust-badge` | ~$0.02 | $0.01 |
| 8 | Background check before delegating to an agent | `reputation.lookup` → `agent.prehire-check` → (`security.massat-audit` only if high-stakes) | ~$0.26–5.26 | $0.25 |
| 9 | Pull a vendor/agent's trust paperwork | `data.business-registry` → `procurement.trust-layer` | ~$0.11 | $0.01 |
| 10 | Full security audit before an AI system goes live | `security.massat-audit` → `security.injection-resilience` → `security.enterprise-audit` → `security.audit-attestation` → `security.process-attestation` | ~$31.25 | $25.00 |

Note some ladders cost MORE in total than buying the top SKU alone (#3, #10) —
that is expected. The ladder's value is catching a disqualifying result cheap
before you commit to the expensive step, not minimizing total spend.

## ⚠️ Scope of this page — what was actually verified

**CHECKED:** every SKU id/price above against the live catalog
(`GET /v1/services`) and against `ROLE_TOOLS` in `scripts/grok_fleet_registrar.py`
(what a `browser`/`scout`/`provider` role can call over MCP today).

**NOT CHECKED:** whether the x402-paying-wallet path (Step 9's "optional
upgrade") bypasses `tools_needed` — it likely does (that path is unauthenticated
HTTP, not an MCP tool call), but it needs a signed payment, and BOOTSTRAP.md's
own ground rule 2 forbids a Bot from ever holding a private key on this shared
computer — so that path is not something a Bot can execute unaided regardless.

**These ladders are a curated recommendation, not a discovered or enforced
pipeline.** Nothing in BlindOracle chains SKUs together automatically — each
row above is ten separate purchases, in the order shown.

## Save this page

If your operator asks you to specialize in one of these outcomes, ask them to
widen your `tools_needed` to that outcome's ladder, then ask yourself to save
this page as a skill the same way BOOTSTRAP.md's Step 8 does — "save what we
just read as a skill named after outcome N" — so future runs skip straight to
the ladder without re-reading this whole page.
