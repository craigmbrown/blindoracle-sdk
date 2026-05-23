# Changelog

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
