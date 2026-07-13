"""Unit tests for agentix.drivers.adapters.vendor.anthropic_auth token sources."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from agentix.drivers.adapters.vendor.anthropic_auth import (
    ChainTokenSource,
    EnvTokenSource,
    FileTokenSource,
    KeychainTokenSource,
    StaticTokenSource,
    resolve_token_source,
)

from agentix.drivers.base import DriverInvalidRequest

# ────────────────────────── StaticTokenSource ──────────────────────────


def test_static_token_source_api_key() -> None:
    src = StaticTokenSource(token="sk-ant-api03-abc")
    token, is_oauth = src.get_token()
    assert token == "sk-ant-api03-abc"
    assert is_oauth is False


def test_static_token_source_oauth() -> None:
    src = StaticTokenSource(token="sk-ant-oat01-abc")
    _, is_oauth = src.get_token()
    assert is_oauth is True


# ────────────────────────── EnvTokenSource ─────────────────────────────


def test_env_token_source_reads_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """EnvTokenSource re-reads the env var on every call — rotating the
    var in-process is picked up without re-constructing the source."""
    monkeypatch.setenv("PILOT_ANTH_TOKEN", "sk-ant-oat01-v1")
    src = EnvTokenSource(var_name="PILOT_ANTH_TOKEN")
    assert src.get_token() == ("sk-ant-oat01-v1", True)

    # Rotate: the next call should return the new value.
    monkeypatch.setenv("PILOT_ANTH_TOKEN", "sk-ant-oat01-v2")
    assert src.get_token() == ("sk-ant-oat01-v2", True)


def test_env_token_source_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PILOT_ANTH_TOKEN_MISSING", raising=False)
    src = EnvTokenSource(var_name="PILOT_ANTH_TOKEN_MISSING")
    with pytest.raises(DriverInvalidRequest, match="unset"):
        src.get_token()


# ────────────────────────── FileTokenSource ────────────────────────────


def test_file_token_source_reads_fresh_on_rotate(tmp_path: Path) -> None:
    """Claude Code writes credentials.json in place; re-reading the file
    each call must surface the new token without restarting."""
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-v1"}}))
    src = FileTokenSource(path=path)
    assert src.get_token() == ("sk-ant-oat01-v1", True)

    # Simulate rotation — the same source picks up the new token.
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-v2"}}))
    assert src.get_token() == ("sk-ant-oat01-v2", True)


def test_file_token_source_missing_file(tmp_path: Path) -> None:
    src = FileTokenSource(path=tmp_path / "does-not-exist.json")
    with pytest.raises(DriverInvalidRequest, match="not found"):
        src.get_token()


def test_file_token_source_missing_access_token(tmp_path: Path) -> None:
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"claudeAiOauth": {}}))
    src = FileTokenSource(path=path)
    with pytest.raises(DriverInvalidRequest, match="accessToken"):
        src.get_token()


def test_file_token_source_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "creds.json"
    path.write_text("not valid json")
    src = FileTokenSource(path=path)
    with pytest.raises(DriverInvalidRequest, match="parse"):
        src.get_token()


# ────────────────────────── KeychainTokenSource ────────────────────────


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["security", "find-generic-password"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_keychain_token_source_happy_path() -> None:
    """macOS ``security find-generic-password -s <service> -w`` returns
    the raw JSON blob Claude Code stored."""
    payload = json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-kc"}})
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run", return_value=_fake_completed(stdout=payload)
    ) as mock:
        src = KeychainTokenSource(service_name="Claude Code-credentials")
        token, is_oauth = src.get_token()
    assert token == "sk-ant-oat01-kc"
    assert is_oauth is True
    # Verify the exact command we shelled out to — the interface with the
    # macOS security CLI is sensitive to flag ordering.
    args = mock.call_args.args[0]
    assert args == ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"]


def test_keychain_token_source_security_missing() -> None:
    """Non-macOS or stripped-down image — ``security`` isn't on PATH."""
    with patch("agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run", side_effect=FileNotFoundError):
        src = KeychainTokenSource()
        with pytest.raises(DriverInvalidRequest, match="only works on macOS"):
            src.get_token()


