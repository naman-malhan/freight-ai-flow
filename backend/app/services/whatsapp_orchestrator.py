from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import DraftStatus, TripIntent
from app.schemas import (
    CancelDraftRequest,
    ConfirmDraftRequest,
    CreateTripDraftRequest,
    PatchTripDraftRequest,
    TripDraftResponse,
    TripIntentExtraction,
)
from app.services.llm_extractor import extract_trip_intent
from app.services.trip_draft_service import TripDraftService
from app.services.whatsapp_client import WhatsAppClient
from app.validators import next_missing_field

logger = logging.getLogger(__name__)


class WhatsAppOrchestrator:
    """WhatsApp inbound handler — same business rules as the n8n text workflow."""

    def __init__(self, db: AsyncSession, client: WhatsAppClient | None = None) -> None:
        self.db = db
        self.service = TripDraftService(db)
        self.client = client or WhatsAppClient()

    async def handle_webhook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = (payload.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        messages = value.get("messages") or []
        if not messages:
            return {"status": "ignored", "reason": "no_messages"}

        message = messages[0]
        sender = str(message.get("from") or "").lstrip("+")
        message_id = message.get("id") or ""
        message_type = message.get("type")

        if not sender or not message_id:
            return {"status": "ignored", "reason": "invalid_message"}

        try:
            if message_type == "interactive":
                reply_id = (
                    (message.get("interactive") or {}).get("button_reply") or {}
                ).get("id") or (
                    (message.get("interactive") or {}).get("list_reply") or {}
                ).get("id")
                return await self._handle_interactive(sender, message_id, reply_id)

            if message_type == "audio":
                media_id = (message.get("audio") or {}).get("id")
                text = await self.client.transcribe_audio(media_id) if media_id else None
                if not text:
                    await self.client.send_text(
                        sender,
                        "Voice note samajh nahi aaya. Please trip details type karke bhejein "
                        "(example: Kal HR55AB1234 Gurgaon se Jaipur, ABC party, freight 42000).",
                    )
                    return {"status": "audio_failed"}
                return await self._handle_text(sender, message_id, text)

            if message_type == "text":
                text = ((message.get("text") or {}).get("body") or "").strip()
                if not text:
                    await self.client.send_text(sender, "Khaali message mila. Trip details bhejein.")
                    return {"status": "empty_text"}
                return await self._handle_text(sender, message_id, text)

            await self.client.send_text(
                sender,
                "Abhi sirf text aur voice note support hai. Trip details type karke bhejein.",
            )
            return {"status": "unsupported_type", "type": message_type}
        except Exception:
            logger.exception("WhatsApp orchestrator failed for %s", message_id)
            try:
                await self.client.send_text(
                    sender,
                    "System error aaya. Thodi der baad dubara try karein.",
                )
            except Exception:
                logger.exception("Failed to send error reply")
            return {"status": "error"}

    async def _handle_interactive(
        self, sender: str, message_id: str, reply_id: str | None
    ) -> dict[str, Any]:
        reply = (reply_id or "").upper()
        draft = await self.service.get_latest_open_draft(sender)

        if reply == "CREATE":
            if not draft or draft.status != DraftStatus.READY_TO_CONFIRM:
                await self.client.send_text(
                    sender,
                    "Koi ready draft nahi mila. Pehle trip details bhejein.",
                )
                return {"status": "no_ready_draft"}
            trip = await self.service.confirm_draft(
                draft.id,
                ConfirmDraftRequest(sender_phone=sender, source_message_id=message_id),
            )
            await self.client.send_text(sender, trip.summary)
            return {"status": "created", "trip_id": trip.trip_id, "draft_id": draft.id}

        if reply == "CANCEL":
            if not draft:
                await self.client.send_text(sender, "Cancel karne ke liye koi open draft nahi hai.")
                return {"status": "no_open_draft"}
            await self.service.cancel_draft(
                draft.id,
                CancelDraftRequest(sender_phone=sender, source_message_id=message_id),
            )
            await self.client.send_text(sender, f"Draft #D-{draft.id} cancel ho gaya.")
            return {"status": "cancelled", "draft_id": draft.id}

        if reply == "EDIT":
            await self.client.send_text(
                sender,
                "Jo field galat hai uska sahi value bhejein, ya poora trip message dubara bhejein.",
            )
            return {"status": "edit_prompt"}

        await self.client.send_text(sender, "Samajh nahi aaya. CREATE / EDIT / CANCEL use karein.")
        return {"status": "unknown_button", "reply": reply}

    async def _handle_text(self, sender: str, message_id: str, text: str) -> dict[str, Any]:
        open_draft = await self.service.get_latest_open_draft(sender)

        if open_draft and open_draft.status == DraftStatus.MISSING_INFO:
            extraction = await extract_trip_intent(text, timezone=settings.app_timezone)
            looks_complete = (
                extraction.intent == TripIntent.CREATE_TRIP
                and len(extraction.missing_fields) <= 1
                and bool(extraction.fields.origin)
                and bool(extraction.fields.destination)
            )
            if not looks_complete:
                field = next_missing_field(open_draft.missing_fields or [])
                if field:
                    value = self._coerce_field_value(field, text, extraction)
                    try:
                        response = await self.service.patch_draft(
                            open_draft.id,
                            PatchTripDraftRequest(
                                sender_phone=sender,
                                source_message_id=message_id,
                                field_updates={field: value},
                                raw_text=text,
                            ),
                        )
                        await self._reply_for_draft(sender, response)
                        return {
                            "status": "patched",
                            "draft_id": response.draft_id,
                            "field": field,
                        }
                    except HTTPException as exc:
                        await self.client.send_text(sender, str(exc.detail))
                        return {"status": "patch_error", "detail": str(exc.detail)}

        return await self._create_from_text(sender, message_id, text)

    async def _create_from_text(
        self, sender: str, message_id: str, text: str
    ) -> dict[str, Any]:
        extraction = await extract_trip_intent(text, timezone=settings.app_timezone)
        if extraction.intent == TripIntent.UNKNOWN or extraction.clarification_needed:
            await self.client.send_text(
                sender,
                extraction.clarification_needed
                or "Trip creation intent clear nahi hai. Example: Kal Gurgaon se Jaipur, ABC party, freight 42000.",
            )
            return {"status": "clarification"}

        try:
            response = await self.service.create_or_update_draft(
                CreateTripDraftRequest(
                    sender_phone=sender,
                    source_message_id=message_id,
                    raw_text=text,
                    extraction=extraction,
                )
            )
        except HTTPException as exc:
            await self.client.send_text(sender, str(exc.detail))
            return {"status": "create_error", "detail": str(exc.detail)}

        await self._reply_for_draft(sender, response)
        return {"status": "drafted", "draft_id": response.draft_id, "draft_status": response.status.value}

    async def _reply_for_draft(self, sender: str, response: TripDraftResponse) -> None:
        try:
            if response.status == DraftStatus.MISSING_INFO and response.next_question:
                await self.client.send_text(sender, response.next_question)
                return
            if response.status == DraftStatus.READY_TO_CONFIRM and response.confirmation_summary:
                await self.client.send_confirmation_buttons(sender, response.confirmation_summary)
                return
            await self.client.send_text(
                sender,
                f"Draft #D-{response.draft_id} status: {response.status.value}",
            )
        except Exception:
            # Draft/trip work is already committed — do not fail the webhook on send errors
            # (common cause: expired Meta access token).
            logger.exception(
                "WhatsApp reply failed for draft_id=%s status=%s",
                response.draft_id,
                response.status.value,
            )

    @staticmethod
    def _coerce_field_value(
        field: str, text: str, extraction: TripIntentExtraction
    ) -> Any:
        fields = extraction.fields
        if field == "freight_amount":
            if fields.freight_amount is not None:
                return fields.freight_amount
            match = re.search(r"(\d[\d,\.]*)", text)
            if match:
                amount = float(match.group(1).replace(",", ""))
                if "hazaar" in text.lower() or "hazar" in text.lower():
                    amount *= 1000
                return amount
            return text.strip()
        if field == "pickup_date":
            return fields.pickup_date or fields.pickup_date_raw or text.strip()
        if field == "origin":
            return fields.origin or text.strip()
        if field == "destination":
            return fields.destination or text.strip()
        if field == "customer_name":
            return fields.customer_name or text.strip()
        if field == "vehicle_number":
            return fields.vehicle_number or text.strip()
        if field == "driver_name":
            return fields.driver_name or text.strip()
        if field == "pickup_window":
            return fields.pickup_window or text.strip()
        return text.strip()
