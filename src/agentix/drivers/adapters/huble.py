"""HUBLE provider — routes the agent loop through the HUBLE gateway.

HUBLE (a.k.a. ``llmhub``) is the central LLM gateway: one API key,
many upstream providers (Claude, Melious, OpenAI, Groq, Gemini,
Ollama, …). The app holds only the HUBLE key; HUBLE owns each
upstream's keys and rotates them centrally.

This provider implements the kernel's :class:`Provider` protocol by
POSTing to HUBLE's ``/api/v2/agent/chat`` endpoint, which speaks an
Anthropic-shaped wire format:

  request:  ``{provider, model, messages, tools?, tool_choice?, system?, max_tokens, …}``
  response: ``{content: [{type: "text", text}, {type: "tool_use", id, name, input}], stop_reason, …}``

Switching between upstream providers is a config knob —
``providers.huble.upstream_provider`` — not a code change. The
agent loop sees the same ``ChatResponse`` shape regardless of whether
HUBLE routes to Claude or Melious.

Auth: single ``X-API-Key`` header, env var ``LLMHUB_API_KEY``.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from agentix.core.types import Message, TokenUsage, ToolCall
from agentix.drivers.base import (
    DriverDescriptor,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)
from agentix.drivers.chat import ChatRequest, ChatResponse

log = structlog.get_logger(__name__)

_DEFAULT_BASE_URL = "http://localhost:4000"
_AGENT_CHAT_PATH = "/api/v2/agent/chat"
_DEFAULT_TIMEOUT_S = 300.0
# Gateway-side validator rejects max_tokens above this (HTTP 422,
# `le=16000`). Provider clamps so callers can keep the generous
# ChatRequest default without knowing per-provider wire limits.
_HUBLE_MAX_OUTPUT_TOKENS = 16_000


class HubleChatDriver:
    """Route ChatRequest → HUBLE /api/v2/agent/chat → ChatResponse.

    One HUBLE deployment, one API key, many upstreams. Pin the
    upstream via ``upstream_provider`` (HUBLE's ``provider`` field —
    ``"melious"``, ``"claude"``, ``"openai"``, etc.) and ``model``.

    HUBLE's response is always Anthropic-shaped (``content`` block list
    with ``text`` + ``tool_use`` entries) regardless of upstream — that's
    the gateway's job. We translate only ``ChatRequest`` → HUBLE payload
    and HUBLE's content blocks → ``ChatResponse``; no per-upstream
    branching here.
    """

    name = "huble"

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(
            name=self.name,
            type="model",
            modality="chat",
            source="gateway",
            capabilities=frozenset({"tools", "thinking"}),
            default_model=self.default_model,
            pricing_ref=self.default_model,
        )

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        upstream_provider: str = "melious",
        timeout_seconds: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        # ``model`` is required — no default. Config resolves it from YAML
        # (the app's config loader feeding ``build_drivers``); ad-hoc callers
        # must pass one explicitly.
        if not model:
            raise DriverInvalidRequest(
                "HUBLE: model is required (e.g. 'deepseek-v4-flash'); no default — config or caller must specify",
                driver=self.name,
            )
        self._base_url = (base_url or os.environ.get("LLMHUB_URL") or _DEFAULT_BASE_URL).rstrip("/")
        key = api_key or os.environ.get("LLMHUB_API_KEY")
        if not key:
            raise DriverInvalidRequest(
                "HUBLE: no API key — set LLMHUB_API_KEY or pass api_key=",
                driver=self.name,
            )
        self._api_key = key
        self._upstream_provider = upstream_provider
        self.default_model = model

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-API-Key": self._api_key,
                "Content-Type": "application/json",
            },
            # No connection reuse. HUBLE (like any gateway / RPC server)
            # half-closes idle keep-alive connections; httpx then pulls
            # the dead socket out of the pool and the next request hangs
            # for the full read timeout — retry after retry, a multi-
            # minute stall (TCP CLOSE_WAIT). keepalive_expiry=0 forces a
            # fresh connection per request. Vendor transport clients guard
            # this the same way; HubleProvider missing it hung long runs.
            limits=httpx.Limits(max_keepalive_connections=0, keepalive_expiry=0.0),
            # Split timeouts so a stuck read can't block past the budget
            # and a pool-acquire fails fast rather than waiting forever.
            timeout=httpx.Timeout(
                connect=10.0,
                read=timeout_seconds,
                write=timeout_seconds,
                pool=5.0,
            ),
        )
        log.info(
            "huble.provider_ready",
            base_url=self._base_url,
            upstream_provider=self._upstream_provider,
            default_model=self.default_model,
        )

    async def complete(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.default_model
        system_text, turns = _split_system(request.messages)

        payload: dict[str, Any] = {
            "provider": self._upstream_provider,
            "model": model,
            "messages": turns,
            # The gateway validates max_tokens <= 16000 (HTTP 422 above
            # that). Clamping here keeps the generous ChatRequest default
            # usable across providers — each provider trims to its own
            # wire ceiling instead of callers knowing per-provider limits.
            "max_tokens": min(request.max_tokens, _HUBLE_MAX_OUTPUT_TOKENS),
        }
        if system_text:
            payload["system"] = system_text
        if request.temperature != 1.0:
            payload["temperature"] = request.temperature
        if request.stop_sequences:
            payload["stop_sequences"] = request.stop_sequences
        if request.tools:
            payload["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
                for spec in request.tools
            ]
        if request.tool_choice is not None:
            # HUBLE's agent endpoint accepts the same string the agent
            # uses internally; no per-upstream normalisation here (HUBLE
            # owns that).
            payload["tool_choice"] = request.tool_choice
        # Optional thinking — only some upstreams (Claude) support it;
        # HUBLE silently ignores the field for upstreams that don't.
        if request.thinking_enabled:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": request.thinking_budget_tokens or max(1024, request.max_tokens // 4),
            }
        # Caller-provided extras get a pass-through path so per-call
        # tweaks (e.g. ``flavor: ":eco"``) don't need a code change.
        payload.update(request.extra_params)

        try:
            response = await self._client.post(_AGENT_CHAT_PATH, json=payload)
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            raise DriverUnavailable(f"HUBLE unreachable: {exc}", driver=self.name) from exc
        except httpx.TimeoutException as exc:
            raise DriverUnavailable(f"HUBLE timeout: {exc}", driver=self.name) from exc

        if response.status_code == 429:
            raise DriverRateLimited(_status_message(response), driver=self.name)
        if response.status_code >= 500:
            # Defence-in-depth: HUBLE sometimes wraps upstream 400s
            # (context overflow, malformed request) as 500s, which causes
            # the router to retry a fundamentally non-retriable error 3x and
            # waste tokens on every full input payload. Sniff the body
            # for the canonical upstream-400 signatures and re-classify
            # as DriverInvalidRequest (no-retry). Proper fix lives in HUBLE.
            msg = _status_message(response)
            if _looks_like_wrapped_4xx(msg):
                raise DriverInvalidRequest(
                    f"{msg} (HUBLE wrapped upstream 4xx as 5xx — see #143)",
                    driver=self.name,
                )
            raise DriverUnavailable(msg, driver=self.name)
        if response.status_code >= 400:
            raise DriverInvalidRequest(_status_message(response), driver=self.name)

        try:
            body = response.json()
        except ValueError as exc:
            raise DriverInvalidRequest(
                f"HUBLE returned non-JSON body: {response.text[:200]}",
                driver=self.name,
            ) from exc

        if not body.get("success", True):
            raise DriverInvalidRequest(
                f"HUBLE success=false: {body.get('detail') or body.get('message') or body}",
                driver=self.name,
            )

        return _parse_huble_response(body, model)

    async def aclose(self) -> None:
        await self._client.aclose()


# ────────────────────────────── helpers ────────────────────────────────────


def _split_system(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """HUBLE accepts ``system`` as a top-level field (Anthropic-shape).

    Splits the canonical ``Message`` list into the system text and the
    multi-turn ``turns`` list; tool messages and assistant messages with
    tool_calls keep their structured content blocks.
    """
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
            continue
        turns.append(_message_to_huble(m))
    return "\n\n".join(system_parts), turns


def _message_to_huble(m: Message) -> dict[str, Any]:
    """Translate a canonical ``Message`` to HUBLE's per-message shape.

    HUBLE mirrors Anthropic's content-block convention: assistant
    messages with tool_calls become ``content: [{type: "text", text},
    {type: "tool_use", id, name, input}]``; tool results become
    ``role: "user"`` with ``content: [{type: "tool_result",
    tool_use_id, content}]``.
    """
    if m.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content,
                }
            ],
        }
    role = "assistant" if m.role == "assistant" else "user"
    if not m.tool_calls:
        # Plain text turn.
        return {"role": role, "content": m.content}
    blocks: list[dict[str, Any]] = []
    if m.content:
        blocks.append({"type": "text", "text": m.content})
    for tc in m.tool_calls:
        blocks.append(
            {
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            }
        )
    return {"role": role, "content": blocks}


def _parse_huble_response(body: dict[str, Any], model: str) -> ChatResponse:
    """Translate HUBLE's response body to the canonical ``ChatResponse``.

    HUBLE returns Anthropic-shape ``content`` (list of typed blocks)
    regardless of the upstream provider. Walks the blocks pulling out
    text + tool_use; ``tool_calls`` (the OpenAI-shape mirror) is also
    accepted as a fallback for upstreams that prefer that route.
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    content = body.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text") or ""))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=dict(block.get("input") or {}),
                    )
                )
    elif isinstance(content, str):
        # Non-tool-use response can come back as a plain string.
        text_parts.append(content)

    # Some HUBLE flows expose tool_calls as a top-level OpenAI-shape
    # array. Honour that as a fallback so the same provider works
    # against either wire shape without a code change.
    raw_tool_calls = body.get("tool_calls")
    if not tool_calls and isinstance(raw_tool_calls, list):
        for tc in raw_tool_calls:
            if not isinstance(tc, dict):
                continue
            fn_raw = tc.get("function")
            fn: dict[str, Any] = fn_raw if isinstance(fn_raw, dict) else tc
            args = fn.get("arguments")
            # OpenAI returns arguments as a JSON string; tolerate both.
            if isinstance(args, str):
                import json as _json

                args_raw = args
                try:
                    args = _json.loads(args)
                except _json.JSONDecodeError as exc:
                    # Loud log: silently dropping malformed JSON args is a
                    # silent-bug hole. The agent_dispatcher's empty_args
                    # guard catches the downstream symptom; this log
                    # captures the upstream cause so triage doesn't have
                    # to trace back from "empty args" to "malformed
                    # JSON in upstream response."
                    log.warning(
                        "huble.openai_arguments_malformed_json",
                        tool_name=fn.get("name"),
                        raw_arguments=args_raw[:300],
                        json_error=str(exc)[:160],
                    )
                    args = {}
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id") or ""),
                    name=str(fn.get("name") or ""),
                    arguments=dict(args or {}),
                )
            )

    usage = TokenUsage(
        input_tokens=int(body.get("input_tokens") or 0),
        output_tokens=int(body.get("output_tokens") or 0),
        cached_tokens=int(body.get("cached_tokens") or 0),
    )
    return ChatResponse(
        content="".join(text_parts),
        usage=usage,
        model=str(body.get("model_used") or model),
        finish_reason=body.get("stop_reason"),
        tool_calls=tool_calls,
        raw={
            "log_id": body.get("log_id"),
            "cost_usd": body.get("cost_usd"),
            "provider_used": body.get("provider_used"),
            "provider_metadata": body.get("provider_metadata"),
        },
    )


