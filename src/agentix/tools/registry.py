"""Tool registry — maps name → Tool.

An in-process dict with ``register()``, ``get()``, and ``list()``. The
skills loader scans ``skills/`` and calls ``register()`` for every tool
it imports. Conflicting registrations raise — a skill can't silently
shadow a builtin.
"""

from __future__ import annotations

import structlog

from agentix.tools.base import Tool, ToolSpec

log = structlog.get_logger(__name__)


class ToolConflict(Exception):
    """Two tools tried to register under the same name."""


class ToolRegistry:
    """In-process registry keyed by tool name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Strict register — raises on conflict or missing verifier.

        Used for built-in tools, where a validation failure is a bug
        in our canon and should fail the service loudly.
        """
        if tool.name in self._tools:
            raise ToolConflict(f"tool {tool.name!r} already registered by {type(self._tools[tool.name]).__name__}")
        if tool.mutates_target and not tool.verifier:
            raise ValueError(f"tool {tool.name!r}: mutates_target=True requires a verifier")
        self._tools[tool.name] = tool
        log.debug("tools.registered", name=tool.name)

    def try_register(self, tool: Tool) -> bool:
        """Lenient register — log + skip on validation failure, keep going.

        Returns True if registered, False if skipped. Used by the
        skills loader: one broken customer skill must not take down
        the whole service. The warning surfaces the offending tool
        name so operators can still find it.
        """
        try:
            self.register(tool)
        except ToolConflict as exc:
            log.warning("tools.register_skipped_conflict", name=tool.name, error=str(exc))
            return False
        except ValueError as exc:
            log.warning("tools.register_skipped_missing_verifier", name=tool.name, error=str(exc))
            return False
        return True

    def register_provider_gated(self, tool: Tool, *, available: set[str]) -> bool:
        """Register ``tool`` unless its ``required_provider`` gate is unmet.

        Declarative replacement for ad-hoc ``if provider is not None:
        registry.register(...)`` conditionals in apps. ``available`` is the
        set of active provider names (e.g. from
        ``agentix.config.enabled_providers``).

        * ``required_provider`` absent / ``None`` → always registered.
        * sentinel ``"llm"`` / ``"*"`` → registered only if *any* provider
          is available.
        * a concrete name → registered only if in ``available``.

        Registration itself is strict (:meth:`register`) once the gate
        passes — a provider-met tool with a conflict is still a canon bug.
        Returns True if registered, False if skipped (logged at info).
        """
        required = getattr(tool, "required_provider", None)
        if required is not None:
            met = bool(available) if required in ("llm", "*") else required in available
            if not met:
                log.info(
                    "tools.register_skipped_no_provider",
                    name=tool.name,
                    required_provider=required,
                    available=sorted(available),
                )
                return False
        self.register(tool)
        return True

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def all_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def specs(self) -> list[ToolSpec]:
        """Return JSON-schema advertisements suitable for LLM tool-calling."""
        return [
            ToolSpec(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema.model_json_schema(),
                output_schema=t.output_schema.model_json_schema(),
                mutates_target=t.mutates_target,
                verifier=t.verifier,
            )
            for t in self.all_tools()
        ]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
