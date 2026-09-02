# APPROVALS — Auto Review matrix (set once per account, re-check after duplicating a Bot)

Grok Bot's Auto Review rules are the Bot-side control; BlindOracle's server-side
gates (key binding, tool allowlist, starter-credit budget, refunds on failure)
are the other half. Neither trusts the other.

| action | rule |
|---|---|
| `agent_trust-badge`, `reputation_lookup`, `get_result`, any GET | **Always Allow** — reads and the two proof calls, $0.01 each |
| any other blindoracle tool call (a paid SKU) | **Require Approval** |
| browser: sending a message, submitting a form, making a payment | **Require Approval** |
| browser: sign-in, 2FA, CAPTCHA, payment card | **take over manually** (Grok Bot already forces this) |
| running commands on your local computer | **Never allow** |
| writing a credential or cookie anywhere | **Require Approval** — and the answer is no |

Suggested standing sentence for every task: *"Ask for approval before any send,
submit, or spend; the two proof calls are pre-approved."*

⚠️ **Duplicating a Bot copies its profile, skills and routines** — re-open Auto
Review on the copy and confirm nothing widened. Auto-review rules live on the
desktop that set them; on iPhone confirm the copy prompts for approval on its
first paid call.
