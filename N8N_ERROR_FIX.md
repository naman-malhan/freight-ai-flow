# n8n WhatsApp Errors — Fix Guide

## Current public API base (ngrok)

```
https://49b2-103-248-87-67.ngrok-free.app
```

**Important:** Free ngrok URL changes every time you restart ngrok. After each restart, update all n8n HTTP node base URLs (or re-import `n8n/workflows/whatsapp-trip-creation.json` after updating the file).

We use **ngrok only** (not Cloudflare).

---

## Screenshots Se Root Cause (fixed in repo)

| Symptom                          | Root cause                                                                 |
| -------------------------------- | -------------------------------------------------------------------------- |
| `ENOTFOUND host.docker.internal` | n8n Cloud cannot reach local Docker hostnames — use ngrok public URL       |
| Normalize → `text: null`         | WhatsApp Trigger sends unwrapped `messages[]`, not raw `entry[].changes[]` |
| Text went to Confirm Draft       | Broken IF/Switch conditions                                                |
| `Text Body is required`          | WhatsApp text nodes need `textBody`, not `text`                            |

---

## FIX (repo)

File: `n8n/workflows/whatsapp-trip-creation.json`

1. Normalize supports Trigger + raw Meta shapes
2. IF / Switch use `route` (`TEXT` / `CREATE` / `CANCEL`)
3. HTTP URLs → current ngrok base above
4. Resolve Open Draft before Confirm/Cancel (`GET /v1/trip-drafts/open`)
5. Header `ngrok-skip-browser-warning: true` on HTTP nodes
6. Text send nodes use `textBody`

Backend: `GET /v1/trip-drafts/open`

---

## How to run the app (2 terminals)

### Terminal 1 — API + Postgres

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow"
docker compose up -d
curl http://localhost:8000/health
```

OpenAPI docs: http://localhost:8000/docs

### Terminal 2 — ngrok (keep running)

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow"
ngrok http 8000
```

Or one-shot helper (starts Docker + ngrok):

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow"
./scripts/start-tunnel.sh
```

Copy the new `https://49b2-103-248-87-67.ngrok-free.app` from ngrok UI / http://127.0.0.1:4040 into every n8n HTTP node if it changed.

### Stop everything

```bash
pkill -f "ngrok http" || true
cd "/Users/namanmalhan/Downloads/Freight AI flow"
docker compose down
```

---

## n8n Cloud — after URL update

1. Import / re-import `n8n/workflows/whatsapp-trip-creation.json`
2. Confirm every HTTP URL starts with current ngrok base (no `host.docker.internal`, no `/api/v1`)
3. Credentials:
   - Trigger → WhatsApp Trigger API (OAuth2)
   - Send nodes → WhatsApp Business Cloud API
4. Publish / Active ON

### Text Body expressions (if UI still complains)

| Node              | Text Body                                                           |
| ----------------- | ------------------------------------------------------------------- |
| Ask Missing Field | `={{ $json.next_question }}`                                        |
| Send Trip Created | `={{ $json.summary \|\| ('Trip #' + $json.trip_id + ' created') }}` |
| Send Cancelled    | `={{ 'Draft #D-' + $json.draft_id + ' cancel ho gaya.' }}`          |

---

## Kyun CREATE / EDIT / CANCEL buttons nahi dikhe?

n8n ka built-in **WhatsApp** send node sirf plain text / media bhejta hai — **interactive reply buttons support nahi**.  
Isliye pehle sirf draft summary text aaya, bina Accept/Reject buttons ke.

**Fix (repo):** `Send Confirmation Buttons` ab **HTTP Request → Graph API** hai:

`POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages`  
with `type: interactive` + CREATE / EDIT / CANCEL.

Workflow JSON dubara import karo, us node pe WhatsApp Business Cloud API credential select karo, Publish.

---

## Agar last step pe 401 / Authorization failed

Matlab OpenAPI + draft create **OK** hai; fail sirf **WhatsApp Send** credential pe hai.

Meta temporary tokens expire / invalid ho jate hain (logout, 24h). Fix:

1. https://developers.facebook.com/apps/ → **FreightAIAutomation** → **WhatsApp → API Setup**
2. **Generate access token** (or System User permanent token)
3. n8n → Credentials → **WhatsApp Business Cloud API** → paste naya Access Token → Save
4. Confirm these send nodes use that credential:
   - Ask Missing Field
   - Send Confirmation Buttons
   - Send Trip Created
   - Send Cancelled
5. Optional: same token `backend/.env` → `WHATSAPP_ACCESS_TOKEN=` (FastAPI direct webhook path ke liye)
6. Workflow dubara test

Token check (secret print nahi hoga):

```bash
cd "/Users/namanmalhan/Downloads/Freight AI flow"
TOKEN=$(grep '^WHATSAPP_ACCESS_TOKEN=' backend/.env | cut -d= -f2-)
curl -sS "https://graph.facebook.com/v21.0/me" -H "Authorization: Bearer $TOKEN"
# "error" aaya to token still invalid
```

---

## Why Docker image is ~1.5GB but Whisper large-v3 is ~3GB

**Root cause of confusion:** Whisper **weights are not inside** `freightaiflow-api` image.

