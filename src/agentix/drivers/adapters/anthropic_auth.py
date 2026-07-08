"""Token sources for the Anthropic provider.

Claude Code rotates OAuth tokens every ~hour. A static ``accessToken``
captured at provider-init time expires mid-session and the agent stops
with a 401. This module gives the provider a *source* it can re-read
on every request, so refreshes made by Claude Code (into the macOS
Keychain or the ``~/.claude/.credentials.json`` file) are picked up
transparently.

Four sources, all implementing :class:`TokenSource`:

* :class:`StaticTokenSource` — a literal API key / OAuth token.
* :class:`EnvTokenSource` — read a named env var on every call.
* :class:`FileTokenSource` — re-read ``~/.claude/.credentials.json`` on
  every call.
* :class:`KeychainTokenSource` — shell out to macOS ``security`` on
  every call to fetch the current ``Claude Code-credentials`` blob.

:func:`resolve_token_source` is the factory used by AnthropicProvider:
it tries the configured sources in order and raises
:class:`DriverInvalidRequest` if none produce a token.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agentix.drivers.base import DriverInvalidRequest

_OAUTH_PREFIX = "sk-ant-oat"


class TokenSource(Protocol):
    """A per-request token provider for Anthropic.

    Implementations MUST be safe to call on every API request — they are
    invoked once per ``AnthropicProvider.complete()`` call so Claude
    Code's background refresh lands in the next API call without
    reconnecting.
    """

    def get_token(self) -> tuple[str, bool]:
        """Return ``(token, is_oauth)``. May raise :class:`DriverInvalidRequest`."""
        ...


@dataclass(frozen=True)
class StaticTokenSource:
    """Wraps a fixed token (typical for ``ANTHROPIC_API_KEY`` in CI)."""

    token: str

    def get_token(self) -> tuple[str, bool]:
        return self.token, self.token.startswith(_OAUTH_PREFIX)


@dataclass(frozen=True)
class EnvTokenSource:
    """Re-reads an env var on every request. Useful when an operator
    rotates ``ANTHROPIC_API_KEY`` in the running shell."""

    var_name: str

    def get_token(self) -> tuple[str, bool]:
        value = os.environ.get(self.var_name)
        if not value:
            raise DriverInvalidRequest(
                f"env var {self.var_name!r} is unset",
                driver="anthropic",
            )
        return value, value.startswith(_OAUTH_PREFIX)


@dataclass(frozen=True)
class FileTokenSource:
    """Reads ``claudeAiOauth.accessToken`` from a JSON file on every call.

    The Linux / Windows default Claude Code install writes to
    ``~/.claude/.credentials.json`` and refreshes in place. Re-reading
    per call picks those rotations up without restarting.
    """

    path: Path

    def get_token(self) -> tuple[str, bool]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise DriverInvalidRequest(
                f"Claude credentials file not found at {self.path}",
                driver="anthropic",
            ) from e
        except (OSError, json.JSONDecodeError) as e:
            raise DriverInvalidRequest(
                f"could not parse Claude credentials at {self.path}: {e}",
                driver="anthropic",
            ) from e
        oauth = payload.get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        if not token:
            raise DriverInvalidRequest(
                f"no accessToken in claudeAiOauth at {self.path}",
                driver="anthropic",
            )
        return str(token), True


@dataclass(frozen=True)
class KeychainTokenSource:
    """Pulls the current token from macOS Keychain on every call.

    ``claude login`` on macOS stores the credentials in the Keychain
    under a service name (default ``Claude Code-credentials``) instead
    of a plain file. The ``security find-generic-password`` CLI is the
    documented way to read it; the first call prompts for permission
    and subsequent calls succeed silently once the user picks
    "Always Allow".

    Not available outside macOS — constructing one is fine, but
    :meth:`get_token` raises if ``security`` isn't on ``PATH``.
    """

    service_name: str = "Claude Code-credentials"

    def get_token(self) -> tuple[str, bool]:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", self.service_name, "-w"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        except FileNotFoundError as e:
            raise DriverInvalidRequest(
                "macOS 'security' CLI not available; Keychain token source only works on macOS",
                driver="anthropic",
            ) from e
        except subprocess.TimeoutExpired as e:
            raise DriverInvalidRequest(
                f"'security find-generic-password -s {self.service_name}' timed out",
                driver="anthropic",
            ) from e
        if result.returncode != 0:
            raise DriverInvalidRequest(
                f"Keychain lookup for service {self.service_name!r} failed "
                f"(exit={result.returncode}): {result.stderr.strip()[:200]}",
                driver="anthropic",
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise DriverInvalidRequest(
                f"Keychain payload for {self.service_name!r} is not JSON: {e}",
                driver="anthropic",
            ) from e
        oauth = payload.get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        if not token:
            raise DriverInvalidRequest(
                f"no accessToken in Keychain service {self.service_name!r}",
                driver="anthropic",
            )
        return str(token), True


@dataclass(frozen=True)
class ChainTokenSource:
    """Try sources in order, returning the first non-raising one."""

    sources: tuple[TokenSource, ...]

    def get_token(self) -> tuple[str, bool]:
        last_error: DriverInvalidRequest | None = None
        for source in self.sources:
            try:
                return source.get_token()
            except DriverInvalidRequest as e:
                last_error = e
                continue
        raise last_error or DriverInvalidRequest(
            "no Claude credentials found (no sources configured)",
            driver="anthropic",
        )


def resolve_token_source(
    *,
    api_key: str | None = None,
    credentials_path: str | Path | None = None,
    keychain_service: str | None = None,
) -> TokenSource:
    """Build the preferred-order :class:`TokenSource` for AnthropicProvider.

    Priority:

    1. Explicit ``api_key`` — a literal string wins over everything.
    2. ``CLAUDE_CODE_OAUTH_TOKEN`` / ``ANTHROPIC_AUTH_TOKEN`` env vars,
       read per-request so rotating the var in-shell works.
    3. ``ANTHROPIC_API_KEY`` env var (same per-request behaviour).
    4. ``keychain_service`` if set — the macOS-native Claude Code source.
    5. ``credentials_path`` (default ``~/.claude/.credentials.json``),
       re-read per request so file-based Claude Code installs pick up
       refreshes.

    No source means raising at resolve time — better to fail loudly than
    to construct a provider that can never authenticate.
    """
    sources: list[TokenSource] = []
    if api_key:
        sources.append(StaticTokenSource(token=api_key))
    sources.append(EnvTokenSource(var_name="CLAUDE_CODE_OAUTH_TOKEN"))
    sources.append(EnvTokenSource(var_name="ANTHROPIC_AUTH_TOKEN"))
    sources.append(EnvTokenSource(var_name="ANTHROPIC_API_KEY"))
    if keychain_service:
        sources.append(KeychainTokenSource(service_name=keychain_service))
    resolved_path = Path(credentials_path) if credentials_path else Path.home() / ".claude" / ".credentials.json"
    sources.append(FileTokenSource(path=resolved_path))
    return ChainTokenSource(sources=tuple(sources))


__all__ = [
    "ChainTokenSource",
    "EnvTokenSource",
    "FileTokenSource",
    "KeychainTokenSource",
    "StaticTokenSource",
    "TokenSource",
    "resolve_token_source",
]
