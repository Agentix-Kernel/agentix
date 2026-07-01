"""Named checkpoints for operator-facing resume.

Checkpoint granularity is hybrid. Every turn writes the ``"latest"``
snapshot via ``session.save``. Named checkpoints land at phase
boundaries and are the ones operators reach for with
``omg resume --from <name>``.

The vocabulary lives as a frozen set below — migrations move through
five explicit phases.
"""

from __future__ import annotations

from typing import Literal

from agentix.core.session import Session, save
from agentix.storage import MinioStore, SqliteStore

CheckpointName = Literal[
    "scan_complete",
    "blueprint_generated",
    "extract_complete",
    "load_complete",
    "verify_complete",
]

ORDERED_CHECKPOINTS: tuple[CheckpointName, ...] = (
    "scan_complete",
    "blueprint_generated",
    "extract_complete",
    "load_complete",
    "verify_complete",
)


async def save_checkpoint(
    session: Session,
    name: CheckpointName,
    *,
    sqlite: SqliteStore,
    minio: MinioStore,
) -> str:
    """Save a named checkpoint. Delegates to ``session.save``.

    Returns the MinIO key for the written blob.
    """
    return await save(session, sqlite=sqlite, minio=minio, checkpoint=name)


async def load_checkpoint(
    customer_id: str,
    session_id: str,
    name: CheckpointName,
    *,
    minio: MinioStore,
) -> dict[str, object]:
    """Return the raw JSON snapshot for a named checkpoint."""
    key = MinioStore.key_checkpoint(customer_id, session_id, name)
    result = await minio.get_json(key)
    if not isinstance(result, dict):
        raise ValueError(f"checkpoint {key} is not a JSON object")
    return result
