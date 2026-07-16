#!/usr/bin/env python3
"""check_doc_links.py — verify relative markdown links resolve (docs cleanup #133).

Scans every git-tracked ``*.md`` (excluding the agent memory stores, which are
data, not docs) for inline markdown links and checks that each relative target
exists on disk. External links (http/https/mailto), pure anchors (``#…``) and
workspace-relative links that escape the repo root (``../../agentix/…`` — sibling
repos absent in a solo checkout) are skipped.

Exit 0 = all links resolve; exit 1 = broken links listed on stderr.
Run from anywhere inside the repo; CI runs it as its own job.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Inline links only: [text](target). Reference-style links are rare here.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")
EXCLUDED_DIRS: tuple[str, ...] = ()  # no doc dirs are excluded in this repo


def tracked_markdown(repo_root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    return [repo_root / p for p in out if not p.startswith(EXCLUDED_DIRS)]


def main() -> int:
    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    broken: list[str] = []
    for md in tracked_markdown(repo_root):
        text = md.read_text(encoding="utf-8")
        # Blank out fenced blocks and inline code spans (format examples, not
        # links) — preserving offsets so reported line numbers stay true.
        for span_re in (re.compile(r"```.*?```", re.DOTALL), re.compile(r"`[^`\n]*`")):
            text = span_re.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if target.startswith(SKIP_PREFIXES):
                continue
            # Drop an in-file anchor suffix; decode the one escape docs use.
            path_part = target.split("#", 1)[0].replace("%20", " ")
            if not path_part:
                continue
            resolved = (md.parent / path_part).resolve()
            if not resolved.is_relative_to(repo_root):  # sibling-repo link — unverifiable here
                continue
            if not resolved.exists():
                line = text.count("\n", 0, match.start()) + 1
                broken.append(f"{md.relative_to(repo_root)}:{line}: {target}")
    if broken:
        print("[FAIL] broken relative doc links:", file=sys.stderr)
        print("\n".join(broken), file=sys.stderr)
        return 1
    print("[ok] all relative doc links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
