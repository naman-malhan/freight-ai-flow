from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.services.transcription import (
    mime_to_suffix,
    transcribe_whatsapp_audio_with_meta,
)
from app.services.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/stt", tags=["stt"])


class WhatsAppMediaSttRequest(BaseModel):
    media_id: str = Field(min_length=1)


class SttResponse(BaseModel):
    ok: bool
    text: str | None = None
    provider: str | None = None
    error: str | None = None


@router.post("/whatsapp-media", response_model=SttResponse)
async def transcribe_whatsapp_media(body: WhatsAppMediaSttRequest) -> SttResponse:
    """Download WhatsApp media by id and return transcript only (for n8n text flow)."""
    client = WhatsAppClient()
    if not client.configured:
        return SttResponse(ok=False, error="whatsapp_not_configured")
    try:
        result = await client.transcribe_audio_with_meta(body.media_id)
    except Exception:
        logger.exception("STT whatsapp-media failed media_id=%s", body.media_id)
        return SttResponse(ok=False, error="transcription_failed")
    if not result or not result.get("text"):
        return SttResponse(
            ok=False,
            text=None,
            provider=(result or {}).get("provider"),
            error="empty_transcript_or_media_download_failed",
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
        return SttResponse(ok=False, error="empty_transcript", provider=result.get("provider"))
    return SttResponse(ok=True, text=result["text"], provider=result.get("provider"))
