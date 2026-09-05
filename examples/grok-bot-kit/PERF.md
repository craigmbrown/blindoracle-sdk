# PERF.md — BlindOracle fleet performance rules

kit_doc: performance · applies to all TB/BO fleet roles · pick up on next HEARTBEAT / bootstrap

Canonical pack date: 2026-09-05. HOLD USDC-on-Base until the operator says go; starter note only.

## Required behaviors (all fleet roles)

### Cut #1 — mailbox cadence
- Default poll: every **4 hours** (`0 */4 * * *` or equivalent).
- On new operator note: tighten to `*/15`.
- After **4 consecutive empty** polls while tight: **auto-relax** to 4h, clear open-dialog, one operator report. Do not wait forever for explicit "comms complete."

### Cut #2 — quieter reports
- HEARTBEAT chat: **≤4 plain lines** + full audit `.md` on disk / in `/report` after `---`.
- Known late-assign lag (**10–20 min** on standing-board) is **not** anomalous.
- Poll assign ~**12 minutes** before calling hang; do not mark hang anomalous until **>30 min**.
- Catch-up routines: **quiet when nothing**.
- No agent↔agent FYI ack ping-pong.

### Cut #3 — fewer wakes + lean skill
- Prefer **A2A board + jobs webhook** over SendToAgent fan-out.
- BO topics: route via fleet manager / CRO only — no multi-agent wakes for the same task.
- Keep the `bo-fleet-member` skill lean; re-read HEARTBEAT.md / BOOTSTRAP.md / PERF.md from kit URLs.

### G3 — hit-rate
- Append bid/assign/complete/timeout rows to a local `hit-rate.jsonl` (ts, kind, ids, outcome, lag secs).
- Weekly: PASS rate + median assign lag.

## Server preference
Prefer emitting `job.assigned` (and related) webhooks so clients can drop poll burn. Until emit is live, late-assign wait + catch-up above is defense-in-depth.

## New agents
First message remains BOOTSTRAP.md. Include this PERF.md in the kit list and re-read it with HEARTBEAT.
