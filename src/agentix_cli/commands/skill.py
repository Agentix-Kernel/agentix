"""skill subcommands — list, show, roots, add, new, edit, rm, run."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated

import typer

from agentix_cli._config import load_config
from agentix_cli._output import error, make_table, ok, print_kv, print_table, warn

app = typer.Typer(help="Manage skills across kernel / driver / agent / user layers.")

_SKILL_MD_SKELETON = """\
---
name: {name}
description: One-line description of what this skill does.
allowed-tools: []
---

# {name}

## Purpose

Describe the goal this skill helps the agent achieve.

## Procedure

1. Step one.
2. Step two.
3. Step three.

## Notes

Additional context, constraints, or examples.
"""

_MANIFEST_SKELETON = """\
{{
  "name": "{name}",
  "version": "0.1.0",
  "description": "One-line description.",
  "trigger": {{}}
}}
"""


# ── helpers ───────────────────────────────────────────────────────────────────


def _get_catalog(config_path: Path | None):  # type: ignore[return]
    cfg = load_config(config_path)
    if not cfg.skills_root:
        warn("skills_root not set in config. Add 'skills_root: ~/.agentix/skills' to your config.")
        return None
    if not cfg.skills_root.exists():
        warn(f"skills_root directory does not exist: {cfg.skills_root}")
        return None
    from agentix.skills.catalog import SkillCatalog

    return SkillCatalog(cfg.skills_root)


async def _sdk_skill_roots() -> list[dict] | None:
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            return [r.model_dump() for r in await c.list_skill_roots()]
    except Exception:
        return None


async def _sdk_list_skills() -> list[dict] | None:
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            return [s.model_dump() for s in await c.list_skills()]
    except Exception:
        return None


async def _sdk_get_skill(name: str) -> dict | None:
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            return (await c.get_skill(name)).model_dump()
    except Exception:
        return None


async def _sdk_reload() -> None:
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            await c.reload_skills()
    except Exception:
        pass


def _resolve_layer_path(layer: str, roots: list[dict]) -> Path | None:
    """Resolve a layer token to a filesystem path from the daemon's root list."""
    for r in roots:
        if r["layer"] == layer or r["path"].endswith(f"/{layer}"):
            return Path(r["path"])
    return None


_SKILL_NAME_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _read_skill_name(src: Path) -> str:
    """Read name from SKILL.md frontmatter; fall back to directory basename.

    Only accepts names matching [a-z0-9][a-z0-9_-]{0,63} to prevent path traversal.
    """
    skill_md = src / "SKILL.md"
    if skill_md.exists():
        try:
            import yaml  # type: ignore[import-untyped]

            text = skill_md.read_text()
            if text.startswith("---"):
                end = text.index("---", 3)
                fm = yaml.safe_load(text[3:end])
                if isinstance(fm, dict) and fm.get("name"):
                    candidate = str(fm["name"])
                    if _SKILL_NAME_RE.fullmatch(candidate):
                        return candidate
        except Exception:
            pass
    return src.name


def _safe_dest(target_root: Path, skill_name: str) -> Path:
    """Compute destination and abort if it escapes the target root."""
    if not _SKILL_NAME_RE.fullmatch(skill_name):
        error(f"Skill name {skill_name!r} is invalid. Use lowercase letters, digits, hyphens, underscores only.")
        raise typer.Exit(1)
    dest = (target_root / skill_name).resolve()
    if not dest.is_relative_to(target_root.resolve()):
        error(f"Skill name {skill_name!r} would escape the target root — aborting.")
        raise typer.Exit(1)
    return dest


def _open_editor(path: Path) -> None:
    import os
    import subprocess

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    subprocess.run([editor, str(path)], check=False)


# ── commands ──────────────────────────────────────────────────────────────────


