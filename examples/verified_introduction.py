"""BlindOracle SDK — Verified Introduction (VI-001) example.

End-to-end: self-serve onboarding -> verified introduction -> ProofOfIntroduction.
Run: python examples/verified_introduction.py
"""
import requests

from blindoracle_sdk import BlindOracleClient

API = "https://api.craigmbrown.com"

# ── 1. Self-serve onboarding — get your ERC-8004 passport + API key ──────────
reg = requests.post(f"{API}/v1/agents/register", json={
    "name": "demo-introduction-agent",
    "capabilities": ["verified-introduction"],
}).json()
print("registered:", reg["agent_id"], "(tier:", reg.get("tier"), ")")

bo = BlindOracleClient(api_key=reg["api_key"])
me = bo.agents.me()

# ── 2. Request a verified introduction to another BO-registered agent ────────
# Each side supplies its own criteria BANDS — overlap is computed without either
# side revealing exact values. tolerance>0 lets a band flex to find common ground.
receipt = bo.introductions.request(
    my_profile={
        "agent_id": me.agent_id,
        "category": "dating-concierge",
        "intent": "collab",
        "bands": {"age": [29, 39], "radius_mi": [0, 20]},
    },
    counterparty_profile={
        "agent_id": "agent_...",   # <- a counterparty's BO passport id
        "bands": {"age": [31, 42], "radius_mi": [0, 25]},
    },
    tolerance=8,
)

# ── 3. Read the receipt ─────────────────────────────────────────────────────
print("status:", receipt["status"])                       # matched | no_overlap
print("matched dims:", receipt.get("matched_dimensions"))  # never the raw values
print("ProofOfIntroduction:", receipt.get("introduction_id"))
print("powered_by:", receipt.get("powered_by"))
