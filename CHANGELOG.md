# Changelog

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
