"""bo.inbox (RQ-BO-INBOX-STATUS-01): status / check / watch against a fake transport."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from blindoracle_sdk import BlindOracleClient  # noqa: E402
from blindoracle_sdk.inbox import InboxAPI  # noqa: E402


class FakeTransport:
    def __init__(self, script):
        self.script = list(script)  # [(path_suffix, code, body)]
        self.calls = []

    def __call__(self, path, params=None, etag=None, timeout=30.0):
        self.calls.append((path, params, etag))
        want, code, body = self.script.pop(0)
        assert path.endswith(want), (path, want)
        return code, body


def _inbox(script):
    bo = BlindOracleClient(api_key="k")
    t = FakeTransport(script)
    bo.inbox._get = t
    return bo.inbox, t


def test_client_has_inbox():
    assert isinstance(BlindOracleClient(api_key="k").inbox, InboxAPI)


def test_status_returns_body_and_caps_wait():
    ib, t = _inbox([("/instructions/status", 200, {"unread": 2, "etag": '"e1"'})])
    assert ib.status("bo-x", wait=999)["unread"] == 2
    assert t.calls[0][1] == {"wait": 25}


def test_status_304_is_none():
    ib, _ = _inbox([("/instructions/status", 304, None)])
    assert ib.status("bo-x", wait=5, etag='"e1"') is None


def test_status_error_raises():
    ib, _ = _inbox([("/instructions/status", 401, {"error": "auth_required"})])
    with pytest.raises(RuntimeError):
        ib.status("bo-x")


def test_agent_from_env(monkeypatch):
    monkeypatch.setenv("BLINDORACLE_AGENT", "env-agent")
    ib, t = _inbox([("/instructions/status", 200, {"unread": 0, "etag": '"e"'})])
    ib.status()
    assert "/a2a/agents/env-agent/" in t.calls[0][0]


def test_agent_required(monkeypatch):
    monkeypatch.delenv("BLINDORACLE_AGENT", raising=False)
    with pytest.raises(ValueError):
        BlindOracleClient(api_key="k").inbox.status()


def test_check_peek_param():
    ib, t = _inbox([("/instructions", 200, {"messages": []})])
    ib.check("bo-x", peek=True)
    assert t.calls[0][1] == {"peek": 1}


def test_watch_reads_only_when_unread_and_survives_errors():
    ib, t = _inbox([
        ("/instructions/status", 200, {"unread": 0, "etag": '"a"'}),
        ("/instructions/status", 304, None),                           # nothing changed
        ("/instructions/status", 500, {"error": "boom"}),              # network/server blip
        ("/instructions/status", 200, {"unread": 1, "etag": '"b"'}),
        ("/instructions", 200, {"messages": [{"msg_id": "m1"}]}),
    ])
    sleeps = []
    got = []
    it = ib.watch("bo-x", sleep=sleeps.append)
    got.append(next(it))
    assert got[0]["messages"][0]["msg_id"] == "m1"
    assert sleeps == [5.0]  # one backoff after the 500
    full_reads = [c for c in t.calls if c[0].endswith("/instructions")]
    assert len(full_reads) == 1
    assert t.calls[1][2] == '"a"'  # second status sent the etag


def test_watch_stop():
    ib, _ = _inbox([])
    assert list(ib.watch("bo-x", stop=lambda: True)) == []
