# Meta WhatsApp Setup — Har Step Mein Kya Bharna Hai

App: **FreightAIAutomation** | App ID: `4576648785989127`

---

## Pehle Samjho: Demo Ke Liye Kya Chahiye vs Baad Mein

| Step                           | Demo ke liye abhi? | Kyon                                      |
| ------------------------------ | ------------------ | ----------------------------------------- |
| Step 1 — Try it out            | ✅ **Abhi karo**   | Test number + token + apna phone add      |
| Step 2 — Webhooks              | ✅ **Abhi karo**   | Incoming WhatsApp → n8n ke liye zaroori   |
| Step 2 — Register real phone   | ❌ Baad mein       | Test number se demo chalega               |
| Step 2 — Payment               | ❌ Baad mein       | User pehle message bhejega to free        |
| Step 3 — Business verification | ❌ Baad mein       | Production / scale ke liye                |
| Next steps — Message template  | ❌ Baad mein       | Hum text reply use karenge, template nahi |

---

## STEP 1: Try It Out (Screenshot 5.12.07)

**Path:** Connect on WhatsApp → Basic setup → **Step 1. Try it out**

### 1A. Claim test number — Already done ✅

| Field                        | Value (aapka)       |
| ---------------------------- | ------------------- |
| Test number                  | `+1 (555) 671-4647` |
| Phone Number ID              | `1256431730893371`  |
| WhatsApp Business Account ID | `1097547112614039`  |

### 1B. Access token — Generate karo

1. **"Generate token"** button dabao
2. Token copy karo → `backend/.env` mein `WHATSAPP_ACCESS_TOKEN=` ke baad paste
3. ⚠️ Token 24 ghante baad expire ho sakta hai (temporary). Demo ke liye theek hai.

### 1C. Test recipient add karo (IMPORTANT)

**"Select a recipient number"** dropdown khali hai — pehle recipient add karna hoga:

1. Same page par **"Add recipient phone number"** ya **"Manage phone number list"** dhundo
2. Apna WhatsApp number add karo: **`+91 7206611897`**
3. WhatsApp par verification code aayega — enter karo
4. Ab dropdown mein `917206611897` select karo

### 1D. Test message (optional — sirf check ke liye)

| Field            | Kya bharna hai                             |
| ---------------- | ------------------------------------------ |
| Your test number | `+1-555-671-4647` (already selected)       |
| Recipient        | `917206611897` (aapka number)              |
| Message          | Koi bhi template (e.g. Order Confirmation) |

**"Send message"** dabao → aapke WhatsApp par message aana chahiye.

> **Note:** Humara Freight AI bot **template** use nahi karta. User pehle message bhejta hai, bot reply karta hai. Template test sirf Meta setup verify karne ke liye hai.

---

## STEP 2: Production Setup (Screenshot 5.12.20, 5.12.32)

**Path:** Basic setup → **Step 2. Production setup**

### 2A. Configure Webhooks — ⭐ SABSE IMPORTANT

Pehle **n8n** mein workflow import karo, phir yahan values bharo.

#### n8n mein (pehle):

1. https://namanmlhan.app.n8n.cloud → workflow import
2. **WhatsApp Trigger** node kholo
3. WhatsApp credentials add karo:
   - **Access Token:** (Step 1 se token)
   - **Phone Number ID:** `1256431730893371`
4. Workflow **Save** karo — n8n webhook URL milega, jaise:
   ```
   https://namanmlhan.app.n8n.cloud/webhook/xxxxxxxx-xxxx-xxxx
   ```

#### Meta mein (phir):

| Field            | Kya bharna hai                          | Example                                              |
| ---------------- | --------------------------------------- | ---------------------------------------------------- |
| **Callback URL** | n8n WhatsApp Trigger ka webhook URL     | `https://namanmlhan.app.n8n.cloud/webhook/abc123...` |
| **Verify token** | Koi bhi secret string (aap choose karo) | `freightai_webhook_verify_2026`                      |

1. Dono fields bharo
2. **"Verify and save"** dabao
3. Meta n8n ko verify karega — agar fail ho to n8n workflow active hona chahiye

