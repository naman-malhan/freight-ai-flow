from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import settings
from app.enums import DraftStatus


@pytest.mark.asyncio
async def test_webhook_verify_ok(client: AsyncClient):
    response = await client.get(
        "/v1/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "freightai_webhook_verify_2026",
            "hub.challenge": "challenge-123",
        },
    )
    assert response.status_code == 200
    assert response.text == "challenge-123"


@pytest.mark.asyncio
async def test_webhook_verify_rejects_bad_token(client: AsyncClient):
    response = await client.get(
        "/v1/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "challenge-123",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webhook_text_creates_ready_draft(client: AsyncClient):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.wa-text-001",
                                    "type": "text",
                                    "text": {
                                        "body": (
                                            "Kal HR55AB1234 Gurgaon se Jaipur, "
                                            "ABC party, freight 42000, driver Rakesh."
                                        )
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.transcribe_audio = AsyncMock(return_value=None)
    mock_client.send_text = AsyncMock(return_value={})
    mock_client.send_confirmation_buttons = AsyncMock(return_value={})

    with (
        patch.object(settings, "openai_api_key", None),
        patch(
            "app.services.whatsapp_orchestrator.WhatsAppClient",
            return_value=mock_client,
        ),
    ):
        response = await client.post("/v1/whatsapp/webhook", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] == "drafted"
    assert data["draft_status"] == DraftStatus.READY_TO_CONFIRM.value
    mock_client.send_confirmation_buttons.assert_awaited()


@pytest.mark.asyncio
async def test_webhook_ignores_status_only(client: AsyncClient):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [{"id": "wamid.x", "status": "delivered"}]
                        }
                    }
                ]
            }
        ]
    }
    response = await client.post("/v1/whatsapp/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["reason"] == "no_messages"


@pytest.mark.asyncio
async def test_webhook_audio_creates_ready_draft(client: AsyncClient):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.wa-audio-001",
                                    "type": "audio",
                                    "audio": {"id": "media-audio-001", "mime_type": "audio/ogg"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.transcribe_audio = AsyncMock(
        return_value=(
            "Kal HR55AB1234 Gurgaon se Jaipur, "
            "ABC party, freight 42000, driver Rakesh."
        )
    )
    mock_client.send_text = AsyncMock(return_value={})
    mock_client.send_confirmation_buttons = AsyncMock(return_value={})

    with (
        patch.object(settings, "openai_api_key", None),
        patch(
            "app.services.whatsapp_orchestrator.WhatsAppClient",
            return_value=mock_client,
        ),
    ):
        response = await client.post("/v1/whatsapp/webhook", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] == "drafted"
    assert data["draft_status"] == DraftStatus.READY_TO_CONFIRM.value
    mock_client.transcribe_audio.assert_awaited_once_with("media-audio-001")
    mock_client.send_confirmation_buttons.assert_awaited()


@pytest.mark.asyncio
async def test_webhook_audio_failed_replies(client: AsyncClient):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.wa-audio-fail-001",
                                    "type": "audio",
                                    "audio": {"id": "media-audio-fail", "mime_type": "audio/ogg"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.transcribe_audio = AsyncMock(return_value=None)
    mock_client.send_text = AsyncMock(return_value={})
    mock_client.send_confirmation_buttons = AsyncMock(return_value={})

    with patch(
        "app.services.whatsapp_orchestrator.WhatsAppClient",
        return_value=mock_client,
    ):
        response = await client.post("/v1/whatsapp/webhook", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "audio_failed"
    mock_client.send_text.assert_awaited()
    body = mock_client.send_text.await_args.args[1]
    assert "Voice note" in body or "voice" in body.lower()
    assert "samajh nahi aaya" in body.lower()
