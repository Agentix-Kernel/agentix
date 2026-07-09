"""Local-filesystem file-store driver — the landed file transport.

Owns what used to be inlined in ``storage/memory.py``: path containment
(escape rejection with symlink following), thread-offloaded file I/O,
the ``fcntl.flock`` advisory lock under ``.locks/`` and the git HEAD
pin. ``MemoryStore`` composes page semantics on top; a NextCloud/WebDAV
adapter would replace exactly this module (WebDAV LOCK for ``lock()``,
``head_ref() -> None``).

Descriptor capabilities name what this backend can do that others may
not: ``git-pin`` and ``fcntl-lock``. Single-node only — multi-node
deployments need a DB advisory lock instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import structlog

from agentix.config import DriverSpec
from agentix.drivers.base import DriverDescriptor, DriverInvalidRequest

log = structlog.get_logger(__name__)

__all__ = ["LocalFileStoreDriver"]


class LocalFileStoreDriver:
    """File transport rooted at a local directory.

    Construction: convenience ``LocalFileStoreDriver(root)`` (how
    ``MemoryStore`` builds its default) or the seam contract
    ``LocalFileStoreDriver(spec=spec, api_key=None)`` — root from
    ``spec.base_url`` or ``spec.options["root"]``; no secret, ``api_key``
    accepted and ignored for contract uniformity.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        spec: DriverSpec | None = None,
        api_key: str | None = None,
        name: str = "local-fs",
    ) -> None:
        if root is None:
            if spec is None:
                raise DriverInvalidRequest("LocalFileStoreDriver needs a root or a DriverSpec", driver=name)
            root = spec.base_url or dict(spec.options).get("root", "")
            name = spec.name
        if not str(root):
            raise DriverInvalidRequest("LocalFileStoreDriver: empty root", driver=name)
        self.root = Path(root).resolve()
        self._name = name

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(
            name=self._name,
            type="storage",
            modality="file",
            source="local",
            capabilities=frozenset({"git-pin", "fcntl-lock"}),
            pricing_ref=None,
        )

    async def aclose(self) -> None:
        return None

    # ── path containment ────────────────────────────────────────────

    def resolve(self, relative: str | Path) -> Path:
        """Resolve a relative path under ``root``, rejecting escapes.

        Symlinks ARE followed (``.resolve()``), so an escape via a symlink
        pointing outside root is caught by the containment check. In-root
        symlinks that resolve elsewhere in the same root are allowed —
        operator-controlled territory, and the memory is git-tracked.
        """
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError(f"path {relative!r} escapes file-store root {self.root}")
        return candidate

    # ── verbs ───────────────────────────────────────────────────────

    async def read_text(self, relative: str) -> str:
        path = self.resolve(relative)
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def write_text(self, relative: str, text: str) -> None:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, text, encoding="utf-8")

    async def append_text(self, relative: str, text: str) -> None:
        path = self.resolve(relative)

        def _append() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(text)

        await asyncio.to_thread(_append)

    async def list_files(self, relative_dir: str, pattern: str = "*.md") -> list[str]:
        directory = self.resolve(relative_dir)

        def _scan() -> list[str]:
            if not directory.exists():
                return []
            return sorted(p.relative_to(self.root).as_posix() for p in directory.rglob(pattern) if p.is_file())

        return await asyncio.to_thread(_scan)

    async def exists(self, relative: str) -> bool:
        path = self.resolve(relative)
        return await asyncio.to_thread(path.exists)

    # ── locking ─────────────────────────────────────────────────────

    @asynccontextmanager
    async def _lock_cm(self, name: str, timeout_seconds: float) -> AsyncIterator[None]:
        import fcntl

        # Late import: MemoryLockTimeout lives with the store for handler
        # back-compat; storage.memory imports this adapter only lazily, so
        # there is no import cycle.
        from agentix.storage.memory import MemoryLockTimeout

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

    def lock(self, name: str, *, timeout_seconds: float = 10.0) -> AbstractAsyncContextManager[None]:
        """Non-blocking ``fcntl.flock`` on ``.locks/<name>.lock`` with
        exponential backoff; raises ``MemoryLockTimeout`` on expiry.
        Covers same-process (asyncio.gather) and cross-process contention.
        Single-node only."""
        return self._lock_cm(name, timeout_seconds)

    # ── version pin ─────────────────────────────────────────────────

    def head_ref(self) -> str | None:
        """Git HEAD sha of the root, or None (no repo / no git on $PATH) —
        callers treat None as "no pin, no drift check"."""
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