def test_keychain_token_source_user_denied() -> None:
    """security returns non-zero when the user denies the prompt."""
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run",
        return_value=_fake_completed(returncode=51, stderr="user canceled"),
    ):
        src = KeychainTokenSource()
        with pytest.raises(DriverInvalidRequest, match=r"Keychain lookup.*failed"):
            src.get_token()


def test_keychain_token_source_timeout() -> None:
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="security", timeout=10.0),
    ):
        src = KeychainTokenSource()
        with pytest.raises(DriverInvalidRequest, match="timed out"):
            src.get_token()


def test_keychain_token_source_malformed_payload() -> None:
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run", return_value=_fake_completed(stdout="not json")
    ):
        src = KeychainTokenSource()
        with pytest.raises(DriverInvalidRequest, match="not JSON"):
            src.get_token()


def test_keychain_token_source_missing_access_token() -> None:
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run",
        return_value=_fake_completed(stdout=json.dumps({"claudeAiOauth": {}})),
    ):
        src = KeychainTokenSource()
        with pytest.raises(DriverInvalidRequest, match="no accessToken"):
            src.get_token()


# ────────────────────────── ChainTokenSource ───────────────────────────


def test_chain_returns_first_successful() -> None:
    first = StaticTokenSource(token="sk-ant-api03-one")
    second = StaticTokenSource(token="sk-ant-api03-two")
    chain = ChainTokenSource(sources=(first, second))
    assert chain.get_token() == ("sk-ant-api03-one", False)


def test_chain_falls_through_to_next_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PILOT_A", raising=False)
    monkeypatch.setenv("PILOT_B", "sk-ant-oat01-fallback")
    chain = ChainTokenSource(
        sources=(
            EnvTokenSource(var_name="PILOT_A"),  # missing → raises, move on
            EnvTokenSource(var_name="PILOT_B"),  # present → returns
        )
    )
    assert chain.get_token() == ("sk-ant-oat01-fallback", True)


def test_chain_reraises_last_error_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PILOT_X", raising=False)
    monkeypatch.delenv("PILOT_Y", raising=False)
    chain = ChainTokenSource(
        sources=(
            EnvTokenSource(var_name="PILOT_X"),
            EnvTokenSource(var_name="PILOT_Y"),
        )
    )
    with pytest.raises(DriverInvalidRequest, match="PILOT_Y"):
        chain.get_token()


# ────────────────────────── resolve_token_source ───────────────────────


def test_resolve_explicit_api_key_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key`` beats every env var or Keychain entry that also exists.
    Explicit config > ambient config is the resolution rule we promise
    in the ``resolve_token_source`` docstring."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-env")
    src = resolve_token_source(api_key="sk-ant-api03-explicit", credentials_path=tmp_path / "nope.json")
    assert src.get_token() == ("sk-ant-api03-explicit", False)


def test_resolve_falls_through_env_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No explicit key, no env tokens, no keychain → the file source
    must successfully produce a token for Linux operators."""
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-file"}}))
    src = resolve_token_source(credentials_path=path)
    assert src.get_token() == ("sk-ant-oat01-file", True)


def test_resolve_keychain_then_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keychain configured + present → wins over the file fallback."""
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-file"}}))
    kc_payload = json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-kc"}})
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run", return_value=_fake_completed(stdout=kc_payload)
    ):
        src = resolve_token_source(credentials_path=path, keychain_service="Claude Code-credentials")
        assert src.get_token() == ("sk-ant-oat01-kc", True)


def test_resolve_keychain_fails_then_file_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keychain configured but failing → falls back to file source. This
    is the crucial graceful-degradation path for macOS operators who
    denied the Keychain prompt."""
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-file"}}))
    with patch(
        "agentix.drivers.adapters.vendor.anthropic_auth.subprocess.run",
        return_value=_fake_completed(returncode=1, stderr="denied"),
    ):
        src = resolve_token_source(credentials_path=path, keychain_service="Claude Code-credentials")
        assert src.get_token() == ("sk-ant-oat01-file", True)
