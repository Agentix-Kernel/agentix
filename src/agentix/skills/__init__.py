"""Skill functionality — the agent's skill-loading surface, all in one package.

Three layers live here:

* :class:`SkillCatalog` (``catalog.py``) — the **agent-agnostic, open-standard**
  reader. Any agent process points it at *its own* per-process ``skills_root``;
  a bundle is identified by its ``SKILL.md`` YAML frontmatter (``name`` +
  ``description``), surfaced cheaply at session start, with bodies pulled on
  demand (progressive disclosure).
* the incumbent **manifest loader** (``loader.py``: ``load_skills`` /
  ``list_skill_manifests`` / ``register_activated_skills``) — bound to
  ``skills/<name>/manifest.json`` + recon-phase trigger predicates; registers a
  bundle's ``tool.py`` skill-scoped tools. Re-exported from ``ludo.tools`` for
  back-compat.
* the **consult tool** (``consult_skill.py``) — reads a named skill's ``SKILL.md``
  body at runtime (``read_file`` is sandboxed and can't reach ``skills/``).

Cluster design: ``docs/proposals/agent-skills-catalog.md``,
``tool-skill-calling.md``.
"""

from __future__ import annotations

from agentix.skills.catalog import SkillBundle, SkillCatalog
from agentix.skills.consult_skill import (
    ConsultSkill,
    ConsultSkillInput,
    ConsultSkillOutput,
)
from agentix.skills.loader import (
    SkillManifestError,
    list_skill_manifests,
    load_skills,
    register_activated_skills,
)

__all__ = [
    "ConsultSkill",
    "ConsultSkillInput",
    "ConsultSkillOutput",
    "SkillBundle",
    "SkillCatalog",
    "SkillManifestError",
    "list_skill_manifests",
    "load_skills",
    "register_activated_skills",
]
