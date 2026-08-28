from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.whatsapp_orchestrator import WhatsAppOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/whatsapp", tags=["whatsapp"])


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> Response:
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload = await request.json()
    logger.info("WhatsApp webhook received keys=%s", list(payload.keys()))
    orchestrator = WhatsAppOrchestrator(db)
    result = await orchestrator.handle_webhook_payload(payload)
    return {"ok": True, **result}
