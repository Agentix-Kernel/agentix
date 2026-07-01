"""Kernel purity gate — ``src/agentix`` must carry no app-domain vocabulary in
its CODE surface (identifiers + string literals). Docstrings/comments may
reference the app to explain a seam (e.g. "the migration app's LoadToOdooError"),
so this checks the AST, not raw text.

If this fails, an Odoo/migration term leaked into kernel code — move it to the
app behind a seam. This is the machine definition of "Agentix is app-agnostic".
"""

from __future__ import annotations

import ast
from pathlib import Path

_KERNEL = Path(__file__).resolve().parents[2] / "src" / "agentix"

# High-confidence app-domain terms that must never appear as a kernel identifier
# or string literal. Deliberately excludes generic words ("migration" — DB schema
# migrations are generic; "rename" — generic) to avoid false positives.
_FORBIDDEN = (
    "odoo",
    "xmlid",
    "load_to_odoo",
    "extract_from_odoo",
    "update_rename_map",
    "verify_migration",
    "source_version",
    "target_version",
    "target_models",
    "bulk_pin",
    "rename_map",
    "customer_page",
)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """id()s of Constant nodes that are docstrings (module/class/func level)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _code_surface(source: str) -> list[str]:
    """Every identifier + non-docstring string literal in the file (lowercased)."""
    tree = ast.parse(source)
    doc_ids = _docstring_nodes(tree)
    surface: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            surface.append(node.id.lower())
        elif isinstance(node, ast.Attribute):
            surface.append(node.attr.lower())
        elif isinstance(node, ast.arg):
            surface.append(node.arg.lower())
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            surface.append(node.name.lower())
        elif isinstance(node, ast.keyword) and node.arg:
            surface.append(node.arg.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            surface.append(node.value.lower())
    return surface


def test_kernel_code_is_domain_neutral() -> None:
    leaks: dict[str, list[str]] = {}
    for path in sorted(_KERNEL.rglob("*.py")):
        surface = _code_surface(path.read_text(encoding="utf-8"))
        hits = sorted({term for term in _FORBIDDEN for tok in surface if term in tok})
        if hits:
            leaks[str(path.relative_to(_KERNEL.parent.parent))] = hits
    assert not leaks, (
        "App-domain vocabulary leaked into kernel CODE (not docstrings) — "
        "move it to the app behind a seam:\n"
        + "\n".join(f"  {f}: {terms}" for f, terms in leaks.items())
    )
