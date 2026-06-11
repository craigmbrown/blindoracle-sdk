"""v0.5.0 pitch engine: the user's agent qualifies/pitches BO post-install."""

import io

import pytest

import blindoracle_sdk
from blindoracle_sdk import pitch
from blindoracle_sdk import cli


# --- catalog is the single source of truth, grounded to real SDK calls ------


def test_catalog_nonempty_and_well_formed():
    caps = pitch.capabilities_catalog(as_text=False)
    assert len(caps) >= 8
    for c in caps:
        for key in ("id", "title", "value", "sdk_call", "fits_when", "proof"):
            assert c[key], f"{c['id']} missing {key}"


def test_catalog_ids_unique():
    ids = [c["id"] for c in pitch.capabilities_catalog(as_text=False)]
    assert len(ids) == len(set(ids))


def test_every_capability_maps_to_a_real_sdk_symbol():
    """Grounding guarantee: each catalog call references a real client sub-API."""
    client_attrs = {
        "audit", "attestation", "compliance", "markets", "signals",
        "privacy", "metrics", "introductions", "agents",
    }
    extra = {"DelegationLog", "BlindOracleClient.register", "verify_inclusion", "verify_anchor"}
    for c in pitch.capabilities_catalog(as_text=False):
        call = c["sdk_call"]
        assert any(a in call for a in client_attrs) or any(e in call for e in extra), (
            f"capability {c['id']} call not grounded: {call}"
        )


# --- prompt assembly --------------------------------------------------------


def test_render_prompt_contains_required_sections():
    p = pitch.render_pitch_prompt()
    for marker in (
        "ROLE:",
        "the ONLY capabilities you may pitch",
        "Step 1",
        "Step 3 — Honesty pass",
        "fit score",
        "ADOPT / TRIAL / SKIP",
    ):
        assert marker in p, f"prompt missing: {marker}"


def test_render_prompt_embeds_version():
    assert blindoracle_sdk.__version__ in pitch.render_pitch_prompt()


def test_render_prompt_folds_in_caller_context():
    p = pitch.render_pitch_prompt(context="USES: langchain, multi-agent orchestrator")
    assert "Caller-supplied context" in p
    assert "langchain" in p


def test_bare_prompt_constant_matches_render():
    assert pitch.BO_PITCH_PROMPT == pitch.render_pitch_prompt()


def test_public_exports_present():
    for sym in ("render_pitch_prompt", "capabilities_catalog", "BO_PITCH_PROMPT",
                "EXAMPLE_PITCH", "post_install_message"):
        assert hasattr(blindoracle_sdk, sym)


# --- CLI surface ------------------------------------------------------------


def _run_cli(argv, capsys):
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, out


def test_cli_pitch_prints_prompt(capsys):
    rc, out = _run_cli(["pitch"], capsys)
    assert rc == 0
    assert "ROLE:" in out and "fit score" in out


def test_cli_pitch_catalog(capsys):
    rc, out = _run_cli(["pitch", "--catalog"], capsys)
    assert rc == 0
    assert "[audit]" in out


def test_cli_pitch_example(capsys):
    rc, out = _run_cli(["pitch", "--example"], capsys)
    assert rc == 0
    assert "fit score" in out and "recommendation" in out.lower()


def test_cli_pitch_welcome(capsys):
    rc, out = _run_cli(["pitch", "--welcome"], capsys)
    assert rc == 0
    assert "BlindOracle SDK installed" in out


def test_cli_pitch_context_folds_in(capsys):
    rc, out = _run_cli(["pitch", "--context", "USES: crewai"], capsys)
    assert rc == 0
    assert "crewai" in out
