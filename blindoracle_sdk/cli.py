"""``blindoracle`` command-line interface — try the marketplace before you code.

    blindoracle version
    blindoracle register my-agent --cap verified-introduction --cap research
    blindoracle markets list --status active --limit 5
    blindoracle agent me            # uses BLINDORACLE_API_KEY from env

Thin wrapper over the SDK; prints JSON so output pipes into ``jq``.
"""

import argparse
import json
import sys

from blindoracle_sdk import BlindOracleClient, __version__
from blindoracle_sdk.exceptions import BlindOracleError


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _cmd_version(args) -> int:
    _print({"blindoracle_sdk": __version__})
    return 0


def _cmd_register(args) -> int:
    bo = BlindOracleClient.register(args.name, args.cap, evm_address=args.evm or "")
    _print(
        {
            "agent_id": bo.agent_id,
            "api_key": bo.api_key,
            "tier": (bo.registration or {}).get("tier"),
            "hint": "export BLINDORACLE_API_KEY=<api_key> to reuse this identity",
        }
    )
    return 0


def _cmd_markets_list(args) -> int:
    bo = BlindOracleClient(api_key=args.api_key)
    ms = bo.markets.list(status=args.status, category=args.category, limit=args.limit)
    _print(
        [
            {"id": m.id, "title": m.title, "yes_probability": m.yes_probability, "status": m.status}
            for m in ms
        ]
    )
    return 0


def _cmd_agent_me(args) -> int:
    bo = BlindOracleClient(api_key=args.api_key)
    me = bo.agents.me()
    _print(me.raw if hasattr(me, "raw") else me)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="blindoracle", description="BlindOracle agent-marketplace CLI")
    p.add_argument(
        "--api-key", dest="api_key", default=None, help="API key (else BLINDORACLE_API_KEY env)"
    )
    sub = p.add_subparsers(dest="command")

    sub.add_parser("version", help="print SDK version").set_defaults(func=_cmd_version)

    pr = sub.add_parser("register", help="self-serve onboard -> ERC-8004 passport + key")
    pr.add_argument("name")
    pr.add_argument(
        "--cap", action="append", default=[], required=True, help="capability (repeatable)"
    )
    pr.add_argument("--evm", default=None, help="optional EVM address")
    pr.set_defaults(func=_cmd_register)

    pm = sub.add_parser("markets", help="market operations")
    msub = pm.add_subparsers(dest="markets_command")
    ml = msub.add_parser("list", help="list markets")
    ml.add_argument("--status", default="active")
    ml.add_argument("--category", default=None)
    ml.add_argument("--limit", type=int, default=20)
    ml.set_defaults(func=_cmd_markets_list)

    pa = sub.add_parser("agent", help="agent operations")
    asub = pa.add_subparsers(dest="agent_command")
    asub.add_parser("me", help="your passport + reputation").set_defaults(func=_cmd_agent_me)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 1
    try:
        return args.func(args)
    except BlindOracleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
