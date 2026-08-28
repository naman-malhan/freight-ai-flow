from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import transcription


@pytest.mark.asyncio
async def test_transcribe_returns_none_without_api_key():
    with patch.object(transcription.settings, "groq_api_key", None):
        result = await transcription.transcribe_whatsapp_audio(
            content=b"fake-ogg",
            mime_type="audio/ogg",
        )
    assert result is None


@pytest.mark.asyncio
async def test_transcribe_success_calls_groq_multipart():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "text": "Kal HR55AB1234 Gurgaon se Jaipur freight 42000"
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch.object(transcription.settings, "groq_api_key", "gsk_test"),
        patch.object(transcription.settings, "groq_stt_model", "whisper-large-v3-turbo"),
        patch("app.services.transcription.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await transcription.transcribe_whatsapp_audio(
            content=b"ogg-bytes",
            mime_type="audio/ogg; codecs=opus",
        )

    assert result == "Kal HR55AB1234 Gurgaon se Jaipur freight 42000"
    kwargs = mock_client.post.await_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer gsk_test"
    assert kwargs["data"]["model"] == "whisper-large-v3-turbo"
    assert kwargs["data"]["language"] == "hi"
    assert "bilty" in kwargs["data"]["prompt"].lower() or "POD" in kwargs["data"]["prompt"]
    files = kwargs["files"]
    assert files["file"][0].endswith(".ogg")


@pytest.mark.asyncio
async def test_transcribe_http_error_returns_none():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(side_effect=Exception("groq down"))

    with (
        patch.object(transcription.settings, "groq_api_key", "gsk_test"),
        patch("app.services.transcription.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await transcription.transcribe_whatsapp_audio(
            content=b"ogg-bytes",
            mime_type="audio/ogg",
        )
    assert result is None


def test_mime_to_suffix():
    assert transcription.mime_to_suffix("audio/ogg; codecs=opus") == ".ogg"
    assert transcription.mime_to_suffix("audio/mpeg") == ".mp3"
    assert transcription.mime_to_suffix("audio/mp4") == ".m4a"
    assert transcription.mime_to_suffix("audio/wav") == ".wav"
