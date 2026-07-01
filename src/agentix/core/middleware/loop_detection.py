"""Loop detection middleware — aborts on repeated LLM behaviour.

Tracks the last few turns for a session and aborts when the agent is
clearly stuck:

* **N identical tool calls in a row** — same tool name + same arguments
  dict, ``N`` times back-to-back. Catches the classic "keep calling the
  same thing expecting a different result" failure mode.
* **N identical assistant messages in a row** — same text content,
  ``N`` times. Catches the LLM-stuck-in-narration failure mode.

Default ``N = 3``.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

import structlog

from agentix.core.middleware.base import Next
from agentix.core.types import ToolCall, Turn

log = structlog.get_logger(__name__)

_DEFAULT_STREAK = 3
_DEFAULT_MAX_SESSIONS = 512


class LoopDetectionMiddleware:
    """Aborts the turn when the agent has clearly stalled.

    Per-session rolling windows of last-seen hashes are kept in an
    LRU-capped :class:`OrderedDict`. Without the cap a long-running
    FastAPI process leaks one dict entry per session it ever saw.
    Operators can also call :meth:`evict` explicitly at session end.
    """

    name = "LoopDetection"

    def __init__(self, *, streak: int = _DEFAULT_STREAK, max_sessions: int = _DEFAULT_MAX_SESSIONS) -> None:
        if streak < 2:
            raise ValueError("streak must be >= 2 to detect a loop")
        if max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        self._streak = streak
        self._max_sessions = max_sessions
        # LRU-capped per-session history. OrderedDict + move_to_end lets
        # us drop the least-recently-used session entries when the cap
        # trips, which is how we bound memory growth.
        self._tool_history: OrderedDict[str, list[str]] = OrderedDict()
        self._assistant_history: OrderedDict[str, list[str]] = OrderedDict()

    async def __call__(self, turn: Turn, next_: Next) -> Turn:
        result = await next_(turn)

        if result.assistant_message is None:
            return result

        tool_hash = _hash_tool_calls(result.assistant_message.tool_calls)
        text_hash = _hash_text(result.assistant_message.content)

        tool_hist = self._get_history(self._tool_history, turn.session_id)
        text_hist = self._get_history(self._assistant_history, turn.session_id)

        self._append(tool_hist, tool_hash)
        self._append(text_hist, text_hash)

        tool_streak = _trailing_streak(tool_hist)
        text_streak = _trailing_streak(text_hist)

        if tool_streak >= self._streak:
            # Enrich the abort reason with the stuck tool name +
            # extracted model arg so the operator gets actionable
            # diagnostics, not just "3 identical calls". When the args
            # don't include a model (e.g. consult_memory), fall through to
            # the bare reason — partial info is still useful.
            hint = _build_recovery_hint(result.assistant_message.tool_calls, tool_streak)
            reason = f"loop: {tool_streak} identical tool-call dicts in a row{hint}"
            log.warning(
                "loop.tool_streak",
                session_id=turn.session_id,
                streak=tool_streak,
                stuck_tool=_extract_stuck_tool(result.assistant_message.tool_calls),
                stuck_model=_extract_stuck_model(result.assistant_message.tool_calls),
            )
            result.abort(reason)
        elif text_streak >= self._streak:
            reason = (
                f"loop: {text_streak} identical assistant messages in a row "
                "— consider: (a) change approach for the item in flight, "
                "(b) narrow the tool's arguments, (c) ask operator"
            )
            log.warning("loop.text_streak", session_id=turn.session_id, streak=text_streak)
            result.abort(reason)

        return result

    def evict(self, session_id: str) -> None:
        """Drop one session's rolling history — call at session end.

        Safe to call on unknown session_ids (no-op). Long-running
        services (FastAPI) call this from the session-completion hook
        so a per-customer deployment doesn't accumulate state over
        months of use.
        """
        self._tool_history.pop(session_id, None)
        self._assistant_history.pop(session_id, None)

    def _get_history(self, store: OrderedDict[str, list[str]], session_id: str) -> list[str]:
        """Return this session's history list, creating it LRU-style.

        When ``max_sessions`` is exceeded, the least-recently-used entry
        is dropped. ``move_to_end`` refreshes the ordering on every
        access so the active session never gets evicted under normal
        load. Without the cap the per-session maps grow unbounded and a
        long-lived FastAPI leaks one entry per session it ever saw.
        """
        if session_id in store:
            store.move_to_end(session_id)
            return store[session_id]
        hist: list[str] = []
        store[session_id] = hist
        while len(store) > self._max_sessions:
            store.popitem(last=False)
        return hist

    @staticmethod
    def _append(history: list[str], value: str) -> None:
        history.append(value)
        # Keep only what's needed for streak detection — trim aggressively.
        if len(history) > _DEFAULT_STREAK * 2:
            del history[:-_DEFAULT_STREAK]


def _hash_tool_calls(calls: list[ToolCall]) -> str:
    """Deterministic fingerprint for a list of ToolCall dicts."""
    if not calls:
        return ""
    payload = [{"name": tc.name, "args": tc.arguments} for tc in calls]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def _hash_text(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _trailing_streak(history: list[str]) -> int:
    if not history:
        return 0
    last = history[-1]
    # Empty fingerprint = "no signal" — never counts as a loop.
    if not last:
        return 0
    count = 0
    for value in reversed(history):
        if value == last:
            count += 1
        else:
            break
    return count


def _extract_stuck_tool(calls: list[ToolCall]) -> str | None:
    """First tool name in the stuck call set — the one to point operators at."""
    if not calls:
        return None
    return calls[0].name


def _extract_stuck_model(calls: list[ToolCall]) -> str | None:
    """Pull the ``model`` arg from the first stuck call when present.

    Tools that act on a target commonly carry it on a top-level ``model``
    field; for tools that don't, returns None and the caller emits a
    tool-only hint without the model qualifier.
    """
    if not calls:
        return None
    for call in calls:
        m = call.arguments.get("model")
        if isinstance(m, str) and m:
            return m
    return None


def _build_recovery_hint(calls: list[ToolCall], streak: int) -> str:
    """Compose the trailing recovery hint appended to the abort reason.

    Separated from the abort site so unit tests can target the message
    shape directly. Two flavors:

      * tool + model known → "stuck on tool=X for model=Y; consider …"
      * tool only → bare suggestion list

    Suggestions are deliberately short and actionable — the operator
    sees them in the CLI's session summary and the structured
    safety_event detail field.
    """
    tool = _extract_stuck_tool(calls)
    model = _extract_stuck_model(calls)
    if not tool:
        return ""
    suggestions = (
        " — consider: (a) skip this item and continue, "
        "(b) change the tool's arguments (missing input / narrower scope), "
        "(c) try a different tool, "
        "(d) ask operator"
    )
    if model:
        return f" (stuck on tool={tool!r} for model={model!r}, streak={streak}){suggestions}"
    return f" (stuck on tool={tool!r}, streak={streak}){suggestions}"
