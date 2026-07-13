"""config subcommands — show, validate."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from agentix_cli._config import load_config
from agentix_cli._output import dry_run_header, error, make_table, ok, print_kv, print_table, warn

app = typer.Typer(help="Show and validate the Agentix configuration.")


@app.command("show")
def config_show(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show the resolved configuration (secrets redacted)."""
    cfg = load_config(config_path)

    print_kv(
        [
            ("Config file", str(cfg.config_path)),
            ("Exists", "yes" if cfg.config_path.exists() else "[red]no[/red]"),
            ("SQLite path", str(cfg.sqlite_path) if cfg.sqlite_path else "—"),
            ("Memory path", str(cfg.memory_path) if cfg.memory_path else "—"),
            ("Skills root", str(cfg.skills_root) if cfg.skills_root else "—"),
            ("Budget (€)", f"{cfg.budget_usd:.2f}"),
        ],
        title="Agentix Configuration",
    )

    if cfg.drivers:
        typer.echo("")
        t = make_table("Name", "Driver", "Type", "Modality", "Model", "Default", title="Declared Drivers")
        for d in cfg.drivers:
            t.add_row(d.name, d.driver, d.type, d.modality, d.model or "—", "[green]yes[/green]" if d.default else "no")
        print_table(t)
    else:
        warn("No drivers declared in config.")


@app.command("validate")
def config_validate(
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Report issues without making any changes")] = False,
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Validate the configuration and declared driver specs."""
    from agentix_cli.commands.driver import _DRIVER_META, _sdk_installed

    if dry_run:
        dry_run_header()

    cfg = load_config(config_path)
    issues: list[str] = []

    if not cfg.config_path.exists():
        issues.append(f"Config file not found: {cfg.config_path}")

    if cfg.sqlite_path and not cfg.sqlite_path.exists():
        warn(f"sqlite_path not found (will be created on first run): {cfg.sqlite_path}")

    if cfg.memory_path and not cfg.memory_path.exists():
        warn(f"memory_path not found (will be created on first run): {cfg.memory_path}")

    for d in cfg.drivers:
        if d.driver not in _DRIVER_META:
            issues.append(f"Driver {d.name!r}: unknown driver key {d.driver!r}")
            continue
        meta = _DRIVER_META[d.driver]
        sdk = meta["sdk"]
        if sdk and not _sdk_installed(sdk):
            issues.append(
                f"Driver {d.name!r} ({d.driver}): SDK {sdk!r} not installed — run 'agentix driver install {d.driver}'"
            )
        if d.api_key_env:
            import os

            if not os.environ.get(d.api_key_env):
                warn(f"Driver {d.name!r}: env var {d.api_key_env!r} is not set")

    if issues:
        for issue in issues:
            error(issue)
        if not dry_run:
            raise typer.Exit(1)
    else:
        ok("Configuration is valid.")
