"""AgentDispatcher — Engine ``TurnDispatcher`` running the tool-use loop.

Per turn: build ``ToolSpec`` payloads, call the provider with message
history + tool catalog, and loop until the response has no ``tool_calls``.
Each tool_call is resolved in the registry, its arguments coerced through
the tool's pydantic ``input_schema``, executed via :class:`SafetyGate`,
and appended as a ``tool_result`` message.

Bounded by ``max_tool_iterations``, orthogonal to the budget /
loop-detection middlewares (which see each Engine turn, not each LLM call
inside the dispatcher).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any, Literal, Protocol, runtime_checkable

import structlog

from agentix.core.context_manager import ContextManager
from agentix.core.session import save as save_session
from agentix.core.types import Message, ToolCall, ToolCallResult, Turn
from agentix.llm.base import LlmRequest, Provider, tool_to_spec
from agentix.tools.base import Tool, ToolContext
from agentix.tools.registry import ToolRegistry
from agentix.tools.safety import (
    SafetyGate,
    SafetyGateBlocked,
    SafetyVerifyFailed,
)

log = structlog.get_logger(__name__)


class AgentLoopExhausted(RuntimeError):
    """Back-compat exception. The dispatcher aborts via ``turn.abort(...)``
    rather than raising; abort_reason keeps the canonical "did not
    terminate after N tool-use iterations" substring."""

    def __init__(self, session_id: str, iterations: int) -> None:
        super().__init__(
            f"agent loop for session {session_id!r} did not terminate after {iterations} tool-use iterations"
        )
        self.session_id = session_id
        self.iterations = iterations


