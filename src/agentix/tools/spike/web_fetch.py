"""web_fetch — bounded GET restricted to an allowlisted set of hosts.

Allowlist enforced on host so the agent can't exfiltrate context to arbitrary
endpoints. The kernel ships a minimal generic default (code-hosting infra); apps
extend it with their own domains via :func:`register_allowed_hosts` (the
migration app adds the Odoo upstream hosts).
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from urllib.parse import urlparse

import httpx
import structlog
from pydantic import BaseModel, Field

from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


# Generic default: code-hosting infra only. Apps add their own via
# ``register_allowed_hosts`` — no app-specific domains hardcoded in the kernel.
_ALLOWED_HOSTS: set[str] = {"github.com", "raw.githubusercontent.com"}
_TIMEOUT_S = 15.0
_BODY_CAP_BYTES = 100_000


def register_allowed_hosts(hosts: Iterable[str]) -> None:
    """Extend the web_fetch host allowlist (app-called at startup)."""
    _ALLOWED_HOSTS.update(hosts)


class WebFetchInput(BaseModel):
    url: str = Field(
        ...,
        description=(
            "HTTPS URL to GET. Host must be in the allowlist (github.com, "
            "raw.githubusercontent.com, plus any hosts the app registers)."
        ),
    )


class WebFetchOutput(BaseModel):
    url: str
    status: int
    content_type: str
    body: str
    truncated: bool = False
    latency_ms: int = 0


class WebFetch(Tool):
    name = "web_fetch"
    description = (
        "GET a URL from the host allowlist (github.com, raw.githubusercontent.com, "
        "plus any hosts the app registers). Body capped at 100 KB. Use this to read "
        "reference docs or fetch source for diffs."
    )
    input_schema = WebFetchInput
    output_schema = WebFetchOutput
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, WebFetchInput)
        parsed = urlparse(params.url)
        if parsed.scheme != "https":
            raise ValueError(f"web_fetch: only https:// allowed, got {parsed.scheme!r}")
        if (parsed.hostname or "") not in _ALLOWED_HOSTS:
            raise ValueError(f"web_fetch: host {parsed.hostname!r} not in allowlist ({sorted(_ALLOWED_HOSTS)})")
        started = time.perf_counter_ns()
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True) as client:
            response = await client.get(params.url)
        if response.status_code >= 400:
            raise ValueError(
                f"web_fetch: {params.url} returned HTTP {response.status_code}. "
                f"Do not retry the same URL — try a different path or fall back to consult_memory."
            )
        body = response.text
        truncated = len(body) > _BODY_CAP_BYTES
        if truncated:
            body = body[:_BODY_CAP_BYTES] + "\n…(truncated)"
        out = WebFetchOutput(
            url=params.url,
            status=response.status_code,
            content_type=response.headers.get("content-type", ""),
            body=body,
            truncated=truncated,
            latency_ms=elapsed_ms(started),
        )
        log.info(
            "spike.web_fetch",
            url=params.url,
            status=response.status_code,
            bytes=len(response.text),
        )
        return out
