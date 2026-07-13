"""consult_skill — read a named skill's SKILL.md body (progressive disclosure).

The agent's ``Available skills`` system block surfaces each skill's name +
description cheaply. When one matches the situation, the Cortex calls
``consult_skill(name=…)`` to pull the full procedure. This is the consult tier
of the remediation cascade (CLAUDE.md § Remediation tiers).

Distinct from ``read_file``: that tool is sandboxed to the module-port spike's
source/output root and cannot reach ``skills/``. ``consult_skill`` reads from the
agent's own skill catalog root (``ToolContext.skills_root``).
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from agentix.tools.base import Tool, ToolContext, ensure_input

log = structlog.get_logger(__name__)

#: SKILL.md bodies are small (~5 KB); cap defensively.
_MAX_CHARS = 64_000


class ConsultSkillInput(BaseModel):
    name: str = Field(
        ...,
        description=(
            "The skill name exactly as listed in the 'Available skills' block. "
            "Returns that skill's full SKILL.md procedure. Do not guess a skill's "
            "contents from its name — consult it."
        ),
    )


class ConsultSkillOutput(BaseModel):
    name: str
    path: str
    content: str
    truncated: bool = False


class ConsultSkill(Tool):
    name = "consult_skill"
    description = (
        "Read the full SKILL.md procedure for a named skill from the agent's skill "
        "catalog. Use when a skill in the 'Available skills' list has a description "
        "matching the situation you face — consult it before acting. Returns the "
        "skill's strategy doctrine."
    )
    input_schema = ConsultSkillInput
    output_schema = ConsultSkillOutput
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        # Lazy import: keeps tools.__init__ free of a tools→skills→tools.registry
        # import-order dependency at module load.
        from agentix.skills import SkillCatalog

        params = ensure_input(input, ConsultSkillInput)
        root = getattr(ctx, "skills_root", "skills") or "skills"
        bundles = [b for b in SkillCatalog(root).bundles() if not b.reference_only]  # multi-root aware
        for b in bundles:
            if b.name == params.name:
                if b.skill_md_path is None:
                    raise ValueError(f"consult_skill: skill {params.name!r} has no SKILL.md body to read.")
                text = b.skill_md_path.read_text(encoding="utf-8")
                truncated = len(text) > _MAX_CHARS
                log.info("consult_skill", name=b.name, bytes=len(text), truncated=truncated)
                return ConsultSkillOutput(
                    name=b.name,
                    path=str(b.skill_md_path),
                    content=text[:_MAX_CHARS],
                    truncated=truncated,
                )
        available = ", ".join(sorted(b.name for b in bundles)) or "(none)"
        raise ValueError(f"consult_skill: no skill named {params.name!r}. Available: {available}")
