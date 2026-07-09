"""Speech driver family — STT wire types + protocol.

The proof that the driver abstraction isn't secretly chat-shaped:
bytes in, structured text out — a request that cannot be smuggled
through ``ChatRequest``. The concrete adapter is
``agentix.drivers.adapters.hf.HfSttDriver`` (HuggingFace Inference API,
``source="huggingface"``).

TTS / vision / timeseries families follow the same pattern when they
land (``docs/drivers.md`` DIRECTION).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agentix.drivers.base import Driver

__all__ = ["AudioSource", "SttDriver", "Transcript"]


@dataclass(frozen=True)
class AudioSource:
    """One piece of audio to transcribe. Raw bytes + their MIME type —
    the adapter streams them verbatim to the backend."""

    data: bytes
    mime_type: str = "audio/wav"
    #: Optional language hint (BCP-47 / ISO-639); backends that can't
    #: pin a language ignore it.
    language: str | None = None
    #: Per-call model override; the driver's default_model when None.
    model: str | None = None
    #: Adapter-specific passthrough (e.g. timestamps granularity).
    extra_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("AudioSource.data must be non-empty")


@dataclass(frozen=True)
class Transcript:
    """Canonical STT output — transcript text + the model that produced it."""

    text: str
    model: str
    language: str | None = None
    duration_seconds: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SttDriver(Driver, Protocol):
    """Protocol every STT adapter implements — the model-type stt verb."""

    async def transcribe(self, source: AudioSource) -> Transcript:
        """Transcribe one audio source to text."""
        ...
