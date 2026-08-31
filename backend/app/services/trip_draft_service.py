from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.enums import DraftStatus, MessageDirection, TripIntent
from app.models import MessageEvent, Trip, TripDraft
from app.schemas import (
    CancelDraftRequest,
    ConfirmDraftRequest,
    CreateTripDraftRequest,
    PatchTripDraftRequest,
    TripDraftResponse,
    TripFields,
    TripResponse,
)
from app.services.master_data import get_company, get_user_by_phone, match_customer, match_driver, match_vehicle
from app.validators import (
    coerce_pickup_year,
    compute_missing_fields,
    draft_expires_at,
    format_confirmation_summary,
    format_display_date,
    hash_payload,
    is_valid_indian_vehicle,
    low_confidence_fields,
    next_missing_field,
    normalize_freight_amount,
    normalize_vehicle_number,
    question_for_field,
    resolve_relative_date,
)


class TripDraftService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _check_idempotency(self, message_id: str) -> TripDraft | None:
        result = await self.db.execute(
            select(MessageEvent).where(MessageEvent.message_id == message_id)
        )
        event = result.scalar_one_or_none()
        if not event or not event.draft_id:
            return None
        draft_result = await self.db.execute(select(TripDraft).where(TripDraft.id == event.draft_id))
        return draft_result.scalar_one_or_none()

    async def _record_message(
        self,
        *,
        message_id: str,
        company_id: int,
        draft_id: int | None,
        payload: str,
    ) -> None:
        existing = await self.db.execute(
            select(MessageEvent).where(MessageEvent.message_id == message_id)
        )
        if existing.scalar_one_or_none():
            return
        self.db.add(
            MessageEvent(
                company_id=company_id,
                message_id=message_id,
                direction=MessageDirection.INBOUND,
                payload_hash=hash_payload(payload),
                draft_id=draft_id,
            )
        )

    async def _normalize_fields(
        self,
        fields: TripFields,
        company_timezone: str,
        source_text: str | None = None,
    ) -> tuple[dict, str | None]:
        data = fields.model_dump()
        clarification = None

        if data.get("vehicle_number"):
            data["vehicle_number"] = normalize_vehicle_number(data["vehicle_number"])
            if data["vehicle_number"] and not is_valid_indian_vehicle(data["vehicle_number"]):
                clarification = (
                    f"Vehicle number '{data['vehicle_number']}' sahi lag raha hai? Confirm karein ya sahi number bhejein."
                )

        if data.get("freight_amount") is not None:
            normalized = normalize_freight_amount(data["freight_amount"])
            if normalized is None:
                clarification = clarification or "Freight amount clear nahi hai. Amount batayein."
            else:
                data["freight_amount"] = normalized

        year_context = " ".join(
            part for part in (data.get("pickup_date_raw"), source_text) if part
        )

        if not data.get("pickup_date") and data.get("pickup_date_raw"):
            resolved, date_clarification = resolve_relative_date(
                data["pickup_date_raw"], timezone=company_timezone
            )
            if resolved:
                data["pickup_date"] = resolved
            elif date_clarification:
                clarification = clarification or date_clarification

        # LLM often invents a stale year (e.g. 2023). Unless the user said a year, use current.
        if data.get("pickup_date"):
            data["pickup_date"] = coerce_pickup_year(
                data["pickup_date"],
                phrase=year_context or data.get("pickup_date_raw"),
                timezone=company_timezone,
            )

        return data, clarification

    async def _build_response(self, draft: TripDraft, *, duplicate: bool = False) -> TripDraftResponse:
        fields = TripFields.model_validate(draft.fields_json or {})
        company = await get_company(self.db, draft.company_id)
        required_config = (company.required_fields_config if company else {}) or {}
        confidence = draft.confidence_json or {}
        flagged = low_confidence_fields(confidence, draft.fields_json or {}, required_config)

        response = TripDraftResponse(
            draft_id=draft.id,
            status=draft.status,
            fields=fields,
            missing_fields=draft.missing_fields or [],
            low_confidence_fields=flagged,
            duplicate=duplicate,
        )

        if draft.status == DraftStatus.MISSING_INFO:
            next_field = next_missing_field(draft.missing_fields or [])
            response.next_question = question_for_field(next_field) if next_field else None
        elif draft.status == DraftStatus.READY_TO_CONFIRM:
            response.confirmation_summary = format_confirmation_summary(draft.id, draft.fields_json or {})
        elif draft.status == DraftStatus.CREATED:
            trip_result = await self.db.execute(select(Trip).where(Trip.draft_id == draft.id))
            trip = trip_result.scalar_one_or_none()
            response.trip_id = trip.id if trip else None
            response.confirmation_summary = format_confirmation_summary(draft.id, draft.fields_json or {})

        return response

    async def create_or_update_draft(self, request: CreateTripDraftRequest) -> TripDraftResponse:
        existing = await self._check_idempotency(request.source_message_id)
        if existing:
            return await self._build_response(existing, duplicate=True)

        user = await get_user_by_phone(self.db, request.sender_phone)
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown sender phone")

        company = await get_company(self.db, user.company_id)
        if not company:
            raise HTTPException(status.HTTP404_NOT_FOUND, detail="Company not found")

        extraction = request.extraction
        if extraction.intent == TripIntent.UNKNOWN:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=extraction.clarification_needed or "Trip creation intent not detected",
            )
        if extraction.clarification_needed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=extraction.clarification_needed)

        fields_dict, clarification = await self._normalize_fields(
            extraction.fields,
            company.timezone,
            source_text=request.raw_text,
        )
        if clarification:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=clarification)

        required_config = company.required_fields_config or {}
        missing = compute_missing_fields(fields_dict, required_config)
        if not missing and extraction.missing_fields:
            missing = [f for f in extraction.missing_fields if f in required_config and required_config.get(f)]

        status_value = DraftStatus.READY_TO_CONFIRM if not missing else DraftStatus.MISSING_INFO

        draft = TripDraft(
            company_id=company.id,
            user_id=user.id,
            fields_json=fields_dict,
            raw_text=request.raw_text,
            status=status_value,
            source_message_id=request.source_message_id,
            missing_fields=missing,
            confidence_json=extraction.confidence.model_dump(),
            expires_at=draft_expires_at(company.timezone),
        )
        self.db.add(draft)
        await self.db.flush()

        await self._record_message(
            message_id=request.source_message_id,
            company_id=company.id,
            draft_id=draft.id,
            payload=request.raw_text or extraction.model_dump_json(),
        )
        await self.db.commit()
        await self.db.refresh(draft)
        return await self._build_response(draft)

    async def get_draft(self, draft_id: int, sender_phone: str) -> TripDraftResponse:
        user = await get_user_by_phone(self.db, sender_phone)
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown sender phone")

        result = await self.db.execute(
            select(TripDraft).where(TripDraft.id == draft_id, TripDraft.company_id == user.company_id)
        )
        draft = result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Draft not found")
        return await self._build_response(draft)

    async def get_latest_open_draft(self, sender_phone: str) -> TripDraft | None:
        user = await get_user_by_phone(self.db, sender_phone)
        if not user:
            return None
        result = await self.db.execute(
            select(TripDraft)
            .where(
                TripDraft.user_id == user.id,
                TripDraft.status.in_(
                    [DraftStatus.MISSING_INFO, DraftStatus.READY_TO_CONFIRM, DraftStatus.NEW]
                ),
            )
            .order_by(TripDraft.updated_at.desc(), TripDraft.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def patch_draft(self, draft_id: int, request: PatchTripDraftRequest) -> TripDraftResponse:
        user = await get_user_by_phone(self.db, request.sender_phone)
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown sender phone")

        result = await self.db.execute(
            select(TripDraft).where(TripDraft.id == draft_id, TripDraft.company_id == user.company_id)
        )
        draft = result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Draft not found")
        if draft.status in {DraftStatus.CREATED, DraftStatus.CANCELLED, DraftStatus.EXPIRED}:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Draft is {draft.status.value}")

        company = await get_company(self.db, user.company_id)
        merged = dict(draft.fields_json or {})
        merged.update(request.field_updates)

        fields = TripFields.model_validate(merged)
        fields_dict, clarification = await self._normalize_fields(
            fields,
            company.timezone if company else "Asia/Kolkata",
            source_text=request.raw_text or draft.raw_text,
        )
        if clarification:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=clarification)

        required_config = (company.required_fields_config if company else {}) or {}
        missing = compute_missing_fields(fields_dict, required_config)
        draft.fields_json = fields_dict
        draft.missing_fields = missing
        draft.status = DraftStatus.READY_TO_CONFIRM if not missing else DraftStatus.MISSING_INFO
        if request.raw_text:
            draft.raw_text = (draft.raw_text or "") + "\n" + request.raw_text

        if request.source_message_id:
            await self._record_message(
                message_id=request.source_message_id,
                company_id=user.company_id,
                draft_id=draft.id,
                payload=request.model_dump_json(),
            )

        await self.db.commit()
        await self.db.refresh(draft)
        return await self._build_response(draft)

    async def confirm_draft(self, draft_id: int, request: ConfirmDraftRequest) -> TripResponse:
        user = await get_user_by_phone(self.db, request.sender_phone)
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown sender phone")

        result = await self.db.execute(
            select(TripDraft).where(TripDraft.id == draft_id, TripDraft.company_id == user.company_id)
        )
        draft = result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Draft not found")

        existing_trip = await self.db.execute(select(Trip).where(Trip.draft_id == draft.id))
        trip = existing_trip.scalar_one_or_none()
        if trip:
            return self._trip_response(trip, draft.id)

        if draft.status == DraftStatus.CANCELLED:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Draft was cancelled")
        if draft.status != DraftStatus.READY_TO_CONFIRM:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Draft not ready to confirm")

        if draft.expires_at:
            tz = ZoneInfo((await get_company(self.db, user.company_id)).timezone)
            if datetime.now(tz) > draft.expires_at.astimezone(tz):
                draft.status = DraftStatus.EXPIRED
                await self.db.commit()
                raise HTTPException(status.HTTP_410_GONE, detail="Draft expired")

        fields = draft.fields_json or {}
        vehicle = await match_vehicle(self.db, user.company_id, fields.get("vehicle_number"))
        driver = await match_driver(self.db, user.company_id, fields.get("driver_name"))
        customer = await match_customer(self.db, user.company_id, fields.get("customer_name"))

        trip = Trip(
            company_id=user.company_id,
            draft_id=draft.id,
            origin=fields["origin"],
            destination=fields["destination"],
            pickup_date=fields["pickup_date"],
            pickup_window=fields.get("pickup_window"),
            customer_name=customer.name if customer else fields["customer_name"],
            freight_amount=fields["freight_amount"],
            currency=fields.get("currency", "INR"),
            vehicle_id=vehicle.id if vehicle else None,
            driver_id=driver.id if driver else None,
            vehicle_number=fields.get("vehicle_number"),
            driver_name=fields.get("driver_name"),
        )
        draft.status = DraftStatus.CREATED
        self.db.add(trip)

        if request.source_message_id:
            await self._record_message(
                message_id=request.source_message_id,
                company_id=user.company_id,
                draft_id=draft.id,
                payload=request.model_dump_json(),
            )

        await self.db.commit()
        await self.db.refresh(trip)
        return self._trip_response(trip, draft.id)

    async def cancel_draft(self, draft_id: int, request: CancelDraftRequest) -> TripDraftResponse:
        user = await get_user_by_phone(self.db, request.sender_phone)
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown sender phone")

        result = await self.db.execute(
            select(TripDraft).where(TripDraft.id == draft_id, TripDraft.company_id == user.company_id)
        )
        draft = result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Draft not found")
        if draft.status == DraftStatus.CREATED:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Trip already created")

        draft.status = DraftStatus.CANCELLED
        if request.source_message_id:
            await self._record_message(
                message_id=request.source_message_id,
                company_id=user.company_id,
                draft_id=draft.id,
                payload=request.model_dump_json(),
            )
        await self.db.commit()
        await self.db.refresh(draft)
        return await self._build_response(draft)

    @staticmethod
    def _trip_response(trip: Trip, draft_id: int) -> TripResponse:
        pickup = format_display_date(trip.pickup_date) or trip.pickup_date
        summary = (
            f"Trip #{trip.id} created\n"
            f"Route: {trip.origin} -> {trip.destination}\n"
            f"Pickup: {pickup} {trip.pickup_window or ''}\n"
            f"Freight: Rs {int(trip.freight_amount):,}"
        )
        return TripResponse(
            trip_id=trip.id,
            draft_id=draft_id,
            origin=trip.origin,
            destination=trip.destination,
            pickup_date=trip.pickup_date,
            pickup_window=trip.pickup_window,
            customer_name=trip.customer_name,
            freight_amount=float(trip.freight_amount),
            currency=trip.currency,
            vehicle_number=trip.vehicle_number,
            driver_name=trip.driver_name,
            summary=summary,
        )