class AgentToolNotInRegistry(KeyError):
    """Raised when the model calls a tool name that isn't registered."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(tool_name)
        self.tool_name = tool_name


CtxFactory = Callable[[Turn], ToolContext]


@runtime_checkable
class TerminationPolicy(Protocol):
    """App hook that can force-terminate the tool-use loop.

    The kernel loop calls ``observe`` after each iteration's tool results, then
    ``terminal_message``; a non-None return ends the loop with that text as the
    final assistant message. The migration app uses this to auto-terminate once
    every requested model has loaded (a domain-specific "done" signal the kernel
    knows nothing about)."""

    def observe(self, turn: Turn) -> None: ...

    def terminal_message(self, turn: Turn) -> str | None: ...


# A pre-execution guard: inspect a pending call (with the turn's prior results)
# and optionally short-circuit it with a synthesised failure ToolCallResult
# instead of running the tool. The migration app uses this to refuse dropping
# an FK-protected field. Returns None to let the call proceed.
DispatchGuard = Callable[[ToolCall, Turn], "ToolCallResult | None"]


class AgentDispatcher:
    """Tool-use loop. Pluggable as an Engine dispatcher."""

    def __init__(
        self,
        *,
        provider: Provider,
        registry: ToolRegistry,
        safety_gate: SafetyGate,
        ctx_factory: CtxFactory,
        max_tool_iterations: int = 50,
        tool_choice: Literal["auto", "any", "none"] | None = "auto",
        request_defaults: LlmRequest | None = None,
        termination_policy: TerminationPolicy | None = None,
        dispatch_guards: list[DispatchGuard] | None = None,
        default_tool_timeout_seconds: float = 300.0,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._safety_gate = safety_gate
        self._ctx_factory = ctx_factory
        self._max_iterations = max_tool_iterations
        self._tool_choice = tool_choice
        self._request_defaults = request_defaults
        # Per-tool override via ``Tool.default_timeout_seconds``.
        self._default_tool_timeout_seconds = default_tool_timeout_seconds
        # App-supplied loop-termination signal + pre-execution guards. Kernel
        # defaults: never force-terminate, no guards.
        self._termination_policy = termination_policy
        self._dispatch_guards: list[DispatchGuard] = list(dispatch_guards or [])
        # The window owner: assembles the per-turn LLM messages (history +
        # working memory) in one place. Compression stays with the TokenBudget
        # middleware for now, so the dispatcher assembles with compress=False.
        self._context_manager = ContextManager()
        # Reset per ``__call__``.
        self._empty_args_streak: dict[str, int] = {}
        # Last-persisted attempt count for throttled checkpoint.
        self._last_persisted_attempts_count = 0

    async def __call__(self, turn: Turn) -> Turn:
        """Run the agent loop for a single engine turn."""
        specs = [tool_to_spec(tool) for tool in self._registry.all_tools()]
        ctx = self._ctx_factory(turn)
        iteration = 0
        final_assistant_content: str | None = None
        self._empty_args_streak = {}

        while True:
            if iteration >= self._max_iterations:
                # ``abort`` not ``raise``: raising bypasses
                # TrajectoryCapture's end-of-turn write.
                turn.abort(
                    f"agent loop for session {turn.session_id!r} did not "
                    f"terminate after {iteration} tool-use iterations"
                )
                log.warning(
                    "agent_dispatcher.exhausted",
                    session_id=turn.session_id,
                    iterations=iteration,
                )
                return turn
            iteration += 1

            response = await self._provider.complete(self._build_request(turn, specs, session=ctx.session))

            # Accumulate usage across every LLM call in this engine turn.
            turn.usage.input_tokens += response.usage.input_tokens
            turn.usage.output_tokens += response.usage.output_tokens
            turn.usage.cached_tokens += response.usage.cached_tokens

            if not response.tool_calls:
                assistant = Message(role="assistant", content=response.content)
                turn.input_messages.append(assistant)
                turn.assistant_message = assistant
                final_assistant_content = response.content
                break

            assistant_turn = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            turn.input_messages.append(assistant_turn)

            for call in response.tool_calls:
                result = await self._execute_tool_call(call, ctx, turn=turn)
                turn.tool_call_results.append(result)
                turn.input_messages.append(
                    Message(
                        role="tool",
                        tool_call_id=call.id,
                        content=_tool_result_to_content(result),
                    )
                )
                # Failures auto-record; successes auto-record only when
                # they overturn a prior failure in blocked_paths.
                if not result.ok:
                    self._auto_record_attempt(turn, call, result, ctx)
                else:
                    self._auto_record_recovery(turn, call, result, ctx)
                # Per-iteration flush so a mid-turn kill leaves a trace.
                await self._persist_iteration(turn, ctx, result)
                # Empty-args hard cap: abort after escalated directives ignored.
                details = result.error_details or {}
                if details.get("empty_args") and self._empty_args_streak.get(call.name, 0) >= _EMPTY_ARGS_HARD_CAP:
                    turn.abort(
                        f"agent loop for session {turn.session_id!r} stopped: "
                        f"tool {call.name!r} called with empty arguments "
                        f"{_EMPTY_ARGS_HARD_CAP} times in a row this turn — "
                        f"model is not responding to escalated directives"
                    )
                    log.warning(
                        "agent_dispatcher.empty_args_hard_cap",
                        session_id=turn.session_id,
                        tool=call.name,
                        streak=_EMPTY_ARGS_HARD_CAP,
                    )
                    return turn

            # App-supplied termination: observe this iteration's results, then
            # let the policy decide whether the loop is "done" (e.g. every
            # requested model loaded) and force-terminate with a synth message.
            if self._termination_policy is not None:
                self._termination_policy.observe(turn)
                policy_msg = self._termination_policy.terminal_message(turn)
                if policy_msg is not None:
                    final_assistant_content = policy_msg
                    assistant = Message(role="assistant", content=final_assistant_content)
                    turn.input_messages.append(assistant)
                    turn.assistant_message = assistant
                    log.info(
                        "agent_dispatcher.force_terminated_by_policy",
                        session_id=turn.session_id,
                        iterations=iteration,
                    )
                    break

        turn.status = "ok" if turn.status == "pending" else turn.status
        log.info(
            "agent_dispatcher.completed",
            session_id=turn.session_id,
            iterations=iteration,
            final_content_len=len(final_assistant_content or ""),
        )
        return turn

    # ──────────────────────── internals ────────────────────────────────────

    def _auto_record_attempt(
        self,
        turn: Turn,
        call: ToolCall,
        result: ToolCallResult,
        ctx: ToolContext,
    ) -> None:
        """Record a failed dispatch into working memory. Best-effort."""
        try:
            args = call.arguments or {}
            subject = args.get("model") or args.get("topic") or args.get("path") or ""
            target = f"{call.name} on {subject}" if subject else call.name
            # Render a few small scalar args; skip the subject keys (already in
            # ``target``) and any bulky payload by SIZE — no app-specific arg
            # names, so this stays domain-neutral (row lists / maps / specs are
            # large and get skipped generically).
            approach_bits: list[str] = []
            for k, v in args.items():
                if k in ("model", "topic", "path"):
                    continue
                vs = str(v)
                if len(vs) > _BULK_ARG_CHARS:
                    continue
                approach_bits.append(f"{k}={vs[:60]}")
                if len(approach_bits) >= 3:
                    break
            approach = f"{call.name}({', '.join(approach_bits)})" if approach_bits else call.name
            lesson_bits: list[str] = []
            if result.error_message:
                lesson_bits.append(result.error_message[:400])
            if result.error_details:
                lesson_bits.append(f"details: {str(result.error_details)[:200]}")
            lesson = " | ".join(lesson_bits) or "tool failed without error_message"

            ctx.session.working_memory.record(
                target=target,
                approach=approach,
                outcome="failed",
                lesson=lesson,
                turn_index=turn.turn_index,
                tool_name=call.name,
            )
            log.info(
                "agent_dispatcher.auto_record_attempt",
                session_id=turn.session_id,
                target=target,
                tool=call.name,
            )
        except Exception as exc:
            log.warning(
                "agent_dispatcher.auto_record_attempt_failed",
                session_id=turn.session_id,
                tool=call.name,
                error=type(exc).__name__,
                message=str(exc)[:300],
            )

    def _auto_record_recovery(
        self,
        turn: Turn,
        call: ToolCall,
        result: ToolCallResult,
        ctx: ToolContext,
    ) -> None:
        """Record a success that overturns a previously-blocked target."""
        try:
            args = call.arguments or {}
            subject = args.get("model") or args.get("topic") or args.get("path") or ""
            target = f"{call.name} on {subject}" if subject else call.name
            wm = ctx.session.working_memory
            # Only record if the target is currently blocked.
            blocked_for_target = [b for b in wm.blocked_paths if b.startswith(target + " via ")]
            if not blocked_for_target:
                return
            wm.record(
                target=target,
                approach=f"{call.name} succeeded after prior failure",
                outcome="success",
                lesson="prior blocked_path overturned",
                turn_index=turn.turn_index,
                tool_name=call.name,
            )
            # Remove the blocked_path entries for this target.
            wm.blocked_paths = [b for b in wm.blocked_paths if not b.startswith(target + " via ")]
            log.info(
                "agent_dispatcher.auto_record_recovery",
                session_id=turn.session_id,
                target=target,
                unblocked=len(blocked_for_target),
            )
        except Exception as exc:
            log.warning(
                "agent_dispatcher.auto_record_recovery_failed",
                session_id=turn.session_id,
                tool=call.name,
                error=type(exc).__name__,
                message=str(exc)[:300],
            )

    async def _persist_iteration(self, turn: Turn, ctx: ToolContext, result: ToolCallResult) -> None:
        """Flush this dispatch to SQLite + checkpoint. Best-effort."""
        try:
            await ctx.sqlite.append_turn(
                session_id=turn.session_id,
                turn_index=turn.turn_index,
                role="tool",
                tool_name=result.tool_name,
                tool_ok=result.ok,
                latency_ms=result.latency_ms,
                content_inline=json.dumps(result.output) if result.output is not None else None,
            )
            turn.persisted_tool_count = len(turn.tool_call_results)
        except Exception as exc:
            log.warning(
                "agent_dispatcher.persist_sqlite_failed",
                session_id=turn.session_id,
                tool=result.tool_name,
                error=type(exc).__name__,
                message=str(exc)[:300],
            )
        # Throttle the MinIO blob save: every Nth tool dispatch, or
        # whenever working_memory accumulated a new attempt.
        wm = ctx.session.working_memory
        current_attempts = len(wm.attempts)
        wm_dirty = current_attempts > self._last_persisted_attempts_count
        cadence_due = (len(turn.tool_call_results) % _CHECKPOINT_CADENCE) == 0
        if wm_dirty or cadence_due:
            try:
                await save_session(
                    ctx.session,
                    sqlite=ctx.sqlite,
                    minio=ctx.minio,
                    checkpoint="latest",
                )
                # Engine reads this to skip its redundant per-turn save.
                turn.checkpoint_saved_by_dispatcher = True
                self._last_persisted_attempts_count = current_attempts
            except Exception as exc:
                log.warning(
                    "agent_dispatcher.persist_checkpoint_failed",
                    session_id=turn.session_id,
                    error=type(exc).__name__,
                    message=str(exc)[:300],
                )

    def _build_request(self, turn: Turn, specs: list[Any], *, session: Any = None) -> LlmRequest:
        base = (
            self._request_defaults.model_copy(deep=True)
            if self._request_defaults is not None
            else LlmRequest(messages=[])
        )
        # Assemble the window through the ContextManager: it folds working
        # memory in as a system message after the leading system prompt (which
        # survives token-budget compression). compress=False leaves the budget
        # step to TokenBudget middleware. This replaces the previous inline
        # injection so there is one assembly path (agentix#20).
        wm_render: str | None = None
        if session is not None:
            wm = getattr(session, "working_memory", None)
            if wm is not None:
                wm_render = wm.render_for_system_prompt() or None
        assembled = self._context_manager.assemble(
            list(turn.input_messages), working_memory_render=wm_render, compress=False
        )
        base.messages = assembled.messages
        base.tools = specs if specs else None
        base.tool_choice = self._tool_choice if specs else None
        return base

    async def _execute_tool_call(
        self,
        call: ToolCall,
        ctx: ToolContext,
        *,
        turn: Turn | None = None,
    ) -> ToolCallResult:
        """Resolve + coerce + run a single tool call via the safety gate."""
        try:
            tool = self._registry.get(call.name)
        except KeyError as exc:
            # Recover from XML-template-bleed in the tool name: suggest the
            # closest registered tool and let the agent retry. Truly-unknown
            # names raise AgentToolNotInRegistry.
            suggestion = _suggest_tool_name(call.name, self._registry)
            if suggestion is not None:
                log.warning(
                    "agent_dispatcher.malformed_tool_name",
                    requested=call.name,
                    suggestion=suggestion,
                )
                return ToolCallResult(
                    call_id=call.id,
                    tool_name=call.name,
                    ok=False,
                    error_message=(
                        f"unknown tool {call.name!r}. Did you mean "
                        f"{suggestion!r}? Re-emit the call with the "
                        f"correct name. The tool name should not contain "
                        f"XML tags like </arg_value> or other formatting "
                        f"artifacts — pass only the bare snake_case "
                        f"name."
                    ),
                    error_details={
                        "unknown_tool": call.name,
                        "suggestion": suggestion,
                        "registered_tools": sorted(t.name for t in self._registry.all_tools()),
                    },
                )
            raise AgentToolNotInRegistry(call.name) from exc

        # Pre-detect empty-args calls for tools with required fields and
        # synthesise a directive error instead of an opaque pydantic stack.
        # Track per-tool consecutive empty-args to escalate the directive;
        # a non-empty call to the same tool resets the streak.
        if call.arguments:
            self._empty_args_streak.pop(call.name, None)
        empty_args_result = _empty_args_guard(call, tool, streak=self._empty_args_streak.get(call.name, 0))
        if empty_args_result is not None:
            self._empty_args_streak[call.name] = self._empty_args_streak.get(call.name, 0) + 1
            return empty_args_result

        # App-supplied pre-execution guards may refuse a call before it runs
        # (e.g. the migration app refusing to drop an FK-protected field).
        if turn is not None:
            for guard in self._dispatch_guards:
                blocked = guard(call, turn)
                if blocked is not None:
                    return blocked

        try:
            # Coerce args through the tool's pydantic schema inside the
            # try/except so a bad arg becomes a recoverable tool_result
            # (surfaced as ``validation_errors``) rather than a session abort.
            input_model = tool.input_schema.model_validate(call.arguments)
            # Tag for ``ctx.progress(...)`` events.
            ctx._current_tool_name = call.name
            input_override = getattr(input_model, "timeout_s", None)
            timeout_s = float(
                input_override
                if input_override is not None
                else (getattr(tool, "default_timeout_seconds", None) or self._default_tool_timeout_seconds)
            )
            try:
                output = await asyncio.wait_for(
                    self._safety_gate.execute(tool, input_model, ctx),
                    timeout=timeout_s,
                )
            except TimeoutError:
                log.warning(
                    "agent_dispatcher.tool_timeout",
                    tool=call.name,
                    timeout_s=timeout_s,
                    session_id=getattr(ctx.session, "id", None),
                )
                return ToolCallResult(
                    call_id=call.id,
                    tool_name=call.name,
                    ok=False,
                    error_message=(
                        f"tool {call.name!r} exceeded wall-clock timeout of "
                        f"{timeout_s:.0f}s — retry with a smaller scope "
                        "(e.g. extract with limit=, load with smaller batch_size, "
                        "or narrower domain filter)"
                    ),
                    error_details={"kind": "wall_clock_timeout", "timeout_s": timeout_s},
                    latency_ms=int(timeout_s * 1000),
                )
            return ToolCallResult(
                call_id=call.id,
                tool_name=call.name,
                ok=True,
                output=_coerce_output(output),
                latency_ms=0,  # individual tools already log their own latency
            )
        except (SafetyGateBlocked, SafetyVerifyFailed) as exc:
            # Safety-layer exceptions mean abort + rollback (already run).
            # Re-raise rather than convert to a tool_result.
            log.warning(
                "agent_dispatcher.safety_halt",
                tool=call.name,
                error=type(exc).__name__,
                message=str(exc)[:500],
            )
            raise
        except Exception as exc:
            # Every other exception is recoverable: return ok=False with
            # structured detail so the agent can read the error and retry.
            log.warning(
                "agent_dispatcher.tool_failed",
                tool=call.name,
                error=type(exc).__name__,
                message=str(exc)[:500],
            )
            return ToolCallResult(
                call_id=call.id,
                tool_name=call.name,
                ok=False,
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
                error_details=_extract_error_details(exc),
                latency_ms=0,
            )


def _tool_result_to_content(result: ToolCallResult) -> str:
    """Serialise a ToolCallResult to structured JSON for the next LLM turn.

    ``details`` carries structured error payloads (app error detail,
    pydantic validation errors) rather than a one-line summary.
    """
    payload: dict[str, Any] = {"ok": result.ok}
    if result.ok:
        payload["output"] = result.output
    else:
        payload["error"] = result.error_message
        if result.error_details is not None:
            payload["details"] = result.error_details
    return json.dumps(payload, default=str)


def _extract_error_details(exc: BaseException) -> Any:
    """Return structured detail from an exception, or None.

    App exceptions expose their own structured payload via a
    ``to_error_details()`` method (e.g. the migration app's ``LoadToOdooError``
    returns its ``messages`` / directive / protected-fields). The kernel adds
    two domain-neutral fallbacks: pydantic ``ValidationError.errors()`` and the
    kernel ``SafetyVerifyFailed.findings``.
    """
    # App-specific structured detail — the exception decides its own shape.
    hook = getattr(exc, "to_error_details", None)
    if callable(hook):
        try:
            detail = hook()
        except Exception:
            detail = None
        if detail:
            return detail
    # Pydantic ValidationError has ``errors()`` (domain-neutral).
    errors_fn = getattr(exc, "errors", None)
    if callable(errors_fn):
        try:
            errs = errors_fn()
        except Exception:
            errs = None
        if isinstance(errs, list) and errs:
            return {"validation_errors": errs}
    # Kernel SafetyVerifyFailed carries ``findings``.
    findings = getattr(exc, "findings", None)
    if isinstance(findings, list) and findings:
        return {"findings": findings}
    return None


_XML_TAG_RE = re.compile(r"<[^>]+>")


def _suggest_tool_name(requested: str, registry: ToolRegistry) -> str | None:
    """Best-effort recovery from XML-template-bleed in tool names.

    Strips all ``<...>`` tags and surrounding noise via regex, then
    suggests a registered tool by exact match on the cleaned form, falling
    back to the longest registered name that is a prefix of the cleaned
    string. Returns ``None`` when no high-confidence match exists.
    """
    if not requested:
        return None
    registered = {t.name for t in registry.all_tools()}

    # Strip all <...> tags and surrounding noise.
    cleaned = _XML_TAG_RE.sub("", requested)
    cleaned = cleaned.strip(" \t\n\"'")

    # Exact match, only when cleaning actually changed the name.
    if cleaned and cleaned != requested and cleaned in registered:
        return cleaned

    # Prefix-match fallback: longest registered name that is a prefix of
    # the cleaned string (length-descending so the most specific wins).
    if cleaned:
        for candidate in sorted(registered, key=len, reverse=True):
            if cleaned.startswith(candidate) and candidate != requested:
                return candidate

    return None


# Max char length of a single tool-call arg rendered into working-memory's
# "approach" string; longer values (row lists, maps, specs) are skipped by size.
_BULK_ARG_CHARS = 120

_EMPTY_ARGS_ESCALATE_AT = 2
# Consecutive empty-args calls from the same tool in a turn that abort
# the turn entirely (hard cost bound when the escalated directive is ignored).
_EMPTY_ARGS_HARD_CAP = 5

# Save the MinIO session checkpoint every N tool dispatches (or whenever
# working_memory accumulates a new attempt).
_CHECKPOINT_CADENCE = 5


def _empty_args_guard(call: ToolCall, tool: Tool, *, streak: int = 0) -> ToolCallResult | None:
    """Synthesise an ok=False directive ToolCallResult for an empty-args
    call to a tool with required fields, bypassing the opaque pydantic
    "Field required" stack.

    ``streak`` is the count of consecutive prior empty-args calls from the
    same tool this turn; at ``_EMPTY_ARGS_ESCALATE_AT`` the directive
    escalates. Returns ``None`` for a well-formed call.
    """
    if call.arguments:
        return None

    required: list[tuple[str, str]] = []
    for name, field in tool.input_schema.model_fields.items():
        if field.is_required():
            required.append((name, _field_type_hint(field)))

    if not required:
        return None

    escalated = streak >= _EMPTY_ARGS_ESCALATE_AT
    log.warning(
        "agent_dispatcher.empty_args",
        tool=call.name,
        required=[n for n, _ in required],
        streak=streak + 1,  # this call is the (streak+1)-th
        escalated=escalated,
    )

    field_list = ", ".join(f"{n} ({t})" for n, t in required)
    if escalated:
        # Blunt directive once the basic one has been ignored 3+ times.
        error_message = (
            f"STOP CALLING {call.name!r} WITH EMPTY ARGUMENTS — you have "
            f"now done so {streak + 1} times in a row this turn. The basic "
            f"directive in the previous tool result was ignored. Either "
            f"(a) populate ALL required fields ({field_list}) and re-emit, "
            f"or (b) call a DIFFERENT tool. Do NOT call {call.name!r} "
            f"again without arguments — it will keep failing the same way."
        )
    else:
        error_message = (
            f"empty arguments — your previous tool call to {call.name!r} "
            f"had no arguments populated. Required fields: {field_list}. "
            f"Re-emit the call with ALL required fields. "
            f"Do NOT retry without arguments."
        )

    return ToolCallResult(
        call_id=call.id,
        tool_name=call.name,
        ok=False,
        error_message=error_message,
        error_details={
            "empty_args": True,
            "tool": call.name,
            "required_fields": [{"name": n, "type": t} for n, t in required],
            "consecutive_empty_args": streak + 1,
            "escalated": escalated,
        },
        latency_ms=0,
    )


def _field_type_hint(field: Any) -> str:
    """Best-effort short type label for a pydantic FieldInfo."""
    annotation = getattr(field, "annotation", None)
    if annotation is None:
        return "unknown"
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    return str(annotation)


def _coerce_output(output: Any) -> Any:
    """Project tool outputs (usually pydantic models) into JSON-friendly dicts."""
    if hasattr(output, "model_dump"):
        return output.model_dump(mode="json")
    return output


# Keep ``Tool`` referenced so mypy doesn't flag the import.
_ = Tool
