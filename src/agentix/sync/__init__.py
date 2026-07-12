"""``agentix.sync`` — the blocking facade over the async kernel (#70).

For integrators whose host runtime is synchronous (preforking WSGI servers,
OT toolchains, plain scripts): one dedicated background event-loop thread per
process (:class:`KernelLoop`) and blocking wrappers over the session/turn API
(:class:`SyncFacade`). There is no sync kernel variant — this module submits
to the one async kernel via ``asyncio.run_coroutine_threadsafe`` and blocks
on the future (``docs/sync.md`` §1/§4).

Why one dedicated loop thread (not per-call ``asyncio.run``): per-loop
limiter state and the attribution ``ContextVar`` binding (``docs/async.md``
§4) must stay consistent across calls — a fresh loop per call would reset
the capacity gate and every driver's per-loop semaphore each time.

Fork-awareness: preforking hosts must initialise lazily in the CHILD.
Threads do not survive ``fork()``; a loop started in the master is dead in
every worker. :class:`KernelLoop` records its pid at ``start()``, refuses
``submit()`` on a pid mismatch, and resets itself via ``os.register_at_fork``
so a forked child sees a cold, unstarted loop and the next ``start()`` in
the child spawns a fresh thread. Never start the loop at import time or in
a pre-fork master process.

Deadline semantics (pre-#71): a ``timeout_seconds`` on a blocking wrapper is
enforced host-side — ``future.result(timeout)`` then ``future.cancel()``,
which cancels the task on the loop abruptly (between awaits). Structurally
safe (checkpoint-first persistence), but the session row can be left
``running``; ``SyncFacade.start()`` therefore reaps expired-lease orphans
once. #71's ``deadline_seconds`` (clean abort → ``paused``) supersedes this
path when it lands.

Admission: the facade serves ``admission_limit`` concurrent runs (default 1 —
single-flight until #39 lands per-task store connections); excess callers
block up to ``admission_timeout_seconds`` then get :class:`SyncFacadeBusy`.
Fan-out is the async API's job, not this facade's.
"""

from __future__ import annotations

import asyncio
import os
import threading
import weakref
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

import structlog

from agentix.core.engine import Engine
from agentix.core.session import Session
from agentix.core.session import create_session as _create_session
from agentix.core.session import resume_or_create as _resume_or_create
from agentix.core.types import Message, Turn
from agentix.drivers.session import session_scope
from agentix.storage import MinioStore, SqliteStore

log = structlog.get_logger(__name__)

__all__ = ["KernelLoop", "SyncDeadlineExceeded", "SyncFacade", "SyncFacadeBusy"]

T = TypeVar("T")


class SyncFacadeBusy(RuntimeError):
    """No admission slot became free within ``admission_timeout_seconds``.

    Nothing was started — the caller decides host-side (retry, queue, tell
    the user the agent is busy)."""


class SyncDeadlineExceeded(TimeoutError):
    """The blocking call outlived its ``timeout_seconds``.

    The underlying task was cancelled on the loop (abrupt, pre-#71); the
    session's last throttled checkpoint is the resume point."""


# ── fork hook: one process-wide registration over all live loops ─────────
#
# ``os.register_at_fork`` callbacks cannot be unregistered, so registering
# per-instance would pin every KernelLoop ever constructed. One module-level
# hook over a WeakSet keeps test-created loops collectable.
_live_loops: weakref.WeakSet[KernelLoop] = weakref.WeakSet()
_fork_hook_lock = threading.Lock()
_fork_hook_installed = False


def _reset_live_loops_after_fork() -> None:
    for kernel_loop in list(_live_loops):
        kernel_loop._reset_after_fork()


def _install_fork_hook() -> None:
    global _fork_hook_installed
    with _fork_hook_lock:
        if not _fork_hook_installed:
            os.register_at_fork(after_in_child=_reset_live_loops_after_fork)
            _fork_hook_installed = True


class KernelLoop:
    """One dedicated background event-loop thread per process. Fork-aware.

    ``start()`` is idempotent within a process; after a ``fork()`` the child
    sees an unstarted loop and must ``start()`` again (lazily, on first use).
    ``submit()`` bridges a coroutine onto the loop and blocks for the result.
    """

    def __init__(self, *, thread_name: str = "agentix-sync-loop") -> None:
        self._thread_name = thread_name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pid: int | None = None
        self._state_lock = threading.Lock()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("KernelLoop is not started")
        return self._loop

    @property
    def running(self) -> bool:
        return self._loop is not None and self._pid == os.getpid()

    def start(self) -> None:
        """Spawn the loop thread (idempotent). Must run post-fork."""
        with self._state_lock:
            if self._loop is not None and self._pid == os.getpid():
                return
            if self._loop is not None:
                # Forked child that skipped the at-fork hook path (or a spoofed
                # pid in tests): the inherited loop object is unusable — drop it.
                self._drop_refs()
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()
                # run_forever returned: drain cancellations, close cleanly.
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

            thread = threading.Thread(target=_run, name=self._thread_name, daemon=True)
            thread.start()
            ready.wait()
            self._loop = loop
            self._thread = thread
            self._pid = os.getpid()
            _install_fork_hook()
            _live_loops.add(self)
            log.info("sync.loop_started", thread=self._thread_name, pid=self._pid)

    def stop(self, timeout_seconds: float = 30.0) -> None:
        """Stop the loop and join the thread. Safe to call twice."""
        with self._state_lock:
            loop, thread = self._loop, self._thread
            self._drop_refs()
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout_seconds)

    def submit(self, coro: Coroutine[Any, Any, T], *, timeout_seconds: float | None = None) -> T:
        """Run ``coro`` on the loop thread, blocking until it returns.

        Raises :class:`SyncDeadlineExceeded` on timeout (after cancelling the
        task on the loop) and ``RuntimeError`` when the loop is unstarted or
        belongs to a pre-fork parent process.
        """
        if self._loop is None or self._pid != os.getpid():
            coro.close()  # avoid the "coroutine was never awaited" warning
            raise RuntimeError(
                "KernelLoop is not started in this process "
                f"(loop pid={self._pid}, current pid={os.getpid()}) — "
                "call start() after fork, never in a pre-fork master"
            )
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout_seconds)
        except TimeoutError:
            future.cancel()
            raise SyncDeadlineExceeded(
                f"kernel call exceeded {timeout_seconds}s and was cancelled on the loop"
            ) from None

    # ── fork handling ────────────────────────────────────────────────

    def _drop_refs(self) -> None:
        self._loop = None
        self._thread = None
        self._pid = None

    def _reset_after_fork(self) -> None:
        # In the child the parent's thread does not exist and its loop object
        # is unusable state — drop references WITHOUT touching them so the
        # next start() builds cold. The parent process is unaffected.
        self._drop_refs()


