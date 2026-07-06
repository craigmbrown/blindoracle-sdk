"""Async client — ``AsyncBlindOracleClient``.

Zero-dependency async: the sync :class:`BlindOracleClient` (stdlib ``urllib``) is
run in a worker thread via :func:`asyncio.to_thread`, so awaiting a call never
blocks the event loop and we reuse every bit of the sync client's tested retry /
error / x402 logic. No httpx, no aiohttp.

    import asyncio
    from blindoracle_sdk.aio import AsyncBlindOracleClient

    async def main():
        bo = await AsyncBlindOracleClient.register("my-agent", ["verified-introduction"])
        ms = await bo.markets.list(status="active", limit=5)
        async for m in bo.markets.aiter(status="active", max_results=20):
            print(m.title)

    asyncio.run(main())
"""

import asyncio
from typing import AsyncIterator

from blindoracle_sdk.client import BlindOracleClient

_NAMESPACES = (
    "markets",
    "compliance",
    "signals",
    "agents",
    "audit",
    "privacy",
    "metrics",
    "introductions",
    "attestation",
    "wallet",
)


class _AsyncProxy:
    """Wrap a sync namespace so its methods become awaitable.

    A sync generator method named ``iter`` is additionally exposed as an async
    generator ``aiter`` (each ``next()`` runs in a thread).
    """

    def __init__(self, target):
        self._t = target

    def __getattr__(self, name):
        attr = getattr(self._t, name)
        if callable(attr):

            async def _call(*args, **kwargs):
                return await asyncio.to_thread(attr, *args, **kwargs)

            return _call
        return attr

    def aiter(self, *args, **kwargs) -> AsyncIterator:
        """Async wrapper over a sync ``iter(...)`` generator (e.g. markets.aiter)."""
        gen = self._t.iter(*args, **kwargs)
        _sentinel = object()

        async def _agen():
            while True:
                item = await asyncio.to_thread(next, gen, _sentinel)
                if item is _sentinel:
                    return
                yield item

        return _agen()


class AsyncBlindOracleClient:
    """Async facade over :class:`BlindOracleClient`. Same args, same namespaces."""

    def __init__(self, *args, **kwargs):
        self._wrap(BlindOracleClient(*args, **kwargs))

    def _wrap(self, sync: BlindOracleClient) -> "AsyncBlindOracleClient":
        self._sync = sync
        for ns in _NAMESPACES:
            setattr(self, ns, _AsyncProxy(getattr(sync, ns)))
        return self

    # passthrough identity / config
    @property
    def api_key(self):
        return self._sync.api_key

    @property
    def agent_id(self):
        return self._sync.agent_id

    @property
    def registration(self):
        return self._sync.registration

    @classmethod
    async def register(
        cls,
        name,
        capabilities,
        evm_address: str = "",
        base_url: str = BlindOracleClient.DEFAULT_BASE_URL,
        timeout: int = 30,
    ) -> "AsyncBlindOracleClient":
        """Async one-line onboarding — see :meth:`BlindOracleClient.register`."""
        sync = await asyncio.to_thread(
            BlindOracleClient.register, name, capabilities, evm_address, base_url, timeout
        )
        return cls.__new__(cls)._wrap(sync)

    async def get(self, path, params=None):
        return await asyncio.to_thread(self._sync.get, path, params)

    async def post(self, path, body=None, extra_headers=None):
        return await asyncio.to_thread(self._sync.post, path, body, extra_headers)
