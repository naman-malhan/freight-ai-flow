# Groq Whisper Voice STT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OpenAI `whisper-1` STT on the FastAPI WhatsApp webhook with Groq `whisper-large-v3-turbo`, keeping OGG bytes unconverted and feeding transcripts into the existing trip-draft flow.

**Architecture:** New `transcription.py` service calls Groq’s OpenAI-compatible audio transcriptions API via `httpx` multipart. `WhatsAppClient.transcribe_audio` downloads WhatsApp media and delegates to that service. Orchestrator audio → text path stays unchanged so transcripts still land in `trip_drafts.raw_text`.

**Tech Stack:** FastAPI, httpx, Groq Audio Transcriptions API (`whisper-large-v3-turbo`), pytest, existing WhatsApp Cloud API media download.

**Spec:** `docs/superpowers/specs/2026-08-28-groq-whisper-voice-stt-design.md`

## Global Constraints

- STT provider for this change: Groq only (no OpenAI Whisper fallback)
- Model default: `whisper-large-v3-turbo`
- Language hint: `hi`
- No ffmpeg / no audio conversion
- No new Python package for Groq SDK — use existing `httpx`
- No DB migration
- No n8n workflow changes in this plan
- Do not commit secrets; only placeholders in `.env.example`
- This workspace may have no git repo — skip commit steps if `git rev-parse` fails
- Every task’s requirements implicitly include this section

## File structure

| File | Responsibility |
|------|----------------|
| `backend/app/services/transcription.py` | Groq STT only: bytes + mime → text \| None |
| `backend/app/config.py` | `GROQ_API_KEY`, `GROQ_STT_MODEL` settings |
| `backend/.env.example` / root `.env.example` | Document new env vars |
| `backend/app/services/whatsapp_client.py` | Download media; call transcription service |
| `backend/tests/test_transcription.py` | Unit tests for Groq STT helper |
| `backend/tests/test_whatsapp_webhook.py` | Audio webhook integration test |
| `README.md` | Mark voice STT path as Groq-based |

---

### Task 1: Config + Groq transcription service (TDD)

**Files:**
- Create: `backend/app/services/transcription.py`
- Create: `backend/tests/test_transcription.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `backend/.env.example` (create if missing; otherwise update)

**Interfaces:**
- Consumes: `settings.groq_api_key`, `settings.groq_stt_model`
- Produces:
  - `LOGISTICS_STT_PROMPT: str` (module constant)
  - `async def transcribe_whatsapp_audio(*, content: bytes, mime_type: str, filename: str | None = None) -> str | None`
  - `def mime_to_suffix(mime_type: str) -> str`

- [ ] **Step 1: Add failing unit tests**

Create `backend/tests/test_transcription.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow/backend"
pytest tests/test_transcription.py -v
```

Expected: FAIL with import/attribute errors (`transcription` module or `groq_api_key` missing).

- [ ] **Step 3: Add settings**

In `backend/app/config.py`, add after `openai_api_key` / `llm_model`:

```python
    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3-turbo"
```

Update `.env.example` (project root) to include:

```bash
GROQ_API_KEY=
GROQ_STT_MODEL=whisper-large-v3-turbo
```

If `backend/.env.example` exists, add the same two lines. Do **not** write a real key into `backend/.env` in this task (user adds later).

- [ ] **Step 4: Implement `transcription.py`**

Create `backend/app/services/transcription.py`:

```python
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

LOGISTICS_STT_PROMPT = (
    "Freight logistics Hindi/Hinglish voice note. "
    "Terms: bilty, LR, POD, party, gaadi, bhada, Manesar, Bhiwadi, "
    "Dharuhera, Mundra, ICD, 32-feet, 14 tyre, "
    "vehicle numbers like HR55AB1234, freight amounts in rupees."
)


def mime_to_suffix(mime_type: str) -> str:
    mt = (mime_type or "").lower()
    if "mpeg" in mt or "mp3" in mt:
        return ".mp3"
    if "mp4" in mt or "m4a" in mt:
        return ".m4a"
    if "wav" in mt:
        return ".wav"
    if "webm" in mt:
        return ".webm"
    if "flac" in mt:
        return ".flac"
    return ".ogg"


async def transcribe_whatsapp_audio(
    *,
    content: bytes,
    mime_type: str,
    filename: str | None = None,
) -> str | None:
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY missing; cannot transcribe audio")
        return None
    if not content:
        return None

    suffix = mime_to_suffix(mime_type)
    name = filename or f"voice{suffix}"
    if not name.endswith(suffix):
        name = f"{name}{suffix}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                GROQ_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                data={
                    "model": settings.groq_stt_model,
                    "language": "hi",
                    "prompt": LOGISTICS_STT_PROMPT,
                    "response_format": "json",
                },
                files={"file": (name, content, mime_type or "audio/ogg")},
            )
            response.raise_for_status()
            text = (response.json().get("text") or "").strip()
            logger.info(
                "Groq STT ok model=%s bytes=%s chars=%s",
                settings.groq_stt_model,
                len(content),
                len(text),
            )
            return text or None
    except Exception:
        logger.exception(
            "Groq transcription failed mime=%s bytes=%s",
            mime_type,
            len(content),
        )
        return None
