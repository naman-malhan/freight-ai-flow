from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.transcription import mime_to_suffix, transcribe_whatsapp_audio_with_meta

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Thin Graph API client for WhatsApp Cloud API send + media download."""

    def __init__(
        self,
        *,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self.access_token = access_token or settings.whatsapp_access_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.api_version = api_version or settings.whatsapp_api_version

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _messages_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.api_version}/"
            f"{self.phone_number_id}/messages"
        )

    async def send_text(self, to: str, body: str) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "text",
            "text": {"body": body, "preview_url": False},
        }
        return await self._post_message(payload)

    async def send_confirmation_buttons(self, to: str, body: str) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body[:1024]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "CREATE", "title": "CREATE"}},
                        {"type": "reply", "reply": {"id": "EDIT", "title": "EDIT"}},
                        {"type": "reply", "reply": {"id": "CANCEL", "title": "CANCEL"}},
                    ]
                },
            },
        }
        return await self._post_message(payload)

    async def _post_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            logger.warning("WhatsApp client not configured; skipping send")
            return {"skipped": True}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self._messages_url(),
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code >= 400:
                logger.error("WhatsApp send failed: %s %s", response.status_code, response.text)
                # Do not raise — callers (draft replies / STT failure notices) should not
                # abort the whole webhook when Meta token is expired.
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "body": response.text,
                }
            return response.json()

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Return (bytes, mime_type) for a WhatsApp media id."""
        meta_url = f"https://graph.facebook.com/{self.api_version}/{media_id}"
        async with httpx.AsyncClient(timeout=60) as client:
            meta = await client.get(meta_url, headers=self._headers())
            meta.raise_for_status()
            data = meta.json()
            media_url = data["url"]
            mime_type = data.get("mime_type", "audio/ogg")
            file_resp = await client.get(media_url, headers=self._headers())
            file_resp.raise_for_status()
            return file_resp.content, mime_type

    async def transcribe_audio(self, media_id: str) -> str | None:
        meta = await self.transcribe_audio_with_meta(media_id)
        return meta.get("text") if meta else None

    async def transcribe_audio_with_meta(self, media_id: str) -> dict[str, str | None]:
        if not media_id:
            return {"text": None, "provider": None}
        try:
            content, mime_type = await self.download_media(media_id)
            suffix = mime_to_suffix(mime_type)
            return await transcribe_whatsapp_audio_with_meta(
                content=content,
                mime_type=mime_type,
                filename=f"voice{suffix}",
            )
        except Exception:
            logger.exception("Audio transcription failed for media_id=%s", media_id)
            return {"text": None, "provider": None}
