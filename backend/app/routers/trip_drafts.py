from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import (
    CancelDraftRequest,
    ConfirmDraftRequest,
    CreateTripDraftRequest,
    ExtractTripIntentRequest,
    PatchTripDraftRequest,
    TripDraftResponse,
    TripResponse,
)
from app.services.llm_extractor import extract_trip_intent
from app.services.trip_draft_service import TripDraftService

router = APIRouter(prefix="/v1", tags=["trip-drafts"])


@router.post("/trip-drafts", response_model=TripDraftResponse)
async def create_trip_draft(
    request: CreateTripDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> TripDraftResponse:
    service = TripDraftService(db)
    return await service.create_or_update_draft(request)


@router.get("/trip-drafts/open", response_model=TripDraftResponse)
async def get_open_trip_draft(
    sender_phone: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> TripDraftResponse:
    """Latest open draft for a sender — used by n8n CREATE/CANCEL buttons."""
    service = TripDraftService(db)
    draft = await service.get_latest_open_draft(sender_phone)
    if not draft:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No open draft found")
    return await service.get_draft(draft.id, sender_phone)


@router.get("/trip-drafts/{draft_id}", response_model=TripDraftResponse)
async def get_trip_draft(
    draft_id: int,
    sender_phone: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> TripDraftResponse:
    service = TripDraftService(db)
    return await service.get_draft(draft_id, sender_phone)


@router.patch("/trip-drafts/{draft_id}", response_model=TripDraftResponse)
async def patch_trip_draft(
    draft_id: int,
    request: PatchTripDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> TripDraftResponse:
    service = TripDraftService(db)
    return await service.patch_draft(draft_id, request)


@router.post("/trip-drafts/{draft_id}/confirm", response_model=TripResponse)
async def confirm_trip_draft(
    draft_id: int,
    request: ConfirmDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> TripResponse:
    service = TripDraftService(db)
    return await service.confirm_draft(draft_id, request)


@router.post("/trip-drafts/{draft_id}/cancel", response_model=TripDraftResponse)
async def cancel_trip_draft(
    draft_id: int,
    request: CancelDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> TripDraftResponse:
    service = TripDraftService(db)
    return await service.cancel_draft(draft_id, request)


@router.post("/extract-trip-intent")
async def extract_intent(request: ExtractTripIntentRequest):
    """Helper endpoint for n8n — converts text to structured TripIntentExtraction."""
    extraction = await extract_trip_intent(
        request.text,
        reference_date=request.reference_date,
        timezone=request.timezone,
    )
    return extraction.model_dump()
