import pytest
from httpx import AsyncClient

from app.enums import DraftStatus, TripIntent
from app.schemas import ConfidenceScores, TripFields, TripIntentExtraction


HAPPY_PATH_TEXT = (
    "Kal HR55AB1234 Gurgaon se Jaipur, ABC party, freight 42000, driver Rakesh."
)


def _full_extraction() -> TripIntentExtraction:
    return TripIntentExtraction(
        intent=TripIntent.CREATE_TRIP,
        fields=TripFields(
            vehicle_number="HR55AB1234",
            origin="Gurgaon",
            destination="Jaipur",
            pickup_date_raw="kal",
            pickup_date="2026-08-29",
            customer_name="ABC",
            freight_amount=42000,
            driver_name="Rakesh",
        ),
        missing_fields=[],
        confidence=ConfidenceScores(intent=0.99, pickup_date=0.82, vehicle_number=0.98),
    )


@pytest.mark.asyncio
async def test_create_draft_happy_path(client: AsyncClient):
    payload = {
        "sender_phone": "919876543210",
        "source_message_id": "wamid.test001",
        "raw_text": HAPPY_PATH_TEXT,
        "extraction": _full_extraction().model_dump(),
    }
    response = await client.post("/v1/trip-drafts", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == DraftStatus.READY_TO_CONFIRM.value
    assert data["confirmation_summary"] is not None
    assert "Gurgaon" in data["confirmation_summary"]
    return data["draft_id"]


@pytest.mark.asyncio
async def test_idempotent_webhook(client: AsyncClient):
    payload = {
        "sender_phone": "919876543210",
        "source_message_id": "wamid.duplicate001",
        "raw_text": HAPPY_PATH_TEXT,
        "extraction": _full_extraction().model_dump(),
    }
    first = await client.post("/v1/trip-drafts", json=payload)
    second = await client.post("/v1/trip-drafts", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["draft_id"] == second.json()["draft_id"]
    assert second.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_confirm_is_idempotent(client: AsyncClient):
    create_payload = {
        "sender_phone": "919876543210",
        "source_message_id": "wamid.confirm001",
        "raw_text": HAPPY_PATH_TEXT,
        "extraction": _full_extraction().model_dump(),
    }
    created = await client.post("/v1/trip-drafts", json=create_payload)
    draft_id = created.json()["draft_id"]

    confirm_payload = {"sender_phone": "919876543210", "source_message_id": "wamid.confirm_btn001"}
    first = await client.post(f"/v1/trip-drafts/{draft_id}/confirm", json=confirm_payload)
    second = await client.post(f"/v1/trip-drafts/{draft_id}/confirm", json=confirm_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["trip_id"] == second.json()["trip_id"]


@pytest.mark.asyncio
async def test_missing_origin_asks_question(client: AsyncClient):
    payload = {
        "sender_phone": "919876543210",
        "source_message_id": "wamid.missing001",
        "raw_text": "Kal Jaipur load hai",
        "extraction": TripIntentExtraction(
            intent=TripIntent.CREATE_TRIP,
            fields=TripFields(destination="Jaipur", pickup_date_raw="kal", pickup_date="2026-08-29"),
            missing_fields=["origin", "customer_name", "freight_amount"],
            confidence=ConfidenceScores(intent=0.9),
        ).model_dump(),
    }
    response = await client.post("/v1/trip-drafts", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == DraftStatus.MISSING_INFO.value
    assert "origin" in data["missing_fields"]
    assert data["next_question"] is not None


@pytest.mark.asyncio
async def test_cancel_draft(client: AsyncClient):
    create_payload = {
        "sender_phone": "919876543210",
        "source_message_id": "wamid.cancel001",
        "raw_text": HAPPY_PATH_TEXT,
        "extraction": _full_extraction().model_dump(),
    }
    created = await client.post("/v1/trip-drafts", json=create_payload)
    draft_id = created.json()["draft_id"]

    cancel = await client.post(
        f"/v1/trip-drafts/{draft_id}/cancel",
        json={"sender_phone": "919876543210"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == DraftStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_patch_and_reconfirm(client: AsyncClient):
    create_payload = {
        "sender_phone": "919876543210",
        "source_message_id": "wamid.patch001",
        "raw_text": "Kal Gurgaon se Jaipur, ABC party, freight 42000",
        "extraction": TripIntentExtraction(
            intent=TripIntent.CREATE_TRIP,
            fields=TripFields(
                origin="Gurgaon",
                destination="Jaipur",
                pickup_date="2026-08-29",
                customer_name="ABC",
                freight_amount=42000,
            ),
            missing_fields=[],
            confidence=ConfidenceScores(intent=0.95),
        ).model_dump(),
    }
    created = await client.post("/v1/trip-drafts", json=create_payload)
    draft_id = created.json()["draft_id"]

    patched = await client.patch(
        f"/v1/trip-drafts/{draft_id}",
        json={
            "sender_phone": "919876543210",
            "field_updates": {"freight_amount": 45000},
        },
    )
    assert patched.status_code == 200
    assert patched.json()["fields"]["freight_amount"] == 45000
