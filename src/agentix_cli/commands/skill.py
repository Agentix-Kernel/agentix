"""skill subcommands — list, show."""

from __future__ import annotations

from pathlib import Path

import typer

from agentix_cli._config import load_config
from agentix_cli._output import error, make_table, print_kv, print_table, warn

app = typer.Typer(help="List and inspect skills from the skills catalog.")


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


@app.command("list")
def skill_list(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """List all skills from the catalog (skills_root in config)."""
    catalog = _get_catalog(config_path)
    if catalog is None:
        return

    bundles = [b for b in catalog.bundles() if not b.reference_only]
    if not bundles:
        typer.echo("No skills found in catalog.")
        return

    t = make_table("Name", "Has tools", "SKILL.md", "Directory")
    for b in sorted(bundles, key=lambda x: x.name):
        has_tools = "[green]yes[/green]" if b.has_tools else "no"
        has_md = "[green]yes[/green]" if b.skill_md_path else "no"
        t.add_row(b.name, has_tools, has_md, str(b.bundle_dir.name))
    print_table(t)
    typer.echo(f"\n{len(bundles)} skill(s) in {catalog.root}")


@app.command("show")
def skill_show(
    name: str = typer.Argument(..., help="Skill name"),
    body: bool = typer.Option(False, "--body", "-b", help="Print the full SKILL.md body"),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show details for a skill, optionally printing its SKILL.md body."""
    catalog = _get_catalog(config_path)
    if catalog is None:
        return

    match = next((b for b in catalog.bundles() if b.name == name), None)
    if match is None:
        error(f"skill {name!r} not found in catalog.")
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
