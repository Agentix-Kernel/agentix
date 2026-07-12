"""WorkingMemory — structured "tried / failed / learned" log on Session.

Rendered by ``agent_dispatcher`` as a system message before each LLM
call. The compression strategy preserves every ``role="system"``
message verbatim, so attempts and lessons survive past the context
limit where tool-result history collapses.

Data + render only. ``record_attempt`` (tool) is the write surface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_MAX_RENDER_CHARS = 6000  # ~1500 tokens, well under 16k input budget
_RECENT_ATTEMPTS_FULL = 12  # older attempts collapse to one-line summary

AttemptOutcome = Literal["success", "failed"]


class AttemptRecord(BaseModel):
    """One thing the agent tried, with what it learned from the outcome."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(
        ...,
        description=(
            "What the attempt was directed at — usually an entity + field "
            "or an entity + action. E.g. 'customer.name', "
            "'invoice:post', 'order lines bulk write'."
        ),
    )
    approach: str = Field(
        ...,
        description=(
            "Short description of HOW the attempt was made — the strategy "
            "the agent chose. E.g. 'direct write with name field', "
            "'set parent first then let computed propagate', 'retry with "
            "a narrower scope'."
        ),
    )
    outcome: AttemptOutcome = Field(
        ...,
        description="'success' if the attempt achieved its goal; 'failed' otherwise.",
    )
    lesson: str = Field(
        ...,
        description=(
            "What was learned from the outcome — stated so a future "
            "decision can use it. On failure: WHY it failed (the rule "
            "violated, the constraint hit). On success: WHAT worked and "
            "under what conditions, so the agent can repeat it for "
            "similar targets."
        ),
    )
    turn_index: int = Field(
        ...,
        description="The session turn the attempt happened on. Lets the supervisor compute thrash velocity.",
    )
    tool_name: str | None = Field(
        default=None,
        description="The tool the attempt called, if any. Empty for purely-reasoning attempts.",
    )


class WorkingMemory(BaseModel):
    """Per-session structured record of attempts, dead ends, and current plan."""

    model_config = ConfigDict(extra="forbid")

    attempts: list[AttemptRecord] = Field(default_factory=list)
    blocked_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Strategies known not to work, stated as '<target> via <approach>'. "
            "Rendered prominently so the agent sees them before each turn."
        ),
    )
    active_strategy: str = Field(
        default="",
        description=(
            "Current high-level plan, in one sentence. The agent updates "
            "this when it commits to a strategy or when it abandons one."
        ),
    )

    def record(
        self,
        *,
        target: str,
        approach: str,
        outcome: AttemptOutcome,
        lesson: str,
        turn_index: int,
        tool_name: str | None = None,
        add_to_blocked: bool = False,
    ) -> AttemptRecord:
        """Append an attempt; optionally flag the (target, approach) as a dead end."""
        rec = AttemptRecord(
            target=target.strip(),
            approach=approach.strip(),
            outcome=outcome,
            lesson=lesson.strip(),
            turn_index=turn_index,
            tool_name=tool_name,
        )
        self.attempts.append(rec)
        if add_to_blocked or outcome == "failed":
            line = f"{rec.target} via {rec.approach}"
            if line not in self.blocked_paths:
                self.blocked_paths.append(line)
        return rec

    def set_strategy(self, strategy: str) -> None:
        """Replace the active strategy. Empty string clears it."""
        self.active_strategy = strategy.strip()

    def is_blocked(self, target: str, approach: str) -> bool:
        """Has this exact (target, approach) pair been recorded as a dead end?"""
        line = f"{target.strip()} via {approach.strip()}"
        return line in self.blocked_paths

    def render_for_system_prompt(self) -> str:
        """Render working memory as a markdown block for system-message injection.

        Empty memory renders as the empty string — callers can use that
        to skip injection on a fresh session.
        """
        if not self.attempts and not self.blocked_paths and not self.active_strategy:
            return ""

        parts: list[str] = ["## Working memory (this session)"]
        parts.append("")
        parts.append(
            "This is your structured record of what you have already tried this "
            "session and what you learned. It survives context compression. "
            "Consult it before deciding your next tool call — if a target+approach "
            "is in `Blocked paths`, do NOT retry it; pick a different approach or "
            "consult_memory/diagnose for an alternative."
        )
        parts.append("")

        if self.active_strategy:
            parts.append(f"**Active strategy:** {self.active_strategy}")
            parts.append("")

        if self.blocked_paths:
            parts.append("**Blocked paths (known dead ends — do not repeat):**")
            for line in self.blocked_paths:
                parts.append(f"- {line}")
            parts.append("")

        if self.attempts:
            parts.append("**Attempts log (most recent last):**")
            if len(self.attempts) > _RECENT_ATTEMPTS_FULL:
                older = self.attempts[:-_RECENT_ATTEMPTS_FULL]
                recent = self.attempts[-_RECENT_ATTEMPTS_FULL:]
                parts.append(
                    f"- … {len(older)} earlier attempt(s) elided; tool names: "
                    f"{', '.join(sorted({a.tool_name or '-' for a in older}))}"
                )
            else:
                recent = list(self.attempts)
            for a in recent:
                tag = "✓" if a.outcome == "success" else "✗"
                tool_suffix = f" ({a.tool_name})" if a.tool_name else ""
                parts.append(
                    f"- {tag} turn {a.turn_index}{tool_suffix} — **{a.target}** via *{a.approach}*: {a.lesson}"
                )
            parts.append("")

        rendered = "\n".join(parts).strip()
        if len(rendered) > _MAX_RENDER_CHARS:
            rendered = rendered[:_MAX_RENDER_CHARS] + "\n\n…[working memory truncated to budget]"
        return rendered


__all__ = [
    "AttemptOutcome",
    "AttemptRecord",
    "WorkingMemory",
]
