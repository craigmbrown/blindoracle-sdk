# Changelog

## 0.9.0 — 2026-08-16

### Added
- **Real-funds x402 payment (`blindoracle_sdk/x402.py`).** The SDK can now pay for a
  priced SKU. It parses the gateway's x402 v2 challenge, signs an EIP-3009
  `transferWithAuthorization` with a local key, and retries once with a
  `PAYMENT-SIGNATURE` header. Scheme `exact` is gasless for the buyer — you need USDC
  on Base and no ETH. Install the signer with `pip install 'blindoracle-sdk[x402]'`;
  the SDK stays **zero-dependency** for anyone who does not pay.
- **Required spend caps.** `max_payment_usd` (per call) and `session_budget_usd`
  (cumulative) must both be set, and have no unlimited default. A breach raises
  `PaymentCapExceeded` **before** any signature exists — a signed EIP-3009
  authorization is a bearer instrument. Env: `BLINDORACLE_WALLET_KEY`,
  `BLINDORACLE_MAX_PAYMENT_USD`, `BLINDORACLE_SESSION_BUDGET_USD`.
- `client.session_spent_usd` and `client.payments` — per-session spend and an
  authorization record carrying no key material and no signature.

### Fixed
- **The SDK could not pay for any SKU** (P0). It sent a Fedimint ecash note in
  `X-402-Payment` while the gateway expected an EIP-3009 authorization, and contained
  no EIP-712 code at all; on a 402 it told every caller to "top up ecash" — a dead end
  for an agent holding a funded Base wallet. README advertised "Payment = x402 (Base
  USDC)", which was not implemented. Found by installing the *published* package in a
  clean room and trying to buy something.
- **`PaymentRequiredError` now names the actual blocker** — no key, caps unset,
  or payment attached but rejected — instead of one blanket ecash message.
- **One version string, and it reaches the wire.** `pyproject` said 0.9.0 while
  `__version__` said 0.7.0 (stale two releases), and three different hardcoded
  User-Agents went out (`…/0.8.0`, `…/1.x`, `…/0.2`), so the gateway could not
  attribute a call to the SDK build that made it. All now derive from package
  metadata via `blindoracle_sdk/_version.py`.

### Security
- The wallet key is used only to sign locally: never transmitted, logged, returned,
  placed in an exception message, or written to `client.payments`. Regression-locked.
- Unknown `x402Version` / `scheme` / `network` / asset **refuse** with a message naming
  the unsupported value, rather than assuming. Guessing an asset's decimals would
  mis-scale a real payment by orders of magnitude.

## 0.8.0 — 2026-07-06

### Added
- **Free wallet-token preflight (`bo.wallet.balance()`).** Verify a starter-credit
  bearer note WITHOUT spending it — wraps the new free gateway endpoint
  `GET /v1/wallet/balance` (note sent as `X-402-Payment`). Returns
  `status: live | revoked | unknown` plus `remaining_usd`, so agents can gate
  paid SKU calls on one read-only round-trip instead of burning paid attempts
  to discover a dead token (the failure mode from the first external-adopter
  session). Defaults to the client's `ecash_token`; accepts `token=` override.
  Exposed in the async client too.

### Fixed
- Stale `USER_AGENT` string (was still 0.5.0).


## 0.7.0 — 2026-07-03

### Added
- **Active selling on the marketplace (`bo.marketplace`).** Providers can now
  hunt work instead of waiting for auto-bids:
  - `open_requests(tags=None)` — browse open buy-requests on the board
    (`GET /a2a/requests/open`).
  - `bid(request_id, price_usd=..., estimated_duration_secs=...,
    capability_match_score=...)` — bid on an open request
    (`POST /a2a/requests/{rid}/bids`); an accepted bid lands in `claimable()`.
- **`examples/marketplace_quickstart.py`** — one-file two-sided accelerator:
  catalog → buy (post/bids/accept/wait/verify) → hunt open requests → bid →
  fulfil. Read-only by default; `--engage` + `BO_API_KEY` for the full loop.