@app.command("list")
def skill_list(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """List all skills from all registered layers (daemon-backed with local fallback)."""
    skills = asyncio.run(_sdk_list_skills())

    if skills is not None:
        bundles = [s for s in skills if not s.get("reference_only")]
        if not bundles:
            typer.echo("No skills found.")
            return
        t = make_table("Name", "Layer", "Description", "Tools")
        for s in sorted(bundles, key=lambda x: (x.get("layer", ""), x.get("name", ""))):
            has_tools = "[green]yes[/green]" if s.get("has_tools") else "no"
            t.add_row(s.get("name", ""), s.get("layer", ""), s.get("description", "")[:60], has_tools)
        print_table(t)
        typer.echo(f"\n{len(bundles)} skill(s) across {len({s.get('layer') for s in bundles})} layer(s)")
        return

    # Fallback: local catalog from config
    catalog = _get_catalog(config_path)
    if catalog is None:
        return
    bundles_local = [b for b in catalog.bundles() if not b.reference_only]
    if not bundles_local:
        typer.echo("No skills found in catalog.")
        return
    t = make_table("Name", "Has tools", "SKILL.md", "Directory")
    for b in sorted(bundles_local, key=lambda x: x.name):
        has_tools = "[green]yes[/green]" if b.has_tools else "no"
        has_md = "[green]yes[/green]" if b.skill_md_path else "no"
        t.add_row(b.name, has_tools, has_md, str(b.bundle_dir.name))
    print_table(t)
    typer.echo(f"\n{len(bundles_local)} skill(s) in {catalog.root}")


@app.command("show")
def skill_show(
    name: str = typer.Argument(..., help="Skill name"),
    body: bool = typer.Option(False, "--body", "-b", help="Print the full SKILL.md body"),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show details for a skill, optionally printing its SKILL.md body."""
    skill = asyncio.run(_sdk_get_skill(name))

    if skill is not None:
        print_kv(
            [
                ("Name", skill.get("name", "")),
                ("Description", skill.get("description") or "—"),
                ("Layer", skill.get("layer") or "—"),
                ("Root", skill.get("root") or "—"),
                ("SKILL.md", skill.get("skill_md_path") or "—"),
                ("Has tools", "yes" if skill.get("has_tools") else "no"),
                ("Allowed tools", ", ".join(skill.get("allowed_tools") or []) or "—"),
            ],
            title=f"Skill: {name}",
        )
        if body and skill.get("body"):
            typer.echo("\n" + skill["body"])
        return

    # Fallback: local catalog
    catalog = _get_catalog(config_path)
    if catalog is None:
        return
    match = next((b for b in catalog.bundles() if b.name == name), None)
    if match is None:
        error(f"skill {name!r} not found.")
        raise typer.Exit(1)
    print_kv(
        [
            ("Name", match.name),
            ("Description", match.description or "—"),
            ("Directory", str(match.bundle_dir)),
            ("SKILL.md", str(match.skill_md_path) if match.skill_md_path else "—"),
            ("Has tools", "yes" if match.has_tools else "no"),
            ("Allowed tools", ", ".join(match.allowed_tools) if match.allowed_tools else "—"),
        ],
        title=f"Skill: {name}",
    )
    if body and match.skill_md_path and match.skill_md_path.exists():
        typer.echo("\n" + match.skill_md_path.read_text())


@app.command("roots")
def skill_roots() -> None:
    """Show all registered skill roots with layer labels. Requires agentixd."""
    roots = asyncio.run(_sdk_skill_roots())
    if roots is None:
        error("agentixd not available — cannot list skill roots.")
        raise typer.Exit(1)
    if not roots:
        typer.echo("No skill roots registered.")
        return
    t = make_table("Layer", "Path", "Writable", "Exists")
    for r in roots:
        writable = "[green]yes[/green]" if r.get("writable") else "no"
        exists = "[green]yes[/green]" if r.get("exists") else "[red]no[/red]"
        t.add_row(r.get("layer", ""), r.get("path", ""), writable, exists)
    print_table(t)


@app.command("add")
def skill_add(
    src: Path = typer.Argument(..., help="Directory containing SKILL.md to install"),
    to: str = typer.Option("user", "--to", help="Target layer token (e.g. user, agent:ludo-user, driver:odoo-user)"),
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite if skill already exists")] = False,
) -> None:
    """Copy a skill bundle into a layer's .skills/ directory."""
    if not src.is_dir():
        error(f"{src} is not a directory.")
        raise typer.Exit(1)
    if not (src / "SKILL.md").exists():
        error(f"No SKILL.md found in {src}.")
        raise typer.Exit(1)

    roots = asyncio.run(_sdk_skill_roots())
    if roots is None:
        error("agentixd not available — cannot resolve skill roots.")
        raise typer.Exit(1)

    # Match the --to token against layer names or suffix
    target_root = _resolve_layer_path(to, roots)
    if target_root is None:
        available = ", ".join(r["layer"] for r in roots if r.get("writable"))
        error(f"Layer {to!r} not found. Writable layers: {available}")
        raise typer.Exit(1)

    if not roots[next(i for i, r in enumerate(roots) if r["path"] == str(target_root))].get("writable", False):
        error(f"Layer {to!r} is not writable (shipped skills are read-only). Use a -user layer.")
        raise typer.Exit(1)

    skill_name = _read_skill_name(src)
    dest = _safe_dest(target_root, skill_name)

    if dest.exists() and not force:
        error(f"Skill {skill_name!r} already exists at {dest}. Use --force to overwrite.")
        raise typer.Exit(1)

    target_root.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    ok(f"Skill {skill_name!r} installed to {dest}")
    asyncio.run(_sdk_reload())


@app.command("new")
def skill_new(
    name: str = typer.Argument(..., help="Skill name (kebab-case)"),
    to: str = typer.Option("user", "--to", help="Target layer token"),
) -> None:
    """Scaffold a new skill bundle and open it in $EDITOR."""
    roots = asyncio.run(_sdk_skill_roots())
    if roots is None:
        error("agentixd not available — cannot resolve skill roots.")
        raise typer.Exit(1)

    target_root = _resolve_layer_path(to, roots)
    if target_root is None:
        available = ", ".join(r["layer"] for r in roots if r.get("writable"))
        error(f"Layer {to!r} not found. Writable layers: {available}")
        raise typer.Exit(1)

    target_root.mkdir(parents=True, exist_ok=True)
    bundle_dir = _safe_dest(target_root, name)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    skill_md = bundle_dir / "SKILL.md"
    manifest = bundle_dir / "manifest.json"

    if not skill_md.exists():
        skill_md.write_text(_SKILL_MD_SKELETON.format(name=name))
    if not manifest.exists():
        manifest.write_text(_MANIFEST_SKELETON.format(name=name))

    ok(f"Skill skeleton created: {bundle_dir}")
    _open_editor(skill_md)
    asyncio.run(_sdk_reload())


@app.command("edit")
def skill_edit(
    name: str = typer.Argument(..., help="Skill name to edit"),
) -> None:
    """Open a skill's SKILL.md in $EDITOR."""
    skill = asyncio.run(_sdk_get_skill(name))
    if skill is None:
        error(f"agentixd not available or skill {name!r} not found.")
        raise typer.Exit(1)
    skill_md = skill.get("skill_md_path")
    if not skill_md or not Path(skill_md).exists():
        error(f"SKILL.md not found for {name!r}.")
        raise typer.Exit(1)
    _open_editor(Path(skill_md))
    asyncio.run(_sdk_reload())


@app.command("rm")
def skill_rm(
    name: str = typer.Argument(..., help="Skill name to remove"),
    from_: str = typer.Option("", "--from", help="Layer token (required if skill appears in multiple roots)"),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Remove a skill bundle from a writable (.skills/) layer."""
    skill = asyncio.run(_sdk_get_skill(name))
    if skill is None:
        error(f"agentixd not available or skill {name!r} not found.")
        raise typer.Exit(1)

    # Check the skill is in a writable root
    roots = asyncio.run(_sdk_skill_roots()) or []
    root_path = skill.get("root", "")
    root_info = next((r for r in roots if r["path"] == root_path), None)

    if root_info and not root_info.get("writable"):
        error(
            f"Skill {name!r} lives in a shipped (read-only) layer: {skill.get('layer')}. "
            "Edit the source repository to remove it."
        )
        raise typer.Exit(1)

    bundle_dir = Path(root_path) / name
    if not bundle_dir.is_dir():
        error(f"Bundle directory not found: {bundle_dir}")
        raise typer.Exit(1)

    if not yes:
        typer.confirm(f"Remove skill {name!r} from {bundle_dir}?", abort=True)

    shutil.rmtree(bundle_dir)
    ok(f"Skill {name!r} removed from {bundle_dir}")
    asyncio.run(_sdk_reload())


@app.command("run")
def skill_run(
    name: str = typer.Argument(..., help="Skill name to test"),
    message: str = typer.Option(..., "--message", "-m", help="Test message to send"),
) -> None:
    """Test-invoke a skill via an ephemeral agentixd session."""

    async def _run() -> None:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            session = await c.create_session(
                customer_id="skill-test",
                budget_usd=1.0,
                app_meta={"active_skills": [name]},
            )
            typer.echo(f"Session: {session.id}")
            turn = await c.run_turn(session.id, message=message)
            typer.echo(f"\n{turn.content or ''}")
            typer.echo(f"\n[tokens: in={turn.input_tokens} out={turn.output_tokens} cost=${turn.cost_usd:.4f}]")

    try:
        asyncio.run(_run())
    except Exception as exc:
        error(f"run failed: {exc}")
        raise typer.Exit(1) from None
