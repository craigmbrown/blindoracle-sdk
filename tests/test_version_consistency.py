#!/usr/bin/env python3
"""Regression lock: ONE version string, and it reaches the wire.

@REQ-ID: RQ-BO-SKU-DOGFOOD-01

Found during the 2026-08-16 external-buyer dogfood run against the PyPI build:
``pip show`` reported 0.8.0 while ``blindoracle_sdk.__version__`` reported
0.7.0, and three different hardcoded User-Agent strings went out on the wire.
The version half made ``blindoracle version`` lie and put a wrong version into
pitch.py's agent-to-agent capability artifact; the User-Agent half meant the
gateway could not attribute an inbound call to the SDK build that made it.

These tests fail if any of those literals is ever reintroduced.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

SDK_ROOT = Path(__file__).resolve().parents[1]
PKG = SDK_ROOT / "blindoracle_sdk"
sys.path.insert(0, str(SDK_ROOT))

import blindoracle_sdk  # noqa: E402
from blindoracle_sdk._version import sdk_version, user_agent  # noqa: E402
from blindoracle_sdk.client import BlindOracleClient  # noqa: E402


def _pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"',
                  (SDK_ROOT / "pyproject.toml").read_text(), re.M)
    assert m, "pyproject.toml has no version field"
    return m.group(1)


# --- the four strings must agree ---------------------------------------------

def test_dunder_version_matches_version_module():
    assert blindoracle_sdk.__version__ == sdk_version()


def test_client_user_agent_carries_the_real_version():
    assert BlindOracleClient.USER_AGENT == user_agent()
    assert sdk_version() in BlindOracleClient.USER_AGENT


def test_source_tree_fallback_tracks_pyproject():
    """The uninstalled-source fallback must not drift from pyproject.toml.

    This is the literal that went stale for two releases. It is only read when
    distribution metadata is absent, which is precisely when nothing else can
    catch the mistake.
    """
    from blindoracle_sdk import _version
    assert _version._FALLBACK == _pyproject_version(), (
        f"_version._FALLBACK ({_version._FALLBACK}) != pyproject "
        f"({_pyproject_version()}) — bump both on release"
    )


# --- no literal may come back ------------------------------------------------

_BANNED = [
    r'User-Agent"\s*:\s*"blindoracle[^"]*"',   # any hardcoded UA value
    r"__version__\s*=\s*['\"]\d",              # any hardcoded __version__
    r'USER_AGENT\s*=\s*["\']blindoracle',      # hardcoded UA constant
]


@pytest.mark.parametrize("pattern", _BANNED)
def test_no_hardcoded_version_or_user_agent_in_package(pattern):
    offenders = []
    rx = re.compile(pattern)
    for f in sorted(PKG.rglob("*.py")):
        if f.name == "_version.py":
            continue  # documents the historical literals on purpose
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if rx.search(line):
                offenders.append(f"{f.relative_to(SDK_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "hardcoded version/User-Agent reintroduced — derive it from "
        "blindoracle_sdk._version instead:\n  " + "\n  ".join(offenders)
    )


def test_every_outbound_user_agent_is_derived():
    """Any module that sets a User-Agent must import the shared helper."""
    missing = []
    for f in sorted(PKG.rglob("*.py")):
        if f.name == "_version.py":
            continue
        src = f.read_text()
        if re.search(r'["\']User-Agent["\']\s*:', src, re.I) and "_version" not in src:
            missing.append(str(f.relative_to(SDK_ROOT)))
    assert not missing, (
        "these modules send a User-Agent without importing _version: " + ", ".join(missing)
    )


# --- the CLI is what an external agent actually runs -------------------------

def test_cli_version_command_reports_the_real_version():
    out = subprocess.run(
        [sys.executable, "-m", "blindoracle_sdk.cli", "version"],
        capture_output=True, text=True, cwd=str(SDK_ROOT), timeout=60,
    )
    assert sdk_version() in out.stdout, (
        f"`blindoracle version` printed {out.stdout!r} / {out.stderr!r}, "
        f"expected {sdk_version()}"
    )


def test_version_read_never_raises(monkeypatch):
    """A version lookup must never break a paid call."""
    import importlib.metadata as md
    from blindoracle_sdk import _version

    def boom(_):
        raise RuntimeError("metadata backend exploded")

    monkeypatch.setattr(md, "version", boom)
    assert _version.sdk_version() == _version._FALLBACK
    assert _version.user_agent().startswith("blindoracle-sdk-python/")
