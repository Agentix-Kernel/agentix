"""Markdown memory-store primitives — the memory layer.

Section-preserving writes over a directory of markdown files with YAML
frontmatter. Callers mutate **one H2 section at a time**; other sections
and the frontmatter are left byte-identical. ``append_to_log`` serialises
writes to ``log.md`` behind an asyncio lock so concurrent calls can't
corrupt the ordering.

The agent-facing ingest/query/lint workflow lives in
``MemoryMaintainMiddleware``; this module is the disk primitive the
sub-agent calls through a small tool.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
import structlog

log = structlog.get_logger(__name__)


class MemoryLockTimeout(TimeoutError):
    """Raised when ``MemoryStore.lock`` cannot acquire the advisory
    filesystem lock within the timeout window."""

    def __init__(self, name: str, timeout_seconds: float) -> None:
        super().__init__(f"timed out after {timeout_seconds:.1f}s waiting for memory lock on {name!r}")
        # Kept as ``customer_id`` for back-compat with MemoryMaintain's
        # exception handler; the value now holds the full lock name
        # (e.g. 'customer-acme' or 'reconcile-<hash>').
        self.customer_id = name
        self.name = name
        self.timeout_seconds = timeout_seconds


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_SECTION_SPLIT_RE = re.compile(r"(?=^##\s)", re.MULTILINE)


@dataclass
class MemoryPage:
    """Parsed representation of a markdown memory page.

    ``preamble`` is the content between frontmatter and the first H2
    heading; ``sections`` preserves insertion order and maps heading text
    to its body (everything until the next H2, exclusive).
    """

    frontmatter: dict[str, Any] = field(default_factory=dict)
    preamble: str = ""
    sections: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Reassemble the page to markdown source (round-trip stable)."""
        post = frontmatter.Post(self.preamble + _sections_to_markdown(self.sections), **self.frontmatter)
        dumped: str = frontmatter.dumps(post)
        return dumped + "\n"


