"""HuggingFace Inference API adapters — the ``source="huggingface"`` family.

First member: :class:`HfSttDriver` (speech-to-text via hosted Whisper).
One POST per call: the raw audio bytes go up with their MIME type, the
transcript comes back as ``{"text": ...}``. No new dependency — httpx is
already in the kernel's dependency set.

Pricing is per-second of audio, not per-token — ``pricing_ref=None``:
the cost recorder does NOT record this driver's spend in v0.5; it emits
a ``driver.usage`` log line instead (``docs/budgets.md`` DIRECTION).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from agentix.drivers.base import (
    DriverDescriptor,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)
from agentix.drivers.limiter import driver_capacity
from agentix.drivers.session import current_session_id
from agentix.drivers.speech import AudioSource, Transcript

log = structlog.get_logger(__name__)

_DEFAULT_BASE_URL = "https://api-inference.huggingface.co"
_DEFAULT_MODEL = "openai/whisper-large-v3"
_DEFAULT_TIMEOUT_S = 120.0

__all__ = ["HfSttDriver"]


class HfSttDriver:
    """Speech-to-text via the HuggingFace Inference API.

    Auth: ``Authorization: Bearer <token>`` — explicit ``api_key`` or the
    ``HF_TOKEN`` env var. A missing key fails loud at construction (a
    misconfigured driver must not surface as a mid-run 401).

    ``transport`` is a test seam: inject ``httpx.MockTransport`` so the
    full error-mapping surface is testable without network.
    """

    name = "hf-stt"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        key = api_key or os.environ.get("HF_TOKEN")
        if not key:
            raise DriverInvalidRequest(
                "HfSttDriver: no HuggingFace token — set HF_TOKEN or pass api_key=",
                driver=self.name,
            )
        self.default_model = model
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_seconds,
            transport=transport,
        )
        log.info("hf_stt.driver_ready", base_url=self._base_url, default_model=model)

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(
            name=self.name,
            type="model",
            modality="stt",
            source="huggingface",
            default_model=self.default_model,
            pricing_ref=None,  # per-second pricing — not token-recordable (v0.5)
        )

    async def transcribe(self, source: AudioSource) -> Transcript:
        model = source.model or self.default_model
        async with driver_capacity():
            try:
                response = await self._client.post(
                    f"/models/{model}",
                    content=source.data,
                    headers={"Content-Type": source.mime_type},
                )
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                raise DriverUnavailable(f"HF inference unreachable: {exc}", driver=self.name) from exc
            except httpx.TimeoutException as exc:
                raise DriverUnavailable(f"HF inference timeout: {exc}", driver=self.name) from exc

        if response.status_code == 429:
            raise DriverRateLimited(_status_message(response), driver=self.name)
        if response.status_code == 503:
            # Cold model loading: HF returns 503 + {"estimated_time": s}.
            # Honest classification: the model is warming — retryable.
            raise DriverUnavailable(_status_message(response), driver=self.name)
        if response.status_code >= 500:
            raise DriverUnavailable(_status_message(response), driver=self.name)
        if response.status_code >= 400:
            raise DriverInvalidRequest(_status_message(response), driver=self.name)

        try:
            body = response.json()
        except ValueError as exc:
            raise DriverInvalidRequest(
                f"HF inference returned non-JSON body: {response.text[:200]}",
                driver=self.name,
            ) from exc
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise DriverInvalidRequest(
                f"HF inference response missing 'text': {response.text[:200]}",
                driver=self.name,
            )

        transcript = Transcript(
            text=text,
            model=model,
            language=source.language,
            raw=body if isinstance(body, dict) else {},
        )
        # v0.5: STT spend is not cost-recorded (per-second pricing has no
        # slot in the per-token table). The usage line keeps it visible.
        log.info(
            "driver.usage",
            type="model",
            modality="stt",
            driver=self.name,
            model=model,
            audio_bytes=len(source.data),
            session_id=current_session_id.get(),
        )
        return transcript

    async def aclose(self) -> None:
        await self._client.aclose()


def _status_message(response: httpx.Response) -> str:
    """Best-effort error string from an HF error response body."""
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    if isinstance(body, dict):
        err = body.get("error")
        eta = body.get("estimated_time")
        if err and eta is not None:
            return f"HTTP {response.status_code}: {err} (model loading, ~{eta}s)"
        if err:
            return f"HTTP {response.status_code}: {err}"
    return f"HTTP {response.status_code}: {response.text[:200]}"