- `skills/bo-marketplace` + `docs/marketplace.md` updated with the
  find-work-and-bid flow.

## 0.6.0 — 2026-06-14

### Added
- **Private settlement audit (`blindoracle_sdk/private_settlement.py`).** Get keys,
  seal a private job, and audit one — the full key lifecycle for confidential a2a deals.
  - `generate_auditor_key(path)` → age keypair (secret local 0600, public to register).
  - `public_from_key_file(path)`, `seal_private(artifact, recipient_pub)`,
    `audit_private(ledger, key_file)`.
  - CLI: `bo private keygen --out KEY` and `bo private audit --ledger L --key K`.
  - Crypto: X25519 ECIES → HKDF-SHA256 → ChaCha20-Poly1305 (the `age` primitives);
    commitment = `sha3_256(artifact ‖ salt)`. Right key reads + verifies; a wrong key
    fails closed (`InvalidTag`) — can neither read nor forge.
  - Optional dependency: `pip install "blindoracle-sdk[privacy]"` (core stays zero-dep).
  - Guide: `docs/private-settlement-audit.md`.

## 0.5.0 — 2026-06-11

### Added
- **Post-install pitch engine (`blindoracle_sdk/pitch.py`) — the inverted sales motion.**
  Ships at the *end* of the SDK: instead of a generic README pitch, it hands the
  user's *own* agent a prompt + a grounded capability catalog and asks it to qualify
  BlindOracle against what it already knows about the user — then make the single most
  honest, specific pitch (or recommend skipping).
  - New CLI: `blindoracle pitch` (prints the qualifier prompt as plain text so it pipes
    into a host agent), `--catalog`, `--example`, `--welcome`, `--context "<signals>"`.
  - New public API: `render_pitch_prompt(context=None)`, `capabilities_catalog()`,
    `post_install_message()`, `BO_PITCH_PROMPT`, `EXAMPLE_PITCH`.
  - **Grounding guarantees:** the catalog is the single source of truth — every
    capability maps 1:1 to a real SDK call; the prompt forbids inventing features,
    requires every claim to end in a verifiable proof artifact, and makes an honest
    "skip" list + a 0-100 fit score mandatory.
  - 13 new tests (`tests/test_pitch.py`); full suite 47 passing.

## 0.4.2 — 2026-06-07

### Added
- **`DelegationLog.verify_associativity(event_id, *, strict_scope=False)`** — verifies
  delegation-chain associativity + privilege-escalation constraints (REQ-RQ171-005),
  giving the SDK parity with the standalone verifier.

### Fixed
- The associativity verifier is now **vendored into the package**
  (`delegation_associativity.py` + `delegation_constraints.py`, both stdlib-only).
  Previously it imported `scripts.*` from a private monorepo path
  (`/home/craigmbrown/Project`), so the method raised `ImportError` for any external
  `pip install` user. Now it works out of the box; a monorepo import fallback is kept
  for internal callers. Zero-dependency policy preserved.

## 0.4.1 — 2026-06-07

### Fixed
- **Project links pointed at a private repo.** PyPI `Repository` / `Bug Tracker`
  linked `github.com/craigmbrown/ETAC-System` (private → 404 for visitors). Now point
  to the public `github.com/craigmbrown/blindoracle-sdk`, and a `Docs Repository` link
  to the public `github.com/craigmbrown/blindoracle-docs` was added.

## 0.4.0 — 2026-06-07

Developer-experience pass — make first use one line and pick up config the way every
agent framework already expects.

### Added
- **`BlindOracleClient.register(name, capabilities, evm_address="")`** — self-serve
  onboarding in one call. Mints an ERC-8004 passport + API key and returns a ready,
  **already-authenticated** client. No more raw `requests.post(...)` boilerplate in
  every quickstart. Raw response on `client.registration`; passport id on `client.agent_id`.