class MemoryStore:
    """Async markdown memory store rooted at ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._log_lock = asyncio.Lock()

    # ───────────────────────────── path helpers ────────────────────────────

    def _resolve(self, relative: str | Path) -> Path:
        """Resolve a relative path under ``root``, rejecting escapes.

        Uses ``strict=False`` with ``.resolve()`` — symlinks ARE followed
        so an escape via symlink (symlink inside root pointing outside)
        is caught by the post-resolve containment check. In-root
        symlinks that resolve elsewhere in the same root are allowed;
        that's operator-controlled territory and the memory is git-tracked
        anyway.
        """
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError(f"path {relative!r} escapes memory root {self.root}")
        return candidate

    def path_log(self) -> Path:
        return self._resolve("log.md")

    def path_index(self) -> Path:
        return self._resolve("index.md")

    # ───────────────────────────── concurrency ────────────────────────────

    @asynccontextmanager
    async def lock(
        self,
        name: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> AsyncIterator[None]:
        """Advisory filesystem lock keyed by an arbitrary name.

        Used to serialise read-merge-write workflows that target the
        same memory resource from concurrent sessions. Callers pick a
        namespaced name to avoid collisions:

        * ``customer-<id>`` — customer page writes (MemoryMaintain).
        * ``reconcile-<key>`` — reconciled rule writes (the diagnosis
          reconciler — without this two concurrent sessions reconciling
          the same key would lose-update each other's ``applied_by``).

        Implementation: non-blocking ``fcntl.flock`` on
        ``.locks/<name>.lock`` under the memory root. Retries with
        exponential backoff up to ``timeout_seconds`` (default 10s).
        On acquisition failure, raises ``MemoryLockTimeout``. The lock
        protects both same-process (asyncio.gather) and cross-process
        (two ``omg`` runs on one node) contention.

        Single-node only. Multi-node deployments need a Postgres
        advisory lock instead; see arch.md §10.2.
        """
        import fcntl

        lock_dir = self.root / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{name}.lock"
        handle = lock_path.open("a+", encoding="utf-8")
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        delay = 0.01
        try:
            acquired = False
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if asyncio.get_event_loop().time() >= deadline:
                        break
                    await asyncio.sleep(min(delay, 0.2))
                    delay = min(delay * 2, 0.2)
            if not acquired:
                handle.close()
                raise MemoryLockTimeout(name, timeout_seconds)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            if not handle.closed:
                handle.close()

    @asynccontextmanager
    async def lock_for_customer(
        self,
        customer_id: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> AsyncIterator[None]:
        """Per-customer advisory lock — thin wrapper over ``lock``.

        Preserved as a named method so callers (MemoryMaintain) read
        clearly. New call sites should prefer the generic ``lock(name)``
        with an explicit namespace prefix.
        """
        async with self.lock(f"customer-{customer_id}", timeout_seconds=timeout_seconds):
            yield

    # ───────────────────────────── git pin ────────────────────────────────

    def head_sha(self) -> str | None:
        """Return the current HEAD commit sha of the memory repo, or None.

        The memory store is the source of truth (arch.md §7.5).
        When a session creates a blueprint we pin that blueprint to the
        commit the memory was at; a later ``make_plan`` run that sees a
        different HEAD knows someone edited the memory mid-session and can
        refuse to proceed without ``--force``.

        Returns ``None`` when the memory root is not inside a git repo (or
        ``git`` isn't on $PATH) — callers treat that as "no pin, no
        drift check", which is the right default for local scratch memories.
        """
        import subprocess

        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0:
            return None
        sha = proc.stdout.strip()
        return sha or None

    # ───────────────────────────── read / write ────────────────────────────

    async def read_page(self, relative: str | Path) -> MemoryPage:
        """Parse a markdown page into frontmatter + H2 sections."""
        path = self._resolve(relative)
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        post = frontmatter.loads(text)
        preamble, sections = _split_sections(post.content)
        return MemoryPage(frontmatter=dict(post.metadata), preamble=preamble, sections=sections)

    async def write_page(self, relative: str | Path, page: MemoryPage) -> None:
        """Persist a fully formed ``MemoryPage`` — full overwrite."""
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = page.render()
        await asyncio.to_thread(path.write_text, text, encoding="utf-8")
        log.debug("memory.write_page", path=str(path.relative_to(self.root)))

    async def write_section(
        self,
        relative: str | Path,
        section_name: str,
        body: str,
    ) -> None:
        """Surgically rewrite one H2 section, preserving every other section.

        If the section is not already present, it is appended in insertion
        order at the end of the page.
        """
        page = await self.read_page(relative)
        page.sections[section_name] = body.rstrip() + "\n"
        await self.write_page(relative, page)

    async def update_frontmatter(
        self,
        relative: str | Path,
        updates: dict[str, Any],
    ) -> None:
        """Merge ``updates`` into the page's YAML frontmatter."""
        page = await self.read_page(relative)
        page.frontmatter.update(updates)
        await self.write_page(relative, page)

    async def create_page(
        self,
        relative: str | Path,
        *,
        frontmatter_data: dict[str, Any],
        sections: dict[str, str],
        preamble: str = "",
    ) -> None:
        """Create a new page from scratch."""
        page = MemoryPage(frontmatter=dict(frontmatter_data), preamble=preamble, sections=dict(sections))
        await self.write_page(relative, page)

    async def list_pages(self, relative_dir: str | Path) -> list[Path]:
        """Return every ``.md`` file under ``relative_dir``, sorted."""
        directory = self._resolve(relative_dir)

        def _scan() -> list[Path]:
            if not directory.exists():
                return []
            return sorted(p for p in directory.rglob("*.md") if p.is_file())

        return await asyncio.to_thread(_scan)

    # ───────────────────────────── log append ──────────────────────────────

    async def append_to_log(
        self,
        *,
        kind: str,
        subject: str,
        body: str = "",
    ) -> None:
        """Append a grep-friendly entry to ``log.md``.

        Format per ``memory/AGENTS.md``:

            ## [YYYY-MM-DD] <kind> | <subject>
            <body>
        """
        date = datetime.now(tz=UTC).date().isoformat()
        heading = f"## [{date}] {kind} | {subject}\n"
        entry = heading + (body.rstrip() + "\n" if body else "") + "\n"
        path = self.path_log()
        async with self._log_lock:

            def _append() -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(entry)

            await asyncio.to_thread(_append)

    # ────────────────────────────── lint helpers ───────────────────────────

    async def find_orphan_pages(
        self,
        relative_dir: str | Path,
        *,
        index_path: str | Path = "index.md",
    ) -> list[Path]:
        """Return pages under ``relative_dir`` that ``index.md`` never links.

        Used by the lint step — a lightweight check; real deep lint lives
        in the MemoryMaintain sub-agent.
        """
        index_file = self._resolve(index_path)
        index_text = await asyncio.to_thread(index_file.read_text, encoding="utf-8")
        pages = await self.list_pages(relative_dir)
        dir_rel = self._resolve(relative_dir).relative_to(self.root)
        referenced: set[str] = set()
        for match in re.finditer(r"\(([^)]+\.md)\)", index_text):
            referenced.add(match.group(1))
        orphans: list[Path] = []
        for page in pages:
            rel = page.relative_to(self.root).as_posix()
            if rel in referenced:
                continue
            if rel == index_file.relative_to(self.root).as_posix():
                continue
            if rel == f"{dir_rel}/.gitkeep":
                continue
            orphans.append(page)
        return orphans

    # ─────────────────────────────── promotion ─────────────────────────────

    async def promote_evidence(
        self,
        *,
        target_relative: str | Path,
        customer_id: str,
        threshold: int = 3,
    ) -> bool:
        """Record a customer's confirmation on a target rename/gotcha page.

        The page's frontmatter is expected to carry ``evidence_count`` and
        ``confirmed_by`` (list). This helper only manages the bookkeeping;
        deciding *whether* to promote is the LLM agent's job. The return
        value is ``True`` iff the page has crossed ``threshold``.
        """
        page = await self.read_page(target_relative)
        confirmed_by = list(page.frontmatter.get("confirmed_by") or [])
        if customer_id not in confirmed_by:
            confirmed_by.append(customer_id)
        page.frontmatter["confirmed_by"] = confirmed_by
        page.frontmatter["evidence_count"] = len(confirmed_by)
        page.frontmatter["last_updated"] = datetime.now(tz=UTC).date().isoformat()
        await self.write_page(target_relative, page)
        return len(confirmed_by) >= threshold


# ──────────────────────────────────────────────────────────────────────────
# Section parsing — shared helpers
# ──────────────────────────────────────────────────────────────────────────


def _split_sections(content: str) -> tuple[str, dict[str, str]]:
    """Split ``content`` into (preamble, {heading: body}) on H2 boundaries."""
    if not _H2_RE.search(content):
        return content, {}
    parts = [p for p in _SECTION_SPLIT_RE.split(content) if p]
    preamble = ""
    sections: dict[str, str] = {}
    if parts and not parts[0].lstrip().startswith("## "):
        preamble = parts.pop(0)
    for raw in parts:
        m = _H2_RE.match(raw)
        if not m:
            # H2 at the very start; fall through to treat the whole chunk
            # as a section if possible.
            continue
        heading = m.group(1).strip()
        body = raw[m.end() :].lstrip("\n")
        sections[heading] = body
    return preamble, sections


def _sections_to_markdown(sections: dict[str, str] | Iterable[tuple[str, str]]) -> str:
    """Render a sections mapping back to markdown source."""
    items = sections.items() if isinstance(sections, dict) else sections
    chunks: list[str] = []
    for heading, body in items:
        body_text = body.rstrip()
        chunks.append(f"## {heading}\n{body_text}\n" if body_text else f"## {heading}\n")
    return "\n".join(chunks)
