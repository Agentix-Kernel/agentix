"""Open-standard skill catalog — scan a per-agent ``skills_root``.

Selection model (the generalization): rather than gate each bundle behind
trigger predicates the recon phase evaluates, the catalog surfaces every
bundle's ``(name, description)`` cheaply at session start and lets the agent's
Cortex pull the full ``SKILL.md`` body on demand (progressive disclosure). This
is the Agent Skills open standard and is agent-agnostic — a business agent's
session is triggered by an inbound A2A request, a migration session by a version
pair, but both consume the same catalog.

The incumbent ``ludo.tools.skills_loader`` (manifest + trigger predicates) is
untouched; this is additive. Tool registration for skills carrying a ``tool.py``
delegates to :func:`ludo.tools.skills_loader.register_activated_skills`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter
import structlog

from agentix.skills.loader import register_activated_skills
from agentix.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SkillBundle:
    """One discovered skill bundle.

    ``name`` / ``description`` drive the cheap session-start surfacing; the
    agent reads ``skill_md_path`` in full only when it decides the skill is
    relevant. ``has_tools`` flags bundles that register skill-scoped primitives
    via ``tool.py`` (so the caller knows activation has a side effect).
    """

    name: str
    description: str
    bundle_dir: Path
    #: Absolute path to ``SKILL.md`` if present (the progressive-disclosure body).
    skill_md_path: Path | None = None
    #: True when a ``manifest.json`` declares skill-scoped tools (``tool.py``).
    has_tools: bool = False
    #: Reference templates (leading-underscore dir name) — excluded from describe().
    reference_only: bool = False
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)


class SkillCatalog:
    """Per-agent view over a ``skills_root`` directory."""

    def __init__(self, skills_root: Path | str) -> None:
        self.root = Path(skills_root)

    def bundles(self) -> list[SkillBundle]:
        """Discover every bundle under ``skills_root``.

        A directory is a bundle when it carries a ``SKILL.md`` (open standard)
        or a ``manifest.json`` (legacy). Directories with neither are ignored.
        Best-effort: an unreadable bundle logs a warning and is skipped.
        """
        if not self.root.exists():
            log.info("skills.root_missing", root=str(self.root))
            return []
        out: list[SkillBundle] = []
        for bundle_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            bundle = self._read_bundle(bundle_dir)
            if bundle is not None:
                out.append(bundle)
        return out

    def describe(self) -> list[tuple[str, str, str]]:
        """Return ``(name, description, skill_md_path)`` for session-start
        surfacing. Reference templates (``_example_*``) are excluded — they
        are not real capabilities the agent should consider."""
        rows: list[tuple[str, str, str]] = []
        for b in self.bundles():
            if b.reference_only:
                continue
            path = str(b.skill_md_path) if b.skill_md_path is not None else str(b.bundle_dir)
            rows.append((b.name, b.description, path))
        return rows

    def activate(self, names: list[str], registry: ToolRegistry) -> list[str]:
        """Register skill-scoped tools for the named bundles into ``registry``.

        Delegates to the incumbent loader so there is one tool-import path.
        Doctrine-only bundles (no ``tool.py``) are a no-op here; their value is
        the ``SKILL.md`` body the agent reads, not a registered tool. Names that
        carry tools but have no ``manifest.json`` (pure open-standard stubs) are
        silently skipped by the delegate, which scans ``*/manifest.json``.
        """
        return register_activated_skills(self.root, names, registry)

    # ── internals ────────────────────────────────────────────────────────

    def _read_bundle(self, bundle_dir: Path) -> SkillBundle | None:
        skill_md = bundle_dir / "SKILL.md"
        manifest = bundle_dir / "manifest.json"
        if not skill_md.exists() and not manifest.exists():
            return None

        meta = self._read_skill_md_frontmatter(skill_md) if skill_md.exists() else {}
        man = self._read_manifest(manifest) if manifest.exists() else {}

        name = str(meta.get("name") or man.get("name") or bundle_dir.name)
        description = str(meta.get("description") or man.get("description") or "")
        # Open standard uses ``allowed-tools``; legacy manifest uses ``tools``.
        allowed = meta.get("allowed-tools") or man.get("tools") or []
        allowed_tools = tuple(str(t) for t in allowed) if isinstance(allowed, list) else ()

        return SkillBundle(
            name=name,
            description=description,
            bundle_dir=bundle_dir,
            skill_md_path=skill_md if skill_md.exists() else None,
            has_tools=bool(man.get("tools")),
            reference_only=bundle_dir.name.startswith("_"),
            allowed_tools=allowed_tools,
        )

    @staticmethod
    def _read_skill_md_frontmatter(path: Path) -> dict[str, Any]:
        try:
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("skill.skill_md_unreadable", path=str(path), error=str(exc))
            return {}
        meta = post.metadata
        return dict(meta) if isinstance(meta, dict) else {}

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skill.manifest_unreadable", path=str(path), error=str(exc))
            return {}
        return data if isinstance(data, dict) else {}