_WRAPPED_4XX_SIGNATURES: tuple[str, ...] = (
    "exceeds the model's context window",
    "context length",
    "context window",
    "maximum context length",
    "too many tokens",
    "tokens exceed",
    "max_tokens",
    "invalid request",
    "error code: 400",
    "error code: 401",
    "error code: 403",
    "error code: 404",
    "error code: 422",
    "bad request",
    "unauthorized",
)


def _looks_like_wrapped_4xx(message: str) -> bool:
    """HUBLE sometimes wraps upstream 4xx as 5xx. Sniff the body for
    canonical upstream-4xx signatures so the router doesn't retry a
    fundamentally non-retriable error.

    Case-insensitive substring match across known signatures. Conservative
    by design: false-positives reclassify a real 5xx as 4xx and surface
    sooner; false-negatives keep the existing wasteful-retry behavior.
    """
    if not message:
        return False
    lowered = message.lower()
    return any(sig in lowered for sig in _WRAPPED_4XX_SIGNATURES)


def _status_message(response: httpx.Response) -> str:
    """Best-effort error string from a HUBLE error response body."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    detail = body.get("detail")
    if isinstance(detail, dict):
        return f"HTTP {response.status_code}: {detail.get('code', '')}: {detail.get('message') or detail}"
    if isinstance(detail, str):
        return f"HTTP {response.status_code}: {detail}"
    return f"HTTP {response.status_code}: {body}"
