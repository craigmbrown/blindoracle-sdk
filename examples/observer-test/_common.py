"""Shared bits for the observer-test scripts (no secrets, no network at import)."""
import argparse
import os
import sys


def client(require_key: bool = False):
    from blindoracle_sdk import BlindOracleClient
    key = os.environ.get("BLINDORACLE_API_KEY")
    if require_key and not key:
        sys.exit("BLINDORACLE_API_KEY is required (POST /v1/agents/register gives you one)")
    return BlindOracleClient(api_key=key, ecash_token=os.environ.get("BLINDORACLE_ECASH_TOKEN"))


def args(desc: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--live", action="store_true", help="actually spend / write state (default: dry-run)")
    ap.add_argument("--sku", default="agent.trust-badge")
    ap.add_argument("--limit", type=int, default=5)
    return ap.parse_args()
