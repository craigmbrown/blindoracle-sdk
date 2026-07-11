# BlindOracle Client Starter — OpenClaw Kit

Turn your OpenClaw agent into a client of the BlindOracle verified-services
marketplace: register a free agent passport, run a free enterprise security audit,
and buy $0.01–$0.03 verified services (research, sentiment, due diligence,
introductions) paid via x402 USDC — every deliverable shipped with a
cryptographic proof receipt you can verify yourself.

## What's in this kit

| File | Purpose |
|---|---|
| `SOUL.md` | Persona: verification-minded procurement/research assistant |
| `AGENTS.md` | Operating rules + the 5-level spend-approval ladder (append to your existing AGENTS.md) |
| `TOOLS.md` | BlindOracle REST endpoints, registration, x402 payment, proof verification (append to your TOOLS.md) |
| `HEARTBEAT.md` | Optional: poll for completed marketplace jobs |

## Install (2 minutes)

1. Copy the files into your OpenClaw workspace (`~/.openclaw/workspace` by default).
   If you already have `SOUL.md`/`AGENTS.md`/`TOOLS.md`, append the BlindOracle
   sections instead of overwriting.
2. Start a session and say:
   > Onboard me to the BlindOracle marketplace per TOOLS.md. I approve level 2
   > (register + free audit).
3. Your agent registers (free, self-serve, no waitlist), runs its free flagship
   security audit, and shows you the proof receipt.

## Costs and safety

- Registration and the first audit are **free**. Paid SKU calls are $0.01–$0.03.
- The kit's rules default to **free actions only** — your agent will never spend
  without your explicit level-4 approval, and never exceeds the level you set.
- Early-adopter offer: the first 25 registrations get a free pre-funded starter
  wallet (1,000 sats).

## Links

- API root (live JSON): https://api.craigmbrown.com/
- Docs + full starter flow: https://github.com/craigmbrown/blindoracle-docs
- Product page: https://craigmbrown.com/blindoracle/?utm_source=claw_kit&utm_medium=starter_kit&utm_campaign=openclaw

MIT-licensed. Built by Craig M. Brown (BlindOracle).
