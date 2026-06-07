"""v0.4.0 DX extras: full-jitter backoff, pagination iter, async client, CLI."""

import asyncio
import json
import io

import pytest

from blindoracle_sdk import BlindOracleClient, AsyncBlindOracleClient, Market
from blindoracle_sdk.aio import _AsyncProxy
from blindoracle_sdk import cli

# --- full-jitter backoff ----------------------------------------------------


def test_backoff_within_full_jitter_bounds():
    c = BlindOracleClient(api_key="x")
    for attempt in range(5):
        cap = min(c.BACKOFF_CAP, c.BACKOFF_BASE * (2**attempt))
        for _ in range(50):
            d = c._backoff(attempt)
            assert 0.0 <= d <= cap


def test_backoff_capped():
    c = BlindOracleClient(api_key="x")
    assert c._backoff(30) <= c.BACKOFF_CAP


# --- pagination iter() ------------------------------------------------------


class _PagingClient:
    """Fake transport: 50 markets across pages of `page_size`."""

    def __init__(self, total, page_size_seen=None):
        self.total = total
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        off = params["offset"]
        lim = params["limit"]
        rows = [{"id": f"m{i}", "title": f"M{i}"} for i in range(off, min(off + lim, self.total))]
        return {"markets": rows}


def test_iter_follows_pages():
    from blindoracle_sdk.markets import MarketsAPI

    api = MarketsAPI(_PagingClient(total=120))
    got = list(api.iter(page_size=50))
    assert len(got) == 120
    assert all(isinstance(m, Market) for m in got)


def test_iter_respects_max_results():
    from blindoracle_sdk.markets import MarketsAPI

    pc = _PagingClient(total=1000)
    api = MarketsAPI(pc)
    got = list(api.iter(page_size=50, max_results=10))
    assert len(got) == 10
    assert pc.calls == 1  # stopped within the first page


def test_iter_empty():
    from blindoracle_sdk.markets import MarketsAPI

    assert list(MarketsAPI(_PagingClient(total=0)).iter(page_size=50)) == []


# --- async client -----------------------------------------------------------


def test_async_namespaces_present():
    bo = AsyncBlindOracleClient(api_key="x")
    for ns in ("markets", "agents", "audit", "attestation", "introductions"):
        assert isinstance(getattr(bo, ns), _AsyncProxy)


def test_async_method_is_awaitable():
    bo = AsyncBlindOracleClient(api_key="x")
    # wrap a known sync method (markets.list) over a fake transport
    bo._sync.markets._client = _PagingClient(total=3)

    async def run():
        return await bo.markets.list(limit=50)

    out = asyncio.run(run())
    assert len(out) == 3


def test_async_aiter():
    bo = AsyncBlindOracleClient(api_key="x")
    bo._sync.markets._client = _PagingClient(total=7)

    async def run():
        return [m.id async for m in bo.markets.aiter(page_size=5)]

    ids = asyncio.run(run())
    assert ids == [f"m{i}" for i in range(7)]


def test_async_passthrough_identity():
    bo = AsyncBlindOracleClient(api_key="kk")
    assert bo.api_key == "kk"
    assert bo.agent_id is None
    assert bo.registration is None


# --- CLI --------------------------------------------------------------------


def test_cli_version(capsys):
    rc = cli.main(["version"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "blindoracle_sdk" in out


def test_cli_no_command_returns_1():
    assert cli.main([]) == 1


def test_cli_markets_list(monkeypatch, capsys):
    monkeypatch.setattr(
        BlindOracleClient,
        "get",
        lambda self, path, params=None: {
            "markets": [
                {"id": "m1", "title": "ETH 5k?", "yes_probability": 0.6, "status": "active"}
            ]
        },
    )
    rc = cli.main(["markets", "list", "--limit", "1"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["id"] == "m1"
