# n8n WhatsApp Trip Workflow — Fault Tolerance Design

**Date:** 2026-08-29  
**Status:** Approved for planning  
**Workflow:** `n8n/workflows/whatsapp-trip-creation.json`  
**Goal:** No unhandled node failure should abort the user-facing path; users always get a clear English WhatsApp reply when something breaks.

---

## Problem

Today the workflow has **no** `onError` / `continueOnFail` settings. When any HTTP or send node throws (timeout, 401, 5xx, credential error), n8n marks the **execution as Error** and stops the branch. Soft STT failures (`{ok:false}`) already route to `Send STT Failed`, but hard HTTP failures do not.

Clarification: each inbound WhatsApp message is **one execution**. That run ending (success or handled error) is normal. “Workflow must not stop” means:

1. Execution must not die on an unhandled node error without notifying the user.
2. The workflow remains **Active/Published** for the next message.

---

## Approach (chosen)

**Continue On Fail / Error Output on HTTP nodes → shared error path → WhatsApp reply.**

- Approach A only (no global Error Workflow, no auto-retry in v1).
- WhatsApp **send** nodes do **not** use continue-on-fail (avoids error→send→error loops).

---

## Architecture

```
[Risky HTTP node]
  success  → existing happy path
  error    → Build Error Message → Send Error to User

[STT soft fail {ok:false} / empty text]
  → IF STT Has Text (false) → Send STT Failed (specific text by stt_error)
```

### Nodes that get Error Output (`onError: continueErrorOutput`)

| Node | Notes |
|------|--------|
| Extract Trip Intent | FastAPI `/v1/extract-trip-intent` |
| POST Trip Draft | FastAPI `/v1/trip-drafts` |
| Handle Audio via FastAPI (STT) | FastAPI `/v1/stt/whatsapp-media` |
| Resolve Open Draft (CREATE) | GET open draft |
| Resolve Open Draft (CANCEL) | GET open draft |
| Confirm Draft | POST confirm |
| Cancel Draft | POST cancel |
| Send Confirmation Buttons | Meta Graph interactive HTTP |

All of these error outputs connect to **Build Error Message**.

### Nodes that do NOT get continue-on-fail

| Node | Reason |
|------|--------|
| Ask Missing Field | Terminal send |
| Send Trip Created | Terminal send |
| Send Cancelled | Terminal send |
| Send STT Failed | Terminal send |
| Send Error to User (new) | Terminal send — must not recurse |

Code / IF / Switch / Normalize nodes keep default behavior (they rarely throw; if they do, that indicates a bug).

---

## New nodes

### 1. `Build Error Message` (Code)

**Inputs:** error item from any failed HTTP node (n8n error payload includes failed node name, status, message/body when available). Also read `sender_phone` from `Normalize Incoming Message`.

**Outputs:**

```json
{
  "sender_phone": "...",
  "failed_node": "Extract Trip Intent",
  "error_code": "api_timeout | token_expired | api_down | draft_not_found | stt_hard_fail | generic",
  "text_body": "<user-facing English string>",
  "debug": { "statusCode": 401, "message": "..." }
}
```

**Classification rules (order matters):**

1. Failed node is STT HTTP **or** body/error contains `media_download_unauthorized` / OAuth / `Session has expired` / HTTP 401 on Graph or media → `token_expired` or `stt_hard_fail` as below.
2. HTTP 401 / 403 or message mentions expired session → `token_expired`.
3. Failed node is Resolve Open Draft* and status 404 / body indicates no draft → `draft_not_found`.
4. Timeout / `ECONNREFUSED` / 502 / 503 / 504 → `api_timeout`.
5. Else → `generic`.

### 2. `Send Error to User` (WhatsApp)

- Credential: same WhatsApp Business Cloud API as other sends.
- `phoneNumberId`: same as existing (`1256431730893371` or env-equivalent).
- `recipientPhoneNumber`: `={{ $json.sender_phone }}`
- `textBody`: `={{ $json.text_body }}`
- **No** continue-on-fail.

---

## User-facing messages (short English)

| `error_code` | Message |
|--------------|---------|
| `token_expired` | WhatsApp access expired. Please try again later. |
| `stt_failed` | Could not understand the voice note. Please type the trip details. |
| `stt_token` | Voice processing unavailable right now. Please type the trip details. |
| `api_timeout` | Service temporarily unavailable. Please retry in a moment. |
| `draft_not_found` | No open draft found. Please send trip details first. |
| `generic` | Something went wrong. Please type the trip details and try again. |

### Soft STT path (existing `Send STT Failed`)

Update `Merge Transcript` / `Send STT Failed` so message depends on `stt_error`:

- `media_download_unauthorized_token_expired` → `stt_token` message
- empty / other STT errors → `stt_failed` message

Hard STT HTTP throw (network/5xx before JSON body) still goes through **Build Error Message**.

---

## Connections

1. Each listed HTTP node: enable Error Output; wire **error** output → `Build Error Message`.
2. `Build Error Message` → `Send Error to User`.
3. Success outputs unchanged.
4. Optional: Switch fallback for unsupported interactive (EDIT / OTHER_BUTTON) may already fall through; out of scope unless already broken — do not expand in this change unless needed for import validity.

---

## Out of scope (v1)

- Auto-retry / backoff on HTTP nodes
- Global n8n Error Workflow
- Keeping a single execution “open forever”
- Changing FastAPI backend error shapes (consume what exists today)
- Permanent Meta System User token setup (separate ops task)

---

## Success criteria

1. Killing FastAPI mid-flow still results in WhatsApp reply (`api_timeout` / `generic`), not a red unhandled execution with silence.
2. Expired Meta token during media download / Graph calls notifies the user with the token / voice-unavailable copy.
3. Happy path (text trip → draft → confirmation buttons) unchanged.
4. WhatsApp send failure does not recurse into another error send.
5. Updated workflow JSON in repo remains importable into n8n cloud.

---

## Implementation notes

- Prefer n8n node setting `onError: "continueErrorOutput"` (n8n 1.x+) so success and error are separate outputs; if cloud UI only exposes “Continue On Fail”, use that and branch with IF on `$json.error` — prefer Error Output when available.
- Keep hardcoded ngrok base URL as-is in this change (no URL refactor).
- After editing JSON, document re-import / publish steps for the user’s n8n cloud workflow.
`}