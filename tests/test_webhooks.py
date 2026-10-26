"""blindoracle_sdk.webhooks.verify + MarketplaceAPI.register_callback (RQ-BO-CALLBACK-ADOPTION-01)."""
import hashlib
import hmac

import pytest

from blindoracle_sdk import webhooks
from blindoracle_sdk.marketplace import MarketplaceAPI

BODY = b'{"event":"job.completed","job_id":"j1"}'


def _sig(key: bytes, body: bytes = BODY) -> str:
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def test_agent_alg_verifies_with_api_key():
    key = hashlib.sha256(b"k1").hexdigest().encode()
    h = {"X-BO-Signature": _sig(key), "X-BO-Signature-Alg": webhooks.ALG_AGENT}
    assert webhooks.verify(BODY, h, api_key="k1")
    assert webhooks.verify(BODY.decode(), {k.lower(): v for k, v in h.items()}, api_key="k1")
    assert not webhooks.verify(BODY, h, api_key="k2")
    assert not webhooks.verify(BODY + b"x", h, api_key="k1")


def test_job_alg_verifies_with_callback_secret():
    h = {"X-BO-Signature": _sig(b"sec"), "X-BO-Signature-Alg": webhooks.ALG_JOB}
    assert webhooks.verify(BODY, h, callback_secret="sec")
    assert not webhooks.verify(BODY, h, api_key="sec")  # wrong key type for this alg


@pytest.mark.parametrize("alg", ["hmac-sha256;key=server;verify=refetch verify_url", "", "x"])
def test_server_or_unknown_alg_is_never_verified(alg):
    h = {"X-BO-Signature": _sig(b"anything"), "X-BO-Signature-Alg": alg}
    assert not webhooks.verify(BODY, h, api_key="anything", callback_secret="anything")


def test_missing_signature():
    assert not webhooks.verify(BODY, {}, api_key="k1")


class _FakeClient:
    def __init__(self, agent_id="agent_1", api_key="k"):
        self.agent_id, self.api_key, self.calls = agent_id, api_key, []

    def gw_post(self, path, body=None, extra_headers=None):
        self.calls.append((path, body))
        return {"ok": True, "request_id": "r1"} if path == "/a2a/requests" else {"ok": True}


def test_post_request_with_callback_registers_first():
    c = _FakeClient()
    MarketplaceAPI(c).post_request("cap", "task", callback_url="https://me.dev/h")
    assert c.calls[0] == ("/a2a/agents/agent_1/callback", {"url": "https://me.dev/h"})
    assert c.calls[1][0] == "/a2a/requests"


def test_post_request_without_callback_is_unchanged():
    c = _FakeClient()
    MarketplaceAPI(c).post_request("cap", "task")
    assert [p for p, _ in c.calls] == ["/a2a/requests"]


def test_register_callback_needs_identity():
    with pytest.raises(ValueError):
        MarketplaceAPI(_FakeClient(agent_id=None)).register_callback("https://me.dev/h")


# RQ-BO-WEBHOOK-SECRET-01 ---------------------------------------------------------

def test_webhook_secret_alg_verifies_with_the_secret_only():
    h = {"X-BO-Signature": _sig(b"whsec_abc"), "X-BO-Signature-Alg": webhooks.ALG_WEBHOOK}
    assert webhooks.verify(BODY, h, webhook_secret="whsec_abc")
    assert not webhooks.verify(BODY, h, webhook_secret="whsec_other")
    # the api_key / callback_secret paths never satisfy a webhook_secret delivery
    assert not webhooks.verify(BODY, h, api_key="whsec_abc", callback_secret="whsec_abc")


def test_legacy_alg_still_needs_the_api_key():
    key = hashlib.sha256(b"k1").hexdigest().encode()
    h = {"X-BO-Signature": _sig(key), "X-BO-Signature-Alg": webhooks.ALG_AGENT}
    assert not webhooks.verify(BODY, h, webhook_secret=key.decode())
    assert webhooks.verify(BODY, h, api_key="k1")
