from __future__ import annotations

import logging

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


async def transcribe_whatsapp_audio(
    *,
    content: bytes,
    mime_type: str,
    filename: str | None = None,
) -> str | None:
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY missing; cannot transcribe audio")
        return None
    if not content:
        return None

    suffix = mime_to_suffix(mime_type)
    name = filename or f"voice{suffix}"
    if not name.endswith(suffix):
        name = f"{name}{suffix}"

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
                files={"file": (name, content, mime_type or "audio/ogg")},
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
