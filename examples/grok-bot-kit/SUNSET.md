# SUNSET.md — routines BlindOracle now runs for the fleet

Your weekly usage allowance is shared by every Bot on the account. A routine that repeats work
the BO server already does costs the whole fleet and moves everyone closer to a usage-guard freeze.

## Keep: public content is your job
Searching, scanning and reading public pages, X, news, feeds and listings, then passing the
signal to BO, stays with you. You read untrusted content on your VM so the server does not have
to. Never list these routines for sunset. When the usage guard is at T2 or above, halve their
cadence instead and restore it after the weekly reset.

## Sunset: the server does these now
| your routine looks like | BO runs instead | status |
| --- | --- | --- |
| board watch, board-watch, late-assign | a2a_board_watch (every 30 min) + gb_customer_success board intake (every 10 min) | LIVE |
| freeze, resume, rate-limit-t | none needed: one-shot freeze/resume routines are finished once they fire | LIVE |
| perf-digest, perf digest, github-backup | bo_fleet_margin_dashboard (daily 13:30 UTC) and the server's own backups | LIVE |

## What to do
On the first weekday heartbeat of the week, for each enabled routine that matches a `LIVE` row,
write `SUNSET: <routine> → <BO job> · fires/week <n>` in your report. For a routine that
produced nothing useful in 7 days, write `SUNSET: idle <routine>`. If nothing matches, write
`SUNSET: none`. Do not pause anything until a mailbox note from gb-customer-success confirms it.
Then pause it in the app (pause, do not delete) and report `SUNSET-DONE: <routine> paused`.
Never list your HEARTBEAT, persona export or usage-guard routine.

