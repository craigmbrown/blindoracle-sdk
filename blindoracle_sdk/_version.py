"""Single source of truth for the SDK version and wire User-Agent.

@REQ-ID: RQ-BO-SKU-DOGFOOD-01

Before this module the SDK carried FOUR version strings and three of them were
wrong:

    pyproject.toml            0.9.0                       <- the truth
    __init__.__version__      0.7.0                       <- stale 2 releases
    client.USER_AGENT         blindoracle-sdk-python/0.8.0 <- stale 1 release
    attestation.py UA         blindoracle-sdk/1.x          <- meaningless
    audit.py UA               blindoracle-sdk/0.2          <- stale 7 releases

Consequences, all measured against the PyPI build during the 2026-08-16
external-buyer dogfood run: ``blindoracle version`` reported 0.7.0; ``pitch.py``
embedded 0.7.0 into an agent-to-agent capability artifact; and because three
different User-Agents went out on the wire, the gateway could not attribute an
inbound call to the SDK build that made it — which defeats the point of having
an audit trail on SDK usage at all.

This module has NO intra-package imports, so every other module (including the
package ``__init__`` and ``client``, which import each other) can depend on it
without a cycle.
"""

# Fallback used only when running from an uninstalled source tree, where
# distribution metadata does not exist. Keep in step with pyproject.toml on
# release; the installed path never reads it.
_FALLBACK = "0.9.0"

_DIST = "blindoracle-sdk"


def sdk_version() -> str:
    """Installed distribution version, or the source-tree fallback."""
    try:
        from importlib.metadata import version, PackageNotFoundError
    except ImportError:  # Python < 3.8
        return _FALLBACK
    try:
        return version(_DIST)
    except PackageNotFoundError:
        return _FALLBACK
    except Exception:  # noqa: BLE001 - a version read must never break a call
        return _FALLBACK


def user_agent() -> str:
    """The one User-Agent every outbound request in this SDK must send."""
    return f"blindoracle-sdk-python/{sdk_version()}"
