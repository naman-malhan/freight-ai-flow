from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import transcription


@pytest.mark.asyncio
async def test_transcribe_uses_local_primary_when_available():
    with (
        patch.object(transcription.settings, "faster_whisper_enabled", True),
        patch.object(
            transcription,
            "_transcribe_local",
            new=AsyncMock(
                return_value=("Kal HR55AB1234 Gurgaon se Jaipur freight 42000", None)
            ),
        ),
        patch.object(
            transcription,
            "_transcribe_groq",
            new=AsyncMock(return_value="should-not-be-used"),
        ) as groq_mock,
    ):
        result = await transcription.transcribe_whatsapp_audio(
            content=b"ogg-bytes",
            mime_type="audio/ogg",
        )

    assert result == "Kal HR55AB1234 Gurgaon se Jaipur freight 42000"
    groq_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcribe_falls_back_to_groq_when_local_fails():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"text": "Sonipat se Gujarat kiraya 50000"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch.object(transcription.settings, "faster_whisper_enabled", True),
        patch.object(
            transcription,
            "_transcribe_local",
            new=AsyncMock(return_value=(None, "local_transcription_failed")),
        ),
        patch.object(transcription.settings, "groq_api_key", "gsk_test"),
        patch.object(transcription.settings, "groq_stt_model", "whisper-large-v3-turbo"),
        patch("app.services.transcription.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await transcription.transcribe_whatsapp_audio(
            content=b"ogg-bytes",
            mime_type="audio/ogg; codecs=opus",
        )

    assert result == "Sonipat se Gujarat kiraya 50000"
    kwargs = mock_client.post.await_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer gsk_test"
    assert kwargs["data"]["model"] == "whisper-large-v3-turbo"
    assert kwargs["data"]["language"] == "hi"
    assert files_name_ends_with_ogg(kwargs["files"])


@pytest.mark.asyncio
async def test_transcribe_returns_none_when_local_and_groq_fail():
    with (
        patch.object(
            transcription,
            "_transcribe_local",
            new=AsyncMock(return_value=(None, "local_transcription_failed")),
        ),
        patch.object(transcription.settings, "groq_api_key", None),
    ):
        result = await transcription.transcribe_whatsapp_audio(
            content=b"fake-ogg",
            mime_type="audio/ogg",
        )
    assert result is None


@pytest.mark.asyncio
async def test_transcribe_groq_http_error_returns_none_after_local_fail():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(side_effect=Exception("groq down"))

    with (
        patch.object(
            transcription,
            "_transcribe_local",
            new=AsyncMock(return_value=(None, "local_transcription_failed")),
        ),
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


def files_name_ends_with_ogg(files: dict) -> bool:
    return files["file"][0].endswith(".ogg")
