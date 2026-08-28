from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

LOGISTICS_STT_PROMPT = (
    "Freight logistics Hindi/Hinglish voice note. "
    "Terms: bilty, LR, POD, party, gaadi, bhada, Manesar, Bhiwadi, "
    "Dharuhera, Mundra, ICD, 32-feet, 14 tyre, "
    "vehicle numbers like HR55AB1234, freight amounts in rupees."
)

_model_lock = threading.Lock()
_whisper_model: Any | None = None


def mime_to_suffix(mime_type: str) -> str:
    mt = (mime_type or "").lower()
    if "mpeg" in mt or "mp3" in mt:
        return ".mp3"
    if "mp4" in mt or "m4a" in mt:
        return ".m4a"
    if "wav" in mt:
        return ".wav"
    if "webm" in mt:
        return ".webm"
    if "flac" in mt:
        return ".flac"
    return ".ogg"


def _get_whisper_model() -> Any:
    """Lazy-load faster-whisper model (heavy; once per process)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _model_lock:
        if _whisper_model is not None:
            return _whisper_model
        from faster_whisper import WhisperModel

        device = settings.faster_whisper_device
        compute_type = settings.faster_whisper_compute_type
        model_size = settings.faster_whisper_model
        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s",
            model_size,
            device,
            compute_type,
        )
        _whisper_model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        return _whisper_model


def _transcribe_local_sync(path: str) -> str | None:
    model = _get_whisper_model()
    segments, _info = model.transcribe(
        path,
        language="hi",
        initial_prompt=LOGISTICS_STT_PROMPT,
        vad_filter=True,
    )
    text = "".join(segment.text for segment in segments).strip()
    return text or None


async def _transcribe_local(*, content: bytes, suffix: str) -> str | None:
    if not settings.faster_whisper_enabled:
        logger.info("Local faster-whisper disabled via FASTER_WHISPER_ENABLED")
        return None
    if not content:
        return None

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        text = await asyncio.to_thread(_transcribe_local_sync, tmp_path)
        logger.info(
            "Local STT ok model=%s bytes=%s chars=%s",
            settings.faster_whisper_model,
            len(content),
            len(text or ""),
        )
        return text
    except Exception:
        logger.exception(
            "Local faster-whisper transcription failed bytes=%s",
            len(content),
        )
        return None
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


async def _transcribe_groq(
    *,
    content: bytes,
    mime_type: str,
    filename: str,
) -> str | None:
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY missing; cloud fallback unavailable")
        return None
    if not content:
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                GROQ_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                data={
                    "model": settings.groq_stt_model,
                    "language": "hi",
                    "prompt": LOGISTICS_STT_PROMPT,
                    "response_format": "json",
                },
                files={"file": (filename, content, mime_type or "audio/ogg")},
            )
            response.raise_for_status()
            text = (response.json().get("text") or "").strip()
            logger.info(
                "Groq STT ok model=%s bytes=%s chars=%s",
                settings.groq_stt_model,
                len(content),
                len(text),
            )
            return text or None
    except Exception:
        logger.exception(
            "Groq transcription failed mime=%s bytes=%s",
            mime_type,
            len(content),
        )
        return None


async def transcribe_whatsapp_audio(
    *,
    content: bytes,
    mime_type: str,
    filename: str | None = None,
) -> str | None:
    """Primary: local faster-whisper. Fallback: Groq cloud STT. Returns text only."""
    meta = await transcribe_whatsapp_audio_with_meta(
        content=content, mime_type=mime_type, filename=filename
    )
    return meta.get("text") if meta else None


async def transcribe_whatsapp_audio_with_meta(
    *,
    content: bytes,
    mime_type: str,
    filename: str | None = None,
) -> dict[str, str | None]:
    """Same as transcribe_whatsapp_audio but includes provider metadata."""
    if not content:
        return {"text": None, "provider": None}

    suffix = mime_to_suffix(mime_type)
    name = filename or f"voice{suffix}"
    if not name.endswith(suffix):
        name = f"{name}{suffix}"

    local_text = await _transcribe_local(content=content, suffix=suffix)
    if local_text:
        return {"text": local_text, "provider": "faster-whisper"}

    logger.info("Local STT empty/failed; attempting Groq fallback")
    groq_text = await _transcribe_groq(content=content, mime_type=mime_type, filename=name)
    if groq_text:
        return {"text": groq_text, "provider": "groq"}
    return {"text": None, "provider": None}
