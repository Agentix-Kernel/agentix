"""tool subcommands — list, show.

Tools are registered in-process. The CLI provides a static catalogue of the
kernel's built-in tools; app-registered tools are visible only when the CLI
runs inside the app's process (not typical for a standalone agentix install).
"""

from __future__ import annotations

import typer

from agentix_cli._output import error, make_table, print_kv, print_table

app = typer.Typer(help="List and inspect registered tools.")

# Kernel built-in tools (registered by register_kernel_tools in tools/builtin.py)
_BUILTIN_TOOLS: list[dict[str, str]] = [
    {"name": "read_file", "mutates": "no", "verifier": "—", "description": "Read a file from the allowed paths"},
    {"name": "glob", "mutates": "no", "verifier": "—", "description": "List files matching a glob pattern"},
    {"name": "grep", "mutates": "no", "verifier": "—", "description": "Search file contents for a pattern"},
    {"name": "fetch", "mutates": "no", "verifier": "—", "description": "Fetch a URL (allowed hosts only)"},
    {
        "name": "write_file",
        "mutates": "yes",
        "verifier": "read_file",
        "description": "Write content to a file (sandboxed)",
    },
    {"name": "apply_patch", "mutates": "yes", "verifier": "read_file", "description": "Apply a unified diff patch"},
    {"name": "run_command", "mutates": "yes", "verifier": "—", "description": "Run an allowed shell command"},
    {
        "name": "git_commit",
        "mutates": "yes",
        "verifier": "—",
        "description": "Commit staged changes (namespaced branch)",
    },
    {
        "name": "consult_skill",
        "mutates": "no",
        "verifier": "—",
        "description": "Read a skill SKILL.md body into context",
    },
]


@app.command("list")
def tool_list(
    show_all: bool = typer.Option(False, "--all", help="Include non-advertised tools"),
) -> None:
    """List kernel built-in tools. App-registered tools require running inside the app."""
    t = make_table("Name", "Mutates", "Verifier", "Description")
    for tool in _BUILTIN_TOOLS:
        mut = "[red]yes[/red]" if tool["mutates"] == "yes" else "[green]no[/green]"
        t.add_row(tool["name"], mut, tool["verifier"], tool["description"])
    print_table(t)
    typer.echo("\nApp-registered tools are only visible when running inside the app process.")


@app.command("show")
def tool_show(name: str = typer.Argument(..., help="Tool name")) -> None:
    """Show details for a built-in tool."""
    match = next((t for t in _BUILTIN_TOOLS if t["name"] == name), None)
    if match is None:
        error(f"built-in tool {name!r} not found. Run 'agentix tool list'.")
        raise typer.Exit(1)
    print_kv(
        [
            ("Name", match["name"]),
            ("Mutates target", match["mutates"]),
            ("Verifier", match["verifier"]),
            ("Description", match["description"]),
        ],
        title=f"Tool: {name}",
    )
