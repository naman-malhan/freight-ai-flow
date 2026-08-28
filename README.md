# Freight AI — Flow #1: WhatsApp Trip Creation

AI-powered trip creation from Hindi/Hinglish WhatsApp messages with **human confirmation** before any trip is created.

## Architecture

```
WhatsApp → n8n (orchestration) → FastAPI (business logic) → PostgreSQL (source of truth)
                ↓
           LLM extraction (structured JSON only)
```

**Rule:** AI proposes → user confirms → deterministic code creates the trip.

## Quick Start

### 1. Start PostgreSQL + API

```bash
cp .env.example .env
docker compose up -d postgres
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Or run everything with Docker:

```bash
docker compose up --build
```

API docs: http://localhost:8000/docs

### 2. Demo user (seeded automatically)

| Field    | Value             |
| -------- | ----------------- |
| Phone    | `919876543210`    |
| Company  | Demo Transport Co |
| Vehicle  | HR55AB1234        |
| Driver   | Rakesh            |
| Customer | ABC               |

### 3. Test the happy path (Postman / curl)

**Extract intent** (rule-based without OpenAI key):

```bash
curl -X POST http://localhost:8000/v1/extract-trip-intent \
  -H "Content-Type: application/json" \
  -d '{"text": "Kal HR55AB1234 Gurgaon se Jaipur, ABC party, freight 42000, driver Rakesh."}'
```

**Create draft:**

```bash
curl -X POST http://localhost:8000/v1/trip-drafts \
  -H "Content-Type: application/json" \
  -d '{
    "sender_phone": "919876543210",
    "source_message_id": "wamid.demo001",
    "raw_text": "Kal HR55AB1234 Gurgaon se Jaipur, ABC party, freight 42000, driver Rakesh.",
    "extraction": {
      "intent": "create_trip",
      "fields": {
        "vehicle_number": "HR55AB1234",
        "origin": "Gurgaon",
        "destination": "Jaipur",
        "pickup_date": "2026-08-29",
        "customer_name": "ABC",
        "freight_amount": 42000,
        "driver_name": "Rakesh"
      },
      "missing_fields": [],
      "confidence": {"intent": 0.99, "pickup_date": 0.82}
    }
  }'
```

**Confirm trip** (replace `{draft_id}`):

```bash
curl -X POST http://localhost:8000/v1/trip-drafts/{draft_id}/confirm \
  -H "Content-Type: application/json" \
  -d '{"sender_phone": "919876543210"}'
```

### 4. Run tests

```bash
cd backend
pip install -r requirements.txt
pytest -v
```

## API Endpoints

| Method | Endpoint                       | Purpose                                  |
| ------ | ------------------------------ | ---------------------------------------- |
| POST   | `/v1/trip-drafts`              | Validate extraction, create/update draft |
| GET    | `/v1/trip-drafts/{id}`         | Read draft state                         |
| PATCH  | `/v1/trip-drafts/{id}`         | Apply correction / missing-field answer  |
| POST   | `/v1/trip-drafts/{id}/confirm` | Atomic draft → trip (idempotent)         |
| POST   | `/v1/trip-drafts/{id}/cancel`  | Cancel draft                             |
| POST   | `/v1/extract-trip-intent`      | LLM/rule-based extraction for n8n        |

## Draft State Machine

| State              | Meaning                                     |
| ------------------ | ------------------------------------------- |
| `NEW`              | Webhook received                            |
| `MISSING_INFO`     | Required fields missing — ask one at a time |
| `READY_TO_CONFIRM` | All fields valid — show CREATE/EDIT/CANCEL  |
| `CREATED`          | Trip confirmed                              |
| `CANCELLED`        | User cancelled                              |
| `EXPIRED`          | Draft past policy window                    |

## Run locally (ngrok — no Cloudflare)

```bash
# Terminal 1 — API + Postgres
cd "/Users/namanmalhan/Downloads/Freight AI flow"
docker compose up -d
curl http://localhost:8000/health   # OpenAPI: http://localhost:8000/docs

# Terminal 2 — public tunnel for n8n Cloud / Meta
ngrok http 8000
# Copy https://xxxx.ngrok-free.app into n8n HTTP nodes after every ngrok restart

# Or: ./scripts/start-tunnel.sh   (docker + ngrok together)
```

Stop:

```bash
pkill -f "ngrok http" || true
docker compose down
```

## n8n Setup (Step 4 in playbook)

1. Import `n8n/workflows/whatsapp-trip-creation.json` into n8n Cloud
2. Connect WhatsApp credentials (Trigger OAuth2 + Send API token)
3. Point all HTTP nodes at your **current ngrok** URL (n8n Cloud cannot use `localhost` / `host.docker.internal`)
4. Test text-only path before adding voice — see `N8N_ERROR_FIX.md`

## Configuration

- **Required fields** are per-company in `companies.required_fields_config` (vehicle/driver optional by default)
- **LLM:** Set `OPENAI_API_KEY` in `.env` for production extraction; falls back to rule-based parser without it
- **Voice STT (primary):** local open-source `faster-whisper` (`FASTER_WHISPER_MODEL=large-v3`, CPU `int8`). First run downloads the model (~3GB).
- **Voice STT (fallback):** set `GROQ_API_KEY` for cloud `whisper-large-v3-turbo` if local STT fails. WhatsApp OGG is used directly (no ffmpeg conversion step in app code; Docker image includes ffmpeg for decoding).
- **Timezone:** `Asia/Kolkata` for relative dates (`kal`, `aaj`)

## What You Need to Provide

1. **WhatsApp Business API** — Meta developer account + test phone number
2. **n8n instance** — cloud or self-hosted for webhook orchestration
3. **OpenAI API key** (recommended for messy Hindi/Hinglish; optional for demo)
4. **Pilot transporter config** — adjust `required_fields_config` to their workflow

## Implementation Status (Playbook Order)

- [x] PostgreSQL schema + migrations (Alembic)
- [x] FastAPI draft endpoints + validation
- [x] Idempotent confirm + webhook dedupe
- [x] Structured LLM extraction endpoint + rule-based fallback
- [x] Missing-field conversational flow
- [x] CREATE / EDIT(correct) / CANCEL
- [x] n8n workflow template (text path)
- [ ] WhatsApp Business connection (requires your Meta credentials)
- [x] Voice note path (local faster-whisper `large-v3` primary + Groq fallback)
- [ ] n8n voice note sub-workflow (deferred)

## Edge Cases Handled

- Missing origin — asks, does not invent
- Ambiguous freight (`"42"`) — clarification error
- Duplicate webhooks — `message_id` idempotency
- Double-tap CREATE — same trip ID returned
- Unknown sender phone — 403
- Wrong intent — 422 with helpful message
