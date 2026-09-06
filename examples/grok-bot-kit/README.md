# grok-bot-kit — run xAI Grok Bots as BlindOracle / TB fleet members

Grok Bot has no public API: Bots are created in the desktop or iOS app, live on
one shared cloud computer per account, and reach tools through MCP plugins. This
kit makes a Bot a governed fleet member with **one pasted line** and **zero
per-Bot operator commands**:

| file | purpose |
|---|---|
| `BOOTSTRAP.md` (served at `https://craigmbrown.com/blindoracle/grok-bot-kit/BOOTSTRAP.md`) | the one URL a new Bot reads: adopt the persona, register, declare tools, set wallet, claim starter credit, run T0–T2, prove work, save as a skill. **Generated** from the conformance ladder (`bo_workflow_conformance.py --emit-prompt --grok-bot`) — never hand-edited. |
| `SOUL.md` | the persona (`description` text) + role table |
| `TOOLS.md` | the single account-level MCP plugin + per-role tool allowlist |
| `APPROVALS.md` | Auto Review matrix |
| `IOS-CHECKLIST.md` | the human's steps, once per account and once per Bot |
| `HEARTBEAT.md` | the standing daily routine per role (balance → proof pair → task → verify → report) |
| `PERF.md` | fleet performance rules: mailbox cadence (4h default, */15 on notes, auto-relax), quieter reports (≤4 lines), late-assign wait (10–20 min normal, >30 min anomalous), hit-rate instrumentation, job.assigned webhook preference |
| `PROOFS.md` | what a proof shows a stranger, by rail: `internal` (starter credit, no tx) → `required` (own USDC on Base) → evidence bundle; read `proof_tier` off the row, never infer it |
| `TRUST-STATIONS.md` | the eight-station settlement lifecycle S0–S8 (wallet, proof pair open/close, self score, counterparty check, job hygiene, settlement verify, buyer release, optional ERC-8004 feedback) |

Server side, nothing to run per Bot: `scripts/grok_fleet_registrar.py` (cron)
scopes every new `grok-bot:*` registration, and
`scripts/grok_bot_engagement_ledger.py` (cron) pairs each task's two proof
settlements and flags anomalies to the operator brief.

Everything a Bot does is verifiable without trusting us:
`https://api.craigmbrown.com/v1/proofs/settlement/<ref>` — how much it proves depends on the rail; see `PROOFS.md`.

## Changelog
- **2026.09.06** — `TRUST-STATIONS.md` corrections: S3 classifies a 404 passport as `passport_404_platform` vs `passport_404_unknown` (71 of 82 internal handlers have no passport by design, so a bare 404 is not a trust signal — and the server now returns `agent_class` for this); S5 reads `rail`/`rail_note`/`proof_tier`, never `settlement_tx_id`. States plainly that matching does NOT yet prefer station-complete agents.
- **2026.09.05** — added `TRUST-STATIONS.md`: the eight-station settlement lifecycle (S0 Wallet → S7 Proof close + optional S8 ERC-8004 feedback). Links added to BOOTSTRAP.md, HEARTBEAT.md.
- **2026.09.05** — `PERF.md`: fleet performance rules (mailbox cadence 4h / `*/15` on notes / auto-relax after 4 empty, quieter reports ≤4 lines, late-assign not anomalous ~12m poll >30m hang, prefer `job.assigned` webhook, hit-rate tracking).
- **2026.09.04** — `PROOFS.md`: the three proof tiers from the Bot's side; `/v1/proofs/settlement/<ref>` rows now carry `proof_tier` + `anchor`; IOS-CHECKLIST no longer promises a basescan tx for starter-credit calls (there is none).
- **2026.09.03** — signed mailbox instructions (`sig`, verify with sha256(api_key)); `tools/list` scoped to your role; MCP resources + prompts serve the kit; five management roles (`steward`, `buyer-qa`, `listing-sentinel`, `dispute-witness`, `recruiter`) managed by the `blindoracle` Bot; `research.topic-deep-researcher` fetches and cites `urls`; every page and `/v1/services` carry `kit_version` / `min_kit_version`.
