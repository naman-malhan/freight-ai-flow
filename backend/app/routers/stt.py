from __future__ import annotations

import logging
import os

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.services.transcription import (
    mime_to_suffix,
    transcribe_whatsapp_audio_with_meta,
    whisper_model_cached,
)
from app.services.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/stt", tags=["stt"])


class WhatsAppMediaSttRequest(BaseModel):
    media_id: str = Field(min_length=1)
    # Optional override — useful when n8n has a fresh token but backend/.env is stale
    access_token: str | None = None


class SttResponse(BaseModel):
    ok: bool
    text: str | None = None
    provider: str | None = None
    error: str | None = None


class SttStatusResponse(BaseModel):
    faster_whisper_enabled: bool
    faster_whisper_model: str
    model_cached: bool
    hf_home: str
    whatsapp_token_configured: bool
    note: str


@router.get("/status", response_model=SttStatusResponse)
async def stt_status() -> SttStatusResponse:
    cached = whisper_model_cached()
    return SttStatusResponse(
        faster_whisper_enabled=settings.faster_whisper_enabled,
        faster_whisper_model=settings.faster_whisper_model,
        model_cached=cached,
        hf_home=os.environ.get("HF_HOME", "/models"),
        whatsapp_token_configured=bool(settings.whatsapp_access_token),
        note=(
            "Docker image does NOT include Whisper weights (~3GB). "
            "Weights download on first use into HF_HOME volume. "
            "Image size ~1.5GB is app + Python deps only."
            if not cached
            else "Whisper weights present in cache volume."
        ),
    )


@router.post("/whatsapp-media", response_model=SttResponse)
async def transcribe_whatsapp_media(body: WhatsAppMediaSttRequest) -> SttResponse:
    """Download WhatsApp media by id and return transcript only (for n8n text flow)."""
    client = WhatsAppClient(access_token=body.access_token or None)
    if not client.access_token or not client.phone_number_id:
        return SttResponse(ok=False, error="whatsapp_not_configured")
    result = await client.transcribe_audio_with_meta(body.media_id)
    if not result.get("text"):
        return SttResponse(
            ok=False,
            text=None,
            provider=result.get("provider"),
            error=result.get("error") or "empty_transcript_or_media_download_failed",
        )
    return SttResponse(ok=True, text=result["text"], provider=result.get("provider"))


@router.post("/transcribe", response_model=SttResponse)
async def transcribe_upload(
    file: UploadFile = File(...),
    mime_type: str | None = Form(default=None),
) -> SttResponse:
    """Transcribe raw audio bytes (n8n can download media with its own Meta token)."""
    content = await file.read()
    if not content:
        return SttResponse(ok=False, error="empty_file")
    mt = mime_type or file.content_type or "audio/ogg"
    name = file.filename or f"voice{mime_to_suffix(mt)}"
    result = await transcribe_whatsapp_audio_with_meta(
        content=content, mime_type=mt, filename=name
    )
    if not result.get("text"):
        return SttResponse(
            ok=False,
            error=result.get("error") or "empty_transcript",
            provider=result.get("provider"),
        )
    return SttResponse(ok=True, text=result["text"], provider=result.get("provider"))