| What             | Size       | Where                                                                          |
| ---------------- | ---------- | ------------------------------------------------------------------------------ |
| Docker image     | ~1.5–1.7GB | App + Python + ffmpeg + `faster-whisper` **library**                           |
| Model `large-v3` | ~3GB       | Downloaded at **runtime** into volume `whisper_models` → `/models` (`HF_HOME`) |

If `/models` is empty, Whisper never downloaded — usually because media download failed first (expired Meta token), so STT never reached model load.

Check:

```bash
curl -sS http://localhost:8000/v1/stt/status
docker compose exec api du -sh /models
```

---

## STT `empty_transcript_or_media_download_failed` / Send STT Failed

Latest API returns a **specific** `error` field, e.g.:

- `media_download_unauthorized_token_expired` ← fix Meta token in `backend/.env`
- `local_dependency_missing:requests` ← rebuild image (fixed in repo)
- `empty_transcript` ← audio downloaded but STT produced nothing

---

## WhatsApp 401 / OAuthException code 190

**Symptom:** FastAPI logs `401 Unauthorized` on `graph.facebook.com/.../messages` while handling voice.

**Root cause:** `backend/.env` → `WHATSAPP_ACCESS_TOKEN` **expired** (Meta temporary tokens expire ~24h). Same token is required to **download** voice media before Whisper can run — so STT never gets audio bytes.

**Fix:** Meta Developer → WhatsApp → API Setup → **Generate access token** → paste into:

1. `backend/.env` → `WHATSAPP_ACCESS_TOKEN=`
2. n8n credential **WhatsApp Business Cloud API** (send nodes)
3. `docker compose up -d --build api` (or restart api)

Verify (secret not printed):

```bash
TOKEN=$(grep '^WHATSAPP_ACCESS_TOKEN=' backend/.env | cut -d= -f2-)
curl -sS "https://graph.facebook.com/v21.0/me" -H "Authorization: Bearer $TOKEN"
# must NOT contain "Session has expired"
```

---

## Voice note 422 (`text: null`) — root cause + fix

**Symptom:** n8n `Extract Trip Intent` → `422 Input should be a valid string` with `"text": null`.

**Root cause:** Meta webhook hits **n8n Text Path**. Voice messages have no `message.text.body`, so Normalize set `text=null`. Whisper/faster-whisper only runs on FastAPI `/v1/whatsapp/webhook` — that path was never called.

**Fix (repo):** `n8n/workflows/whatsapp-trip-creation.json`

1. Normalize detects `type=audio` → `route=AUDIO` + `media_id`
2. `IF Audio Message` → `Handle Audio via FastAPI (STT)` posts reconstructed webhook to `/v1/whatsapp/webhook`
3. FastAPI runs local faster-whisper (Groq fallback) + draft replies
4. Non-audio empty text → `IF Has Text` → ignore (no more null extract)

**Action:** Re-import/republish the workflow JSON in n8n Cloud after pulling this change.

---

## Quick verify

```bash
curl -sS http://localhost:8000/health
curl -sS -H "ngrok-skip-browser-warning: true" \
  "https://49b2-103-248-87-67.ngrok-free.app/health"
```

Expected WhatsApp text path:

```
Normalize (route=TEXT) → IF false → Extract → POST Draft → Confirmation buttons
```

CREATE button:

```
Normalize (route=CREATE) → Resolve Open Draft → Confirm → Send Trip Created
```

---

## Alternate path (skip n8n)

Point Meta webhook Callback URL to:

`https://49b2-103-248-87-67.ngrok-free.app/v1/whatsapp/webhook`

Verify token: `freightai_webhook_verify_2026` (or value in `backend/.env`)

## Fault-tolerant n8n workflow (2026-08-29)

HTTP nodes use `onError: continueErrorOutput` → `Build Error Message` → `Send Error to User`.
WhatsApp send nodes do **not** continue on fail (no error loops).

### Re-import after pulling this repo

1. n8n → Workflows → open **Freight AI - WhatsApp Trip Creation (Text + Voice)** (or Import from file).
2. Import / replace from `n8n/workflows/whatsapp-trip-creation.json`.
3. Re-select WhatsApp credentials on Trigger + all Send / Graph nodes if import cleared them.
4. **Publish** (keep Active).
5. Smoke test: stop FastAPI, send a WhatsApp text → should receive _Service temporarily unavailable..._ (or generic), not silence.
6. Smoke test: voice with bad token → _Voice processing unavailable..._ or _WhatsApp access expired..._
7. Smoke test: after draft buttons, tap **CREATE** → trip created message (not silence).

### CREATE tap = new execution (this is correct)

WhatsApp sends a **new webhook** when the user taps CREATE. n8n starts a **new execution** that loads open draft `D-N` from the DB. The previous voice execution ending is normal — do **not** try to keep one execution open forever. Keep the workflow **Published/Active** instead.

### CREATE pressed but no WhatsApp reply (fixed 2026-08-29)

Causes that used to go silent:

1. Button reply not parsed → fell into Ignore Empty (no send) — **fixed**: harder Normalize + `Send Unsupported`
2. EDIT / other button → Switch fallback unconnected — **fixed**: `Send Edit Hint`
3. HTTP confirm/resolve failed with no error branch — use fault-tolerant import above
4. Stale ngrok URL in HTTP nodes — update base URL if ngrok restarted
