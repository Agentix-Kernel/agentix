"""Skills loader — scan ``skills/<name>/manifest.json`` at startup.

Each skill bundle is a directory following the v2 schema documented
in ``skills/SCHEMA.md``. Minimum required:

* ``manifest.json`` — ``{"name", "version", "description", "tools": [...],
  "trigger": {...}}``. The legacy ``customer`` field is accepted but
  ignored with a deprecation warning — skills under v2 are general,
  not per-customer.
* ``tool.py`` — a python module exporting a ``register(registry)``
  function. The loader imports the module and hands it the shared
  registry so the bundle can register its tool(s).
* ``SKILL.md`` (recommended) — the doctrine the agent loads when the
  skill triggers. Loader doesn't read it; the recon phase does.

No hot-reload in v0.1 (arch.md §10.2). A skill's tools conflict
with builtins only if the skill deliberately shadows — the registry
raises ``ToolConflict`` in that case.

Trigger-predicate evaluation is the **recon phase's** responsibility,
not the loader's. The loader's job is to validate the manifest and
register the skill's tools so they're available when the recon phase
decides to load the skill. This separation keeps the loader simple
and the trigger logic close to where the recon report is built.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import structlog

from agentix.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


class SkillManifestError(Exception):
    """Raised when a skill's ``manifest.json`` is malformed or missing keys."""


def load_skills(skills_root: Path | str, registry: ToolRegistry) -> list[dict[str, Any]]:
    """Scan ``skills_root`` and register every bundle that validates.

    Returns the list of loaded manifests. Bundles that fail to load
    (missing ``tool.py``, bad manifest, import error) log a warning but
    don't abort — skills are best-effort, the core still runs without
    them.
    """
    root = Path(skills_root)
    if not root.exists():
        log.info("skills.root_missing", root=str(root))
        return []

    loaded: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = _read_manifest(manifest_path)
            # Doctrine-only skills (no declared tools) skip the tool.py
            # import + register call entirely. They contribute strategy
            # template only — surfaced into recon via SKILL.md.
            if manifest.get("tools"):
                module = _import_tool_module(manifest_path.parent, manifest)
                register_fn = getattr(module, "register", None)
                if register_fn is None:
                    raise SkillManifestError(f"{manifest_path}: tool.py missing register() function")
                register_fn(registry)
            loaded.append(manifest)
            log.info(
                "skill.loaded",
                name=manifest["name"],
                version=manifest.get("version"),
                customer=manifest.get("customer"),
                path=str(manifest_path.parent),
            )
        except Exception as exc:
            log.warning(
                "skill.load_failed",
                path=str(manifest_path),
                error=f"{type(exc).__name__}: {exc}",
            )
    return loaded


def list_skill_manifests(skills_root: Path | str) -> list[dict[str, Any]]:
    """Scan ``skills_root`` and return every valid manifest WITHOUT
    importing or registering any tools.

    Used by the recon phase to evaluate trigger predicates before the
    orchestrator decides which skills are active for the current
    migration. Tool registration is a separate step run only for
    activated skills — keeps process start cheap and side-effects
    explicit.

    Bundles whose manifest fails validation log a warning (same as
    :func:`load_skills`) and are skipped — skills are best-effort.
    """
    root = Path(skills_root)
    if not root.exists():
        log.info("skills.root_missing", root=str(root))
        return []
    manifests: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = _read_manifest(manifest_path)
        except Exception as exc:
            log.warning(
                "skill.manifest_invalid",
                path=str(manifest_path),
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        manifest["_bundle_dir"] = str(manifest_path.parent)
        manifests.append(manifest)
    return manifests


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillManifestError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillManifestError(f"{path}: manifest must be a JSON object")
    # v2 schema — see skills/SCHEMA.md. ``customer`` is intentionally
    # NOT required: under v2, skills are general, not per-customer.
    # Bundles still carrying ``customer`` are accepted with a
    # deprecation warning so legacy bundles don't break the loader.
    # ``tools`` is optional — doctrine-only skills (no tool.py) ship
    # strategy templates without skill-scoped primitives.
    for required in ("name", "version"):
        if required not in data:
            raise SkillManifestError(f"{path}: missing required key {required!r}")
    data.setdefault("tools", [])
    if "customer" in data:
        log.warning(
            "skill.deprecated_customer_field",
            path=str(path),
            note="skills are general, not per-customer; remove `customer` from manifest.json — see skills/SCHEMA.md",
        )
    # ``trigger`` is required for production skills but tolerated as
    # absent on reference templates (leading-underscore names).
    if "trigger" not in data and not str(data.get("name", "")).startswith("_"):
        log.warning(
            "skill.missing_trigger",
            path=str(path),
            note="production skills must declare a `trigger` predicate — see skills/SCHEMA.md",
        )
    return data


def register_activated_skills(
    skills_root: Path | str,
    activated_names: list[str],
    registry: ToolRegistry,
) -> list[str]:
    """Register skill-scoped tools from bundles whose names appear in
    ``activated_names`` (typically the set decided by the recon phase's
    trigger evaluator).

    Doctrine-only skills (no ``tools`` declared, no ``tool.py``) are
    counted as activated but contribute zero tools — their SKILL.md
    travels via the recon summary into the agent's first user message,
    not via the tool registry.

    Returns the names of skills that were successfully activated.
    Bundles that fail to load (missing ``tool.py`` for a declared
    tool, import error, …) log a warning and are skipped — skill
    activation is best-effort, the core still runs without them.

    Idempotent: calling twice with the same registry re-registers
    tools, which raises a duplicate-name error from the registry.
    Callers should pass a fresh registry per session.
    """
    root = Path(skills_root)
    if not root.exists():
        log.info("skills.root_missing", root=str(root))
        return []
    if not activated_names:
        return []
    wanted = set(activated_names)
    activated: list[str] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = _read_manifest(manifest_path)
        except Exception as exc:
            log.warning(
                "skill.manifest_invalid",
                path=str(manifest_path),
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        if manifest.get("name") not in wanted:
            continue
        try:
            if manifest.get("tools"):
                module = _import_tool_module(manifest_path.parent, manifest)
                register_fn = getattr(module, "register", None)
                if register_fn is None:
                    raise SkillManifestError(f"{manifest_path}: tool.py missing register() function")
                register_fn(registry)
            activated.append(str(manifest["name"]))
            log.info(
                "skill.activated",
                name=manifest["name"],
                version=manifest.get("version"),
                tool_count=len(manifest.get("tools") or []),
                doctrine_only=not manifest.get("tools"),
            )
        except Exception as exc:
            log.warning(
                "skill.activate_failed",
                path=str(manifest_path),
                error=f"{type(exc).__name__}: {exc}",
            )
    missing = wanted - set(activated)
    if missing:
        log.warning(
            "skill.activated_names_unresolved",
            missing=sorted(missing),
            note="recon activated these by name but no manifest matched — possible name typo or bundle removal between recon and execute",
        )
    return activated


def _import_tool_module(bundle_dir: Path, manifest: dict[str, Any]) -> Any:
    tool_file = bundle_dir / "tool.py"
    if not tool_file.exists():
        raise SkillManifestError(f"{bundle_dir}: tool.py not found")
    module_name = f"ludo_skill__{manifest['name']}"
    spec = importlib.util.spec_from_file_location(module_name, tool_file)
    if spec is None or spec.loader is None:
        raise SkillManifestError(f"{tool_file}: importlib spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
