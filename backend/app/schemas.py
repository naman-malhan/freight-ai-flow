from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.enums import DraftStatus, TripIntent


class TripFields(BaseModel):
    vehicle_number: str | None = None
    origin: str | None = None
    destination: str | None = None
    pickup_date: str | None = None
    pickup_window: str | None = None
    customer_name: str | None = None
    freight_amount: float | None = None
    driver_name: str | None = None
    pickup_date_raw: str | None = None
    currency: str = "INR"


class ConfidenceScores(BaseModel):
    intent: float = 0.0
    vehicle_number: float | None = None
    pickup_date: float | None = None
    freight_amount: float | None = None
    origin: float | None = None
    destination: float | None = None
    customer_name: float | None = None
    driver_name: float | None = None


class TripIntentExtraction(BaseModel):
    intent: TripIntent
    fields: TripFields = Field(default_factory=TripFields)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: ConfidenceScores = Field(default_factory=ConfidenceScores)
    clarification_needed: str | None = None


class CreateTripDraftRequest(BaseModel):
    sender_phone: str
    source_message_id: str
    raw_text: str | None = None
    extraction: TripIntentExtraction


class PatchTripDraftRequest(BaseModel):
    sender_phone: str
    source_message_id: str | None = None
    field_updates: dict[str, Any] = Field(default_factory=dict)
    raw_text: str | None = None


class ConfirmDraftRequest(BaseModel):
    sender_phone: str
    source_message_id: str | None = None


class CancelDraftRequest(BaseModel):
    sender_phone: str
    source_message_id: str | None = None


class TripDraftResponse(BaseModel):
    draft_id: int
    status: DraftStatus
    fields: TripFields
    missing_fields: list[str]
    low_confidence_fields: list[str]
    confirmation_summary: str | None = None
    next_question: str | None = None
    trip_id: int | None = None
    duplicate: bool = False

    model_config = {"from_attributes": True}


class TripResponse(BaseModel):
    trip_id: int
    draft_id: int
    origin: str
    destination: str
    pickup_date: str
    pickup_window: str | None
    customer_name: str
    freight_amount: float
    currency: str
    vehicle_number: str | None
    driver_name: str | None
    summary: str

    model_config = {"from_attributes": True}


class ExtractTripIntentRequest(BaseModel):
    text: str
    reference_date: date | None = None
    timezone: str = "Asia/Kolkata"
