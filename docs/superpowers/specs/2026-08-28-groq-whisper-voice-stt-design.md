# Design: Groq Whisper Voice STT for WhatsApp Trip Creation

**Date:** 2026-08-28  
**Status:** Approved for planning  
**Source:** ChatGPT share recommendation (Groq + Whisper Large V3 Turbo)  
**Scope surface:** FastAPI WhatsApp webhook path (n8n voice branch deferred)

## Problem

Drivers/dispatchers send Hindi/Hinglish WhatsApp voice notes with trip details. The system must turn audio into text before the existing LLM extractor and FastAPI draft flow can run.

ChatGPT’s ideal MVP recommendation:

- Dedicated Speech-to-Text first (not raw audio into a chat LLM)
- **Groq `whisper-large-v3-turbo`**
- WhatsApp OGG/Opus sent **directly** (no ffmpeg conversion initially)
- Transcript then goes to LLM + FastAPI validation
- Persist raw transcript for debugging
- Self-hosted faster-whisper deferred

## Current state

- FastAPI webhook already accepts `type=audio`, downloads media, and calls OpenAI `whisper-1`
- OpenAI billing/quota is empty → STT fails in practice
- Successful transcript already flows into `_handle_text` and is stored as `trip_drafts.raw_text`
- n8n workflow is text-path only; out of scope for this change

## Goals

1. Replace OpenAI Whisper STT with Groq `whisper-large-v3-turbo` on the FastAPI webhook path
2. Keep WhatsApp OGG bytes as-is (no conversion)
3. Keep the rest of trip creation unchanged (extract → draft → confirm)
4. Fail loudly to the user when STT is unavailable; never invent trip fields from silence
5. Make configuration explicit via `GROQ_API_KEY` / `GROQ_STT_MODEL`

## Non-goals

- n8n voice sub-workflow
- ffmpeg / audio conversion
- Self-hosted faster-whisper
- Second-pass / dual-provider STT
- New DB migration for transcript audit columns
- Changing LLM extraction model or draft state machine

## Architecture

```
WhatsApp Cloud API (audio message)
        │
        ▼
FastAPI /v1/whatsapp/webhook
        │
        ▼
WhatsAppClient.download_media(media_id)  →  (bytes, mime_type)  # usually audio/ogg
        │
        ▼
transcription.transcribe_whatsapp_audio(...)
        │  Groq Audio Transcriptions API
        │  model = whisper-large-v3-turbo
        │  language = hi
        │  prompt = logistics domain hint
        ▼
transcript text
        │
        ▼
WhatsAppOrchestrator._handle_text(...)   # existing path
        │
        ▼
extract_trip_intent → TripDraftService → PostgreSQL
```

OpenAI remains used only for optional LLM extraction (`OPENAI_API_KEY` / `LLM_MODEL`), not for STT.

## Components

### 1. `app/services/transcription.py` (new)

Single responsibility: turn WhatsApp audio bytes into text via Groq.

- Input: `content: bytes`, `mime_type: str`, optional filename suffix
- Output: `str | None`
- HTTP: Groq OpenAI-compatible transcriptions endpoint (`https://api.groq.com/openai/v1/audio/transcriptions`)
- Multipart file upload with correct filename extension (`.ogg`, `.mp3`, `.m4a`, `.wav`, …)
- Model from settings (`whisper-large-v3-turbo`)
- `language="hi"`
- Domain `prompt` hint for logistics vocabulary, for example:  
  `Freight logistics Hindi/Hinglish. Terms: bilty, LR, POD, party, gaadi, bhada, Manesar, Bhiwadi, Dharuhera, Mundra, ICD, vehicle numbers like HR55AB1234, freight amounts in rupees.`
- Return stripped text, or `None` on missing key / HTTP error / empty transcript
- Log provider + model + media size; do not log full audio bytes

### 2. `WhatsAppClient.transcribe_audio`

- Keep media download here
- Delegate transcription to `transcription.transcribe_whatsapp_audio`
- Remove OpenAI `whisper-1` STT call from this path

### 3. `WhatsAppOrchestrator` (minimal change)

- Audio branch stays the same:
  - success → `_handle_text(sender, message_id, transcript)`
  - failure → existing Hindi reply asking user to type details
- `trip_drafts.raw_text` continues to store the transcript (ChatGPT “raw transcript save” requirement without a migration)

### 4. Config / env

Add to `Settings` and `.env.example`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_API_KEY` | empty | Groq API key |
| `GROQ_STT_MODEL` | `whisper-large-v3-turbo` | STT model id |

User adds the real key locally later; code must work with key absent (returns `None`, user gets failure reply).

## Data flow details

1. Webhook receives Meta payload with `messages[0].type == "audio"` and `audio.id`
2. Download media with WhatsApp Graph API
3. Call Groq STT
4. If transcript empty/None → reply and stop (`status: audio_failed`)
5. Else treat transcript exactly like inbound text:
   - missing-info patch path, or
   - create/update draft path
6. Draft `raw_text` = transcript (or append on patch)

## Error handling

| Condition | Behavior |
|-----------|----------|
| `GROQ_API_KEY` missing | Log warning; return `None`; user reply: voice not understood |
| Groq 4xx/5xx / timeout | Log exception; return `None`; same user reply |
| Empty transcript | Treat as failure; same user reply |
| Downstream draft/LLM errors | Existing orchestrator error handling unchanged |

No silent trip creation from failed STT.

## Testing

1. **Unit:** `transcription.py` with mocked HTTP — success returns text; missing key returns `None`; HTTP error returns `None`
2. **Webhook integration:** audio payload with mocked `transcribe_audio` → draft created / confirmation path same as text tests
3. Manual later (user): set `GROQ_API_KEY`, send real WhatsApp voice note through webhook

## Success criteria

- With `GROQ_API_KEY` set, a WhatsApp voice note produces a transcript and enters the same draft/confirm flow as typed text
- Without key, user gets a clear Hindi failure message and no draft fields are invented
- No ffmpeg dependency added to Docker image
- Existing text-path tests still pass

## Implementation notes

- Use plain `httpx` multipart against Groq’s OpenAI-compatible transcriptions URL — no new `groq` SDK dependency
- Filename extension must match mime type so Groq accepts OGG
- Do not change n8n JSON in this slice
- Do not commit secrets; only placeholders in `.env.example`
