# Integration Status — Naman Malhan

Last updated: 2026-08-28

## Verified Accounts

| Service        | Status     | Details                                                                    |
| -------------- | ---------- | -------------------------------------------------------------------------- |
| Meta Developer | ✅ Created | App: **FreightAIAutomation**, ID: `4576648785989127`, Mode: In development |
| Meta Business  | ✅ Linked  | Business: **Naman Malhan**, ID: `657846736355138`                          |
| n8n Cloud      | ✅ Created | https://namanmlhan.app.n8n.cloud                                           |
| OpenAI         | ⚠️ Partial | Key saved in `backend/.env` — **billing/quota empty** (429 error)          |

## OpenAI Key — Action Required

Key connects but returns:
`You exceeded your current quota, please check your plan and billing`

→ Add credits: https://platform.openai.com/settings/organization/billing

Until billing is active, system uses **rule-based Hindi parser** (works for demo, not ideal for messy input).

**Security:** Key was shared in chat. After billing setup, **rotate the key** at https://platform.openai.com/api-keys

---

## Still Pending (Your Side)

### A. Meta — WhatsApp Product Setup

In app dashboard: https://developers.facebook.com/apps/4576648785989127/dashboard/

1. Left sidebar → **Add Product** → **WhatsApp** → Set up
2. Go to **WhatsApp → API Setup**
3. Copy these 4 values (send to agent or paste in `.env`):

```
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_BUSINESS_ACCOUNT_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=any-random-string-you-choose
```

4. Add your personal WhatsApp as **test recipient** (API Setup page)
5. Under **Webhook**, set callback URL to n8n (after Step B)

### B. n8n — Workflow + WhatsApp

Project: https://namanmlhan.app.n8n.cloud/projects/TwNsQ9tLnTEtaO3Q/workflows

1. **Import** `n8n/workflows/whatsapp-trip-creation.json`
2. **Credentials** → Add WhatsApp Business Cloud (Meta token + Phone Number ID)
3. **Activate** workflow
4. Copy webhook URL from WhatsApp Trigger node → paste in Meta app webhook config

### C. Public URL for FastAPI (Critical) — ngrok only

n8n Cloud **cannot** reach `localhost:8000`. Use **ngrok** (not Cloudflare):

```bash
ngrok http 8000
```

Then update every n8n HTTP node base URL to the new `https://xxxx.ngrok-free.app` (free ngrok URLs change on restart). Current value is also in `backend/.env` → `PUBLIC_API_BASE_URL` and `n8n/workflows/whatsapp-trip-creation.json`.

### D. Dispatcher Phone Number

Which WhatsApp number will send trip messages? Add to DB:

```sql
-- Replace with real dispatcher number (country code, no +)
UPDATE users SET phone = '91XXXXXXXXXX' WHERE phone = '919876543210';
```

Or tell the agent your number to update seed data.

---

## What Agent Can Do Next (No Blockers)

- [x] Save OpenAI key to `backend/.env`
- [x] Add `.gitignore` (secrets won't commit)
- [ ] Update n8n workflow URLs once you have ngrok/public URL
- [ ] Add your dispatcher phone to seed data
- [ ] Help configure Meta webhook step-by-step (screenshots welcome)
- [ ] End-to-end test once WhatsApp + n8n + public API are connected

---

## Quick Test (Works Now — No WhatsApp)

```bash
cd backend
docker compose -f ../docker-compose.yml up -d postgres   # from project root
uvicorn app.main:app --reload --port 8000
pytest -v
curl http://localhost:8000/health
```

Demo API: http://localhost:8000/docs