class SyncFacade:
    """Blocking wrappers over the session/turn API, on a :class:`KernelLoop`.

    Construction wires the two kernel stores; ``start()`` boots the loop,
    initialises the stores, and reaps orphaned ``running`` sessions from a
    previous process life. All wrappers acquire the admission gate first.
    """

    def __init__(
        self,
        *,
        sqlite: SqliteStore,
        minio: MinioStore,
        loop: KernelLoop | None = None,
        admission_limit: int = 1,
        admission_timeout_seconds: float | None = None,
    ) -> None:
        if admission_limit < 1:
            raise ValueError("admission_limit must be >= 1")
        self._sqlite = sqlite
        self._minio = minio
        self._kernel_loop = loop if loop is not None else KernelLoop()
        self._owns_loop = loop is None
        self._admission = threading.BoundedSemaphore(admission_limit)
        self._admission_timeout = admission_timeout_seconds

    @property
    def kernel_loop(self) -> KernelLoop:
        return self._kernel_loop

    def start(self) -> None:
        """Boot the loop, initialise storage, reap orphans. Idempotent."""
        self._kernel_loop.start()
        self._kernel_loop.submit(self._startup())

    async def _startup(self) -> None:
        await self._sqlite.initialize()
        await self._minio.ensure_bucket()
        reaped = await self._sqlite.reap_expired_sessions()
        if reaped:
            log.warning("sync.reaped_orphan_sessions", count=len(reaped), session_ids=reaped)

    def close(self, timeout_seconds: float = 30.0) -> None:
        """Stop the loop if this facade owns it."""
        if self._owns_loop:
            self._kernel_loop.stop(timeout_seconds)

    @contextmanager
    def _admitted(self) -> Iterator[None]:
        if not self._admission.acquire(timeout=self._admission_timeout):
            raise SyncFacadeBusy(
                f"no admission slot within {self._admission_timeout}s — the facade is single-flight "
                "by default; fan-out belongs to the async API"
            )
        try:
            yield
        finally:
            self._admission.release()

    # ── blocking wrappers ────────────────────────────────────────────

    def create_session(
        self,
        *,
        customer_id: str,
        budget_usd: float = 200.0,
        app_meta: dict[str, Any] | None = None,
        control_plane_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Session:
        with self._admitted():
            return self._kernel_loop.submit(
                _create_session(
                    self._sqlite,
                    customer_id=customer_id,
                    budget_usd=budget_usd,
                    app_meta=app_meta,
                    control_plane_id=control_plane_id,
                ),
                timeout_seconds=timeout_seconds,
            )

    def resume_or_create(
        self,
        *,
        customer_id: str,
        control_plane_id: str,
        budget_usd: float = 200.0,
        app_meta: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[Session, bool]:
        with self._admitted():
            return self._kernel_loop.submit(
                _resume_or_create(
                    self._sqlite,
                    self._minio,
                    customer_id=customer_id,
                    control_plane_id=control_plane_id,
                    budget_usd=budget_usd,
                    app_meta=app_meta,
                ),
                timeout_seconds=timeout_seconds,
            )

    def run_turn(
        self,
        engine: Engine,
        session: Session,
        user_message: Message | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Turn:
        """Advance ``session`` by one turn, inside ``session_scope`` so every
        nested driver call attributes to it. The engine persists the
        ``latest`` checkpoint itself."""

        async def _run() -> Turn:
            async with session_scope(session.id):
                return await engine.run_turn(session, user_message)

        with self._admitted():
            return self._kernel_loop.submit(_run(), timeout_seconds=timeout_seconds)

    def run(self, coro: Coroutine[Any, Any, T], *, timeout_seconds: float | None = None) -> T:
        """Escape hatch: run an integrator-composed coroutine on the loop
        (admission-gated like every wrapper)."""
        try:
            with self._admitted():
                return self._kernel_loop.submit(coro, timeout_seconds=timeout_seconds)
        except SyncFacadeBusy:
            coro.close()  # never submitted — avoid the un-awaited warning
            raise
