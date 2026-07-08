"""Guard: no kernel module imports the legacy llm/embeddings surface.

The legacy shims (``agentix.llm.*``, ``agentix.embeddings``) exist only for
external consumers during the 0.4.x deprecation window. Kernel code must use
``agentix.drivers.*`` exclusively. Delete this guard at 0.5.0 final together
with the shims.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "agentix"

_LEGACY_PREFIX = "agentix.llm"
_LEGACY_MODULE = "agentix.embeddings"


def _is_legacy(module: str) -> bool:
    return module in (_LEGACY_MODULE, _LEGACY_PREFIX) or module.startswith(_LEGACY_PREFIX + ".")


def test_kernel_has_no_legacy_llm_or_embeddings_imports() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        # The shims themselves are allowed to reference the legacy names.
        if rel.parts[0] == "llm" or rel.parts[0] == "embeddings.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and _is_legacy(node.module):
                offenders.append(f"{rel}:{node.lineno} from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_legacy(alias.name):
                        offenders.append(f"{rel}:{node.lineno} import {alias.name}")
    assert not offenders, "legacy llm/embeddings imports in kernel:\n" + "\n".join(offenders)