```

- [ ] **Step 5: Run unit tests**

Run:

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow/backend"
pytest tests/test_transcription.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit (skip if no git repo)**

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow"
git rev-parse --is-inside-work-tree 2>/dev/null || echo "NO_GIT_SKIP"
# if git exists:
git add backend/app/config.py backend/app/services/transcription.py \
  backend/tests/test_transcription.py .env.example backend/.env.example
git commit -m "$(cat <<'EOF'
feat: add Groq Whisper transcription service

EOF
)"
```

---

### Task 2: Wire WhatsAppClient to Groq STT

**Files:**
- Modify: `backend/app/services/whatsapp_client.py`
- Test: covered by Task 3 webhook test; optional thin unit not required if Task 3 covers path

**Interfaces:**
- Consumes: `transcribe_whatsapp_audio(content=..., mime_type=...)`
- Produces: `WhatsAppClient.transcribe_audio(media_id: str) -> str | None` (same signature, Groq backend)

- [ ] **Step 1: Replace OpenAI STT in `transcribe_audio`**

In `backend/app/services/whatsapp_client.py`:

1. Remove unused `io` and `AsyncOpenAI` imports if nothing else needs them.
2. Replace `transcribe_audio` body with:

```python
    async def transcribe_audio(self, media_id: str) -> str | None:
        if not media_id:
            return None
        try:
            content, mime_type = await self.download_media(media_id)
            from app.services.transcription import mime_to_suffix, transcribe_whatsapp_audio

            suffix = mime_to_suffix(mime_type)
            return await transcribe_whatsapp_audio(
                content=content,
                mime_type=mime_type,
                filename=f"voice{suffix}",
            )
        except Exception:
            logger.exception("Audio transcription failed for media_id=%s", media_id)
            return None
```

Prefer a top-level import of `transcribe_whatsapp_audio` / `mime_to_suffix` instead of inline import if the file style uses top-level imports.

- [ ] **Step 2: Confirm OpenAI is no longer used for STT**

Run:

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow/backend"
rg -n "whisper-1|AsyncOpenAI|audio.transcriptions" app/services/whatsapp_client.py
```

Expected: no matches (or only comments if any). LLM extraction may still use OpenAI elsewhere — that is fine.

- [ ] **Step 3: Commit (skip if no git repo)**

```bash
git add backend/app/services/whatsapp_client.py
git commit -m "$(cat <<'EOF'
feat: route WhatsApp voice notes through Groq STT

EOF
)"
```

---

### Task 3: Audio webhook integration test + docs

**Files:**
- Modify: `backend/tests/test_whatsapp_webhook.py`
- Modify: `README.md` (voice checklist / config note)

**Interfaces:**
- Consumes: existing webhook + `WhatsAppClient.transcribe_audio` mock
- Produces: `test_webhook_audio_creates_ready_draft` proving audio → transcript → draft

- [ ] **Step 1: Write failing/new integration test**

Append to `backend/tests/test_whatsapp_webhook.py`:

```python
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
```

Ensure imports already include `AsyncMock`, `patch`, `settings`, `DraftStatus` (they do in the existing file).

- [ ] **Step 2: Run webhook + transcription tests**

Run:

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow/backend"
pytest tests/test_transcription.py tests/test_whatsapp_webhook.py -v
```

Expected: all PASS.

- [ ] **Step 3: Run full suite**

Run:

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow/backend"
pytest -v
```

Expected: all previously passing tests still PASS; new tests PASS.

- [ ] **Step 4: Update README**

In `README.md`:

1. Under Configuration, add: **Voice STT:** set `GROQ_API_KEY` (model default `whisper-large-v3-turbo`); WhatsApp OGG is sent directly (no conversion).
2. In Implementation Status, change voice line to checked for FastAPI path, e.g.  
   `- [x] Voice note path (Groq whisper-large-v3-turbo on FastAPI webhook)`  
   Keep n8n voice sub-workflow unchecked if still not done:
   `- [ ] n8n voice note sub-workflow (deferred)`

- [ ] **Step 5: Commit (skip if no git repo)**

```bash
git add backend/tests/test_whatsapp_webhook.py README.md
git commit -m "$(cat <<'EOF'
test: cover WhatsApp audio webhook via Groq transcript path

EOF
)"
```

---

### Task 4: Manual env checklist (no code)

**Files:** none (operator steps)

- [ ] **Step 1: Document for the user (in chat reply after implementation)**

Tell the user to:

1. Create free key at https://console.groq.com/keys
2. Add to `backend/.env`:

```bash
GROQ_API_KEY=gsk_...
GROQ_STT_MODEL=whisper-large-v3-turbo
```

3. Restart API (`docker compose up -d --build api` or uvicorn reload)
4. Send a WhatsApp voice note to the connected number
5. Confirm draft appears in DB / confirmation buttons reply

No automated test for live Groq in this plan.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Groq `whisper-large-v3-turbo` | Task 1 |
| OGG direct, no ffmpeg | Task 1–2 |
| Logistics prompt hint | Task 1 |
| `GROQ_API_KEY` / `GROQ_STT_MODEL` | Task 1 |
| Wire FastAPI WhatsApp client | Task 2 |
| Orchestrator unchanged; `raw_text` stores transcript | Task 2–3 (existing path) |
| Missing key / STT fail → Hindi reply | Task 3 |
| Unit + webhook tests | Task 1, 3 |
| README update | Task 3 |
| No n8n / no migration / no self-host | Global constraints |

## Self-review notes

- No TBD/placeholder steps
- Function names consistent: `transcribe_whatsapp_audio`, `mime_to_suffix`, `WhatsAppClient.transcribe_audio`
- Commit steps explicitly skippable when git is absent