> **Verify token** wahi string n8n credentials mein bhi same honi chahiye.

#### Webhook fields subscribe karo:

Meta → WhatsApp → Configuration → Webhook fields:

- ✅ `messages`
- ✅ `message_echoes` (optional)

### 2B. Register your WhatsApp phone number — ❌ ABHI SKIP

| Kya hai                        | Demo ke liye                                 |
| ------------------------------ | -------------------------------------------- |
| Real business number add karna | **Skip** — test number `+1 555...` kaafi hai |

Jab real transporter ko demo doge tab apna/real number register karna.

### 2C. Add payment — ❌ ABHI SKIP

| Kya hai                                              | Demo ke liye |
| ---------------------------------------------------- | ------------ |
| Business-initiated template messages ke liye payment | **Skip**     |

User pehle message bhejega ("Kal Gurgaon se Jaipur...") → 24 hour window → hum free reply kar sakte hain.

---

## STEP 3: Business Verification (Screenshot 5.13.00) — ❌ ABHI SKIP

| Field                          | Demo ke liye     |
| ------------------------------ | ---------------- |
| Where is business registered?  | Skip / baad mein |
| Documents (GST, license, etc.) | Skip / baad mein |

**Kab karna hai:** Jab 20+ phone numbers, official business name, ya high volume messaging chahiye.

---

## NEXT STEPS Page (Screenshot 5.13.20) — Summary

| Item                      | Status         | Action                                    |
| ------------------------- | -------------- | ----------------------------------------- |
| Phone Number              | Not registered | **Skip for demo**                         |
| Payment                   | Not added      | **Skip for demo**                         |
| Business Verification     | Not started    | **Skip for demo**                         |
| Approved message template | Not created    | **Skip** — hum text + buttons use karenge |

---

## n8n Setup (Humare Project Ke Liye)

**URL:** https://namanmlhan.app.n8n.cloud/projects/TwNsQ9tLnTEtaO3Q/workflows

### Workflow import

1. **+ Add workflow** → **Import from file**
2. File: `n8n/workflows/whatsapp-trip-creation.json`

### WhatsApp credentials

| Field               | Value               |
| ------------------- | ------------------- |
| Access Token        | (Meta Step 1 token) |
| Phone Number ID     | `1256431730893371`  |
| Business Account ID | `1097547112614039`  |

### FastAPI URL (ngrok required)

n8n Cloud localhost nahi dekh sakta. Terminal mein:

```bash
# Terminal 1 — API start
cd backend && uvicorn app.main:app --port 8000

# Terminal 2 — public tunnel
ngrok http 8000
```

ngrok URL (e.g. `https://abc123.ngrok-free.app`) n8n ke HTTP Request nodes mein lagao:

- `POST {ngrok-url}/v1/extract-trip-intent`
- `POST {ngrok-url}/v1/trip-drafts`
- etc.

### Workflow activate

Toggle **Active** ON → webhook live ho jayega → Meta Step 2A mein Callback URL paste karo.

---

## End-to-End Test Flow

```
1. Meta Step 1: Token + recipient 917206611897 add ✅
2. n8n: Workflow import + credentials + activate ✅
3. ngrok: Public URL for FastAPI ✅
4. Meta Step 2A: Webhook URL + verify token ✅
5. Apne phone 917206611897 se test number +1 555 671 4647 ko message bhejo:
   "Kal HR55AB1234 Gurgaon se Jaipur, ABC party, freight 42000, driver Rakesh."
6. Bot reply karega → CREATE button → Trip ban jayega
```

---

## Aapke Verified Values (Reference)

| Key                          | Value                           |
| ---------------------------- | ------------------------------- |
| App ID                       | `4576648785989127`              |
| Phone Number ID              | `1256431730893371`              |
| WABA ID                      | `1097547112614039`              |
| Test number (from)           | `+1 (555) 671-4647`             |
| Your phone (to / dispatcher) | `917206611897`                  |
| Verify token (suggested)     | `freightai_webhook_verify_2026` |

---

## Security Reminder

Access token chat mein share ho chuka hai. Demo ke baad Meta dashboard se **naya token generate** karo aur purana revoke karo.