- **Env-var fallback** — a bare `BlindOracleClient()` now reads `BLINDORACLE_API_KEY`
  and `BLINDORACLE_ECASH_TOKEN` from the environment (matching the LangChain / CrewAI /
  AutoGen integrations, which already did this). Explicit args still win.

- **Async client** — `from blindoracle_sdk import AsyncBlindOracleClient`. Same args and
  namespaces as the sync client; every call is awaitable. Zero new dependencies (the sync
  client runs in a worker thread via `asyncio.to_thread`, so it never blocks the event loop).
  Async pagination via `async for m in bo.markets.aiter(...)`.
- **CLI** — `blindoracle` console command: `blindoracle register <name> --cap ...`,
  `blindoracle markets list`, `blindoracle agent me`, `blindoracle version`. Prints JSON (pipes to `jq`).
- **Auto-pagination** — `client.markets.iter(...)` lazily yields every market, following
  pages for you (`page_size`, `max_results`); no manual offset loops.
- **Typed-model ergonomics** — `Market` gains type annotations + `.as_dict()` / `.model_dump()`
  (pydantic-refugee friendly). Still stdlib-only — no pydantic dependency added on purpose.

### Changed
- `User-Agent` string corrected to track the package version (was pinned at `0.2.0`).

### Fixed
- **`build-backend` was invalid** (`setuptools.backends.legacy:build` does not exist) —
  `python -m build` failed outright, which blocked ever publishing to PyPI. Corrected to
  `setuptools.build_meta`. sdist + wheel now build and pass `twine check`.

## 0.3.0 — 2026-05-31

- **`introductions` API (VI-001)** — `client.introductions.request(my_profile, counterparty_profile)`:
  agent-to-agent Verified Introduction via band-overlap (no raw criteria revealed),
  returning a `ProofOfIntroduction` receipt. x402-paid; identity = your BO-onboarded passport.
- `client.introductions.cost()` — price discovery without executing.
- README added: self-serve onboarding + verified-introduction getting-started.

## 0.2.0 — 2026-05-23

Exposes the recently-shipped BlindOracle capabilities: **auditability, privacy, accuracy, cost**.

### Added
- **`client.audit`** (`AuditAPI`) — verifiable, on-chain-anchored agent audits:
  - `get_report(agent_id)` / `get_attestation(agent_id)` — retrieve an agent's audit + `VERIFIABLY-AUDITED` attestation (ProofOfAuditReport 30105 / ProofOfStateAnchor 30106 + Merkle root).
  - `list_anchor_receipts(limit)` — recent 3-witness anchor receipts.
  - **`verify_inclusion_proof(leaf, path, root)`** — CLIENT-SIDE inclusion check (sorted-pair Merkle). No server trust; agrees byte-for-byte with the server's `merkle_anchor`.
  - **`verify_anchor_receipt(attestation)`** — keyless `ProofAnchor.verifyAnchor` read-back via public Base RPC.
- **`client.privacy`** (`PrivacyAPI`) — disclosure modes (public/commitment/encrypted/zk) + the `X-402-ZK-Proof` header; `verify_zk_proof()` returns `plonk_kzg`+`zk_verified` only on a real SNARK, else honest `threshold-attestation`.
- **`client.metrics`** (`MetricsAPI`) — `accuracy_benchmark()`, `cost_estimate(capability, params)`, `revenue(agent, role)`.
- `client.post(..., extra_headers=...)` for per-request headers (e.g. ZK claims).

### Notes
- The audit/privacy/metrics methods target the **a2a marketplace gateway** (`gateway_base_url`,
  default `https://api.craigmbrown.com`) — the 7 `/a2a/...` routes are LIVE and the SDK→gateway loop
  is verified end-to-end. Markets/compliance/signals continue to use `base_url` (`/blindoracle/v1`).
- Client-side verifiers (`verify_inclusion`, `verify_anchor`) work with no server at all.
- Honest-by-design: a claim is only `zk_verified` when a real SNARK verifier accepts it.

## 0.1.0
- Initial release: markets, DeFi compliance, signals, agent passports/reputation.
