"""Adversarial verifier — one reusable refute pass.

``refute(provider, claim, prompt)`` runs a second LLM call prompted to
find why ``claim`` could be wrong. Returns ``(refuted, reason)``;
callers demote confidence on a credible refutation.

Best-effort: call failure / unparseable response degrade to
``(False, <diagnostic>)``. Disable via ``AGENTIX_ADVERSARIAL_DISABLED``.
Prompt templates live with the calling primitive.
"""

from __future__ import annotations

import os

import structlog

from agentix.core.types import Message
from agentix.drivers.chat import ChatDriver, ChatRequest

# primitives is stdlib-only by design, so this drivers -> tools import
# cannot form a cycle.
from agentix.tools.primitives import extract_json_object

log = structlog.get_logger(__name__)

_DISABLED_ENV = "AGENTIX_ADVERSARIAL_DISABLED"


def is_disabled() -> bool:
    """``AGENTIX_ADVERSARIAL_DISABLED=1`` skips the refute pass."""
    val = (os.environ.get(_DISABLED_ENV) or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


async def refute(
    provider: ChatDriver,
    *,
    claim_description: str,
    refute_prompt_template: str,
) -> tuple[bool, str]:
    """Returns ``(refuted, reason)``. ``refuted=False`` is NOT a
    positive confirmation — failure modes (call error, unparseable
    response, disabled) all collapse to ``False``.

    The template's ``{claim}`` slot is replaced; the template must
    instruct JSON output matching ``{"refuted": bool, "reason": str}``.
    """
    if is_disabled():
        log.debug("adversarial.disabled_via_env")
        return (False, "disabled")
    prompt = refute_prompt_template.replace("{claim}", claim_description)
    try:
        response = await provider.complete(ChatRequest(messages=[Message(role="user", content=prompt)]))
    except Exception as exc:
        log.warning(
            "adversarial.call_failed",
            error=type(exc).__name__,
            message=str(exc)[:300],
        )
        return (False, "adversarial call failed")
    parsed = extract_json_object(response.content)
    if parsed is None:
        log.warning(
            "adversarial.unparseable",
            response_head=response.content[:300],
        )
        return (False, "adversarial response unparseable")
    refuted = bool(parsed.get("refuted", False))
    reason = str(parsed.get("reason", "") or "")[:600]
    log.info("adversarial.verdict", refuted=refuted, reason=reason[:120])
    return (refuted, reason)


__all__ = ["is_disabled", "refute"]
