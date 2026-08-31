# n8n Fault-Tolerant WhatsApp Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `whatsapp-trip-creation.json` so HTTP failures never silence the user — every hard failure routes to a shared English WhatsApp error reply, while WhatsApp send nodes never recurse on fail.

**Architecture:** Enable `onError: continueErrorOutput` on all FastAPI/Graph HTTP nodes; wire their error outputs into a new Code node (`Build Error Message`) that classifies the failure and a new WhatsApp node (`Send Error to User`). Soft STT `{ok:false}` keeps using `Send STT Failed` with message text keyed by `stt_error`.

**Tech Stack:** n8n workflow JSON, n8n Code node (JavaScript), WhatsApp Business Cloud API nodes, existing FastAPI error strings.

## Global Constraints

- User-facing copy is **short English only** (verbatim strings from the spec).
- WhatsApp send nodes must **not** set `onError` / `continueOnFail`.
- Do not change FastAPI backend contracts in this plan.
- Do not refactor ngrok base URLs.
- Spec: `docs/superpowers/specs/2026-08-29-n8n-fault-tolerant-workflow-design.md`.
- Primary file: `n8n/workflows/whatsapp-trip-creation.json`.
- Commit only when the user explicitly asks (do not auto-commit).

---

## File map

| File | Responsibility |
|------|----------------|
| `n8n/lib/build_error_message.js` | Pure classifier + message map (unit-tested, then copied into Code node) |
| `n8n/lib/build_error_message.test.js` | Node assert tests for classification |
| `n8n/workflows/whatsapp-trip-creation.json` | Workflow nodes, `onError`, connections, STT fail copy |
| `N8N_ERROR_FIX.md` | Short “fault tolerance / re-import” note for operators |

---

### Task 1: Error message classifier (testable JS)

**Files:**
- Create: `n8n/lib/build_error_message.js`
- Create: `n8n/lib/build_error_message.test.js`

**Interfaces:**
- Produces: `classifyError({ failedNode, statusCode, message, bodyText }) → { error_code, text_body }`
- Produces: `MESSAGES` map with exact English strings from the spec

- [ ] **Step 1: Write failing tests**

Create `n8n/lib/build_error_message.test.js`:

```js
const assert = require('assert');
const { classifyError, MESSAGES } = require('./build_error_message');

assert.strictEqual(
  classifyError({
    failedNode: 'Handle Audio via FastAPI (STT)',
    statusCode: 401,
    message: 'Unauthorized',
    bodyText: 'media_download_unauthorized_token_expired',
  }).error_code,
  'token_expired'
);

assert.strictEqual(
  classifyError({
    failedNode: 'Extract Trip Intent',
    statusCode: 504,
    message: 'timeout',
    bodyText: '',
  }).error_code,
  'api_timeout'
);

assert.strictEqual(
  classifyError({
    failedNode: 'Resolve Open Draft (CREATE)',
    statusCode: 404,
    message: 'Not Found',
    bodyText: 'no open draft',
  }).error_code,
  'draft_not_found'
);

assert.strictEqual(
  classifyError({
    failedNode: 'POST Trip Draft',
    statusCode: 500,
    message: 'Internal',
    bodyText: 'boom',
  }).error_code,
  'generic'
);

assert.strictEqual(
  classifyError({
    failedNode: 'Send Confirmation Buttons',
    statusCode: 401,
    message: 'Session has expired',
    bodyText: '',
  }).error_code,
  'token_expired'
);

assert.strictEqual(MESSAGES.stt_failed, 'Could not understand the voice note. Please type the trip details.');
assert.strictEqual(MESSAGES.stt_token, 'Voice processing unavailable right now. Please type the trip details.');

console.log('build_error_message.test.js: OK');
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

Run: `node n8n/lib/build_error_message.test.js`  
Expected: `Cannot find module './build_error_message'`

- [ ] **Step 3: Implement classifier**

Create `n8n/lib/build_error_message.js`:

```js
'use strict';

const MESSAGES = {
  token_expired: 'WhatsApp access expired. Please try again later.',
  stt_failed: 'Could not understand the voice note. Please type the trip details.',
  stt_token: 'Voice processing unavailable right now. Please type the trip details.',
  api_timeout: 'Service temporarily unavailable. Please retry in a moment.',
  draft_not_found: 'No open draft found. Please send trip details first.',
  generic: 'Something went wrong. Please type the trip details and try again.',
};

function classifyError({ failedNode, statusCode, message, bodyText }) {
  const node = String(failedNode || '');
  const msg = `${message || ''} ${bodyText || ''}`.toLowerCase();
  const code = Number(statusCode) || null;

  const looksToken =
    code === 401 ||
    code === 403 ||
    msg.includes('session has expired') ||
    msg.includes('oauth') ||
    msg.includes('media_download_unauthorized') ||
    msg.includes('token_expired') ||
    msg.includes('unauthorized');

  const looksTimeout =
    code === 502 ||
    code === 503 ||
    code === 504 ||
    msg.includes('timeout') ||
    msg.includes('econnrefused') ||
    msg.includes('enotfound') ||
    msg.includes('socket hang up');

  const looksDraftMissing =
    node.startsWith('Resolve Open Draft') &&
    (code === 404 || msg.includes('no open draft') || msg.includes('not found'));

  let error_code = 'generic';
  if (looksToken) error_code = 'token_expired';
  else if (looksDraftMissing) error_code = 'draft_not_found';
  else if (looksTimeout) error_code = 'api_timeout';

  // Soft-STT helpers (used by Send STT Failed path, not HTTP throw)
  if (node === '__soft_stt__') {
    if (msg.includes('media_download_unauthorized') || msg.includes('token_expired')) {
      error_code = 'stt_token';
    } else {
      error_code = 'stt_failed';
    }
  }

  return { error_code, text_body: MESSAGES[error_code] || MESSAGES.generic };
}

module.exports = { classifyError, MESSAGES };
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `node n8n/lib/build_error_message.test.js`  
Expected: `build_error_message.test.js: OK`

---

### Task 2: Add `Build Error Message` + `Send Error to User` nodes

**Files:**
- Modify: `n8n/workflows/whatsapp-trip-creation.json`

**Interfaces:**
- Consumes: `classifyError` logic inlined into Code node `jsCode` (same rules as Task 1; CommonJS `require` is not available in n8n Code — paste the function body)
- Produces nodes:
  - id `build-error-message`, name `Build Error Message`
  - id `send-error-to-user`, name `Send Error to User`

- [ ] **Step 1: Append nodes to the `nodes` array**

Add (positions roughly `[1900, 300]` and `[2120, 300]` — adjust to avoid overlap):

**Build Error Message** — `n8n-nodes-base.code` typeVersion 2 — `jsCode`:

```js
const norm = $('Normalize Incoming Message').first().json || {};
const item = $input.first();
const err = item.json.error || item.json || {};
const failedNode =
  err.node?.name ||
  err.context?.node?.name ||
  item.pairedItem?.sourceOverwrite?.node ||
  ($execution?.error?.node?.name) ||
  'unknown';
const statusCode =
  err.httpCode ||
  err.statusCode ||
  err.context?.httpCode ||
  err.response?.statusCode ||
  null;
const message = err.message || err.description || '';
const bodyText =
  (typeof err.description === 'string' ? err.description : '') +
  ' ' +
  (typeof err.message === 'string' ? err.message : '') +
  ' ' +
  JSON.stringify(err).slice(0, 500);

const MESSAGES = {
  token_expired: 'WhatsApp access expired. Please try again later.',
  stt_failed: 'Could not understand the voice note. Please type the trip details.',
  stt_token: 'Voice processing unavailable right now. Please type the trip details.',
  api_timeout: 'Service temporarily unavailable. Please retry in a moment.',
  draft_not_found: 'No open draft found. Please send trip details first.',
  generic: 'Something went wrong. Please type the trip details and try again.',
};

const msg = `${message} ${bodyText}`.toLowerCase();
const code = Number(statusCode) || null;
const node = String(failedNode || '');

const looksToken =
  code === 401 ||
  code === 403 ||
  msg.includes('session has expired') ||
  msg.includes('oauth') ||
  msg.includes('media_download_unauthorized') ||
  msg.includes('token_expired') ||
  msg.includes('unauthorized');

const looksTimeout =
  code === 502 ||
  code === 503 ||
  code === 504 ||
  msg.includes('timeout') ||
  msg.includes('econnrefused') ||
  msg.includes('enotfound') ||
  msg.includes('socket hang up');

const looksDraftMissing =
  node.startsWith('Resolve Open Draft') &&
  (code === 404 || msg.includes('no open draft') || msg.includes('not found'));

let error_code = 'generic';
if (looksToken) error_code = 'token_expired';
else if (looksDraftMissing) error_code = 'draft_not_found';
else if (looksTimeout) error_code = 'api_timeout';

return [{
  json: {
    sender_phone: norm.sender_phone || null,
    failed_node: node,
    error_code,
    text_body: MESSAGES[error_code] || MESSAGES.generic,
    debug: { statusCode: code, message: String(message).slice(0, 300) },
  },
}];
```

**Send Error to User** — `n8n-nodes-base.whatsApp` typeVersion 1:

```json
{
  "parameters": {
    "operation": "send",
    "phoneNumberId": "1256431730893371",
    "recipientPhoneNumber": "={{ $json.sender_phone }}",
    "textBody": "={{ $json.text_body }}"
  },
  "id": "send-error-to-user",
  "name": "Send Error to User",
  "type": "n8n-nodes-base.whatsApp",
  "typeVersion": 1,
  "position": [2120, 300],
  "notes": "Terminal error notify. Do NOT enable continueOnFail / onError."
}
```

- [ ] **Step 2: Wire connection**

In `connections`:

```json
"Build Error Message": {
  "main": [
    [
      {
        "node": "Send Error to User",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

- [ ] **Step 3: Validate JSON parses**

Run: `node -e "JSON.parse(require('fs').readFileSync('n8n/workflows/whatsapp-trip-creation.json','utf8')); console.log('OK')"`  
Expected: `OK`

---

### Task 3: Enable Error Output on all HTTP nodes + wire to Build Error Message

**Files:**
- Modify: `n8n/workflows/whatsapp-trip-creation.json`

**Interfaces:**
- Consumes: nodes from Task 2
- Each HTTP node below must include top-level `"onError": "continueErrorOutput"`
- Each node's `connections` `main` array must have **two** branches: `[successTargets, errorTargets]` where `errorTargets` → `Build Error Message`

HTTP nodes (exact names):

1. `Extract Trip Intent`
2. `POST Trip Draft`
3. `Handle Audio via FastAPI (STT)`
4. `Resolve Open Draft (CREATE)`
5. `Resolve Open Draft (CANCEL)`
6. `Confirm Draft`
7. `Cancel Draft`
8. `Send Confirmation Buttons`

- [ ] **Step 1: Set `onError` on each of the 8 nodes**

Example for one node object (repeat for all 8):

```json
"onError": "continueErrorOutput"
```

Place it as a sibling of `parameters`, `id`, `name`, `type`, `typeVersion`, `position`.

- [ ] **Step 2: Update connections so error branch is index 1**

Pattern — preserve existing success targets at index 0; add error at index 1:

```json
"Extract Trip Intent": {
  "main": [
    [
      {
        "node": "POST Trip Draft",
        "type": "main",
        "index": 0
      }
    ],
    [
      {
        "node": "Build Error Message",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

Repeat for:

| Node | Success target (unchanged) | Error target |
|------|----------------------------|--------------|
| Extract Trip Intent | POST Trip Draft | Build Error Message |
| POST Trip Draft | IF Missing Info | Build Error Message |
| Handle Audio via FastAPI (STT) | Merge Transcript into Flow | Build Error Message |
| Resolve Open Draft (CREATE) | Confirm Draft | Build Error Message |
| Resolve Open Draft (CANCEL) | Cancel Draft | Build Error Message |
| Confirm Draft | Send Trip Created | Build Error Message |
| Cancel Draft | Send Cancelled | Build Error Message |
| Send Confirmation Buttons | _(none today — leave empty success array or omit further)_ | Build Error Message |

For `Send Confirmation Buttons`, if it currently has no outgoing connection, use:

```json
"Send Confirmation Buttons": {
  "main": [
    [],
    [
      {
        "node": "Build Error Message",
        "type": "main",
        "index": 0
      }
    ]
  ]
}
```

- [ ] **Step 3: Assert no WhatsApp send node has onError**

Run:

```bash
node -e "
const w=require('./n8n/workflows/whatsapp-trip-creation.json');
const sends=w.nodes.filter(n=>n.type==='n8n-nodes-base.whatsApp');
for (const n of sends) {
  if (n.onError || n.continueOnFail) throw new Error('Send node must not continue on fail: '+n.name);
}
const http=w.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest');
for (const n of http) {
  if (n.onError!=='continueErrorOutput') throw new Error('HTTP missing onError: '+n.name);
}
console.log('onError wiring checks OK', {http: http.length, sends: sends.length});
"
```

Expected: `onError wiring checks OK` with `http: 8` (or exact HTTP count in file).

---

### Task 4: Soft STT message by `stt_error`

**Files:**
- Modify: `n8n/workflows/whatsapp-trip-creation.json` — nodes `Merge Transcript into Flow`, `Send STT Failed`

**Interfaces:**
- Consumes: `MESSAGES.stt_failed` / `MESSAGES.stt_token` from Task 1
- Soft path only when STT HTTP returns 200 with `{ok:false,...}`

- [ ] **Step 1: Update Merge Transcript `jsCode` to expose `user_error_text`**

Replace Merge Transcript `jsCode` with:

```js
const norm = $('Normalize Incoming Message').item.json;
const stt = $input.first().json || {};
const text = (stt.text || '').trim() || null;
const sttError = stt.error || null;
const tokenish =
  String(sttError || '').includes('media_download_unauthorized') ||
  String(sttError || '').includes('token_expired');
const user_error_text = tokenish
  ? 'Voice processing unavailable right now. Please type the trip details.'
  : 'Could not understand the voice note. Please type the trip details.';
return [{
  json: {
    sender_phone: norm.sender_phone,
    message_id: norm.message_id,
    message_type: norm.message_type,
    media_id: norm.media_id,
    timestamp: norm.timestamp,
    interactive_reply: norm.interactive_reply,
    text,
    stt_ok: !!stt.ok,
    stt_provider: stt.provider || null,
    stt_error: sttError,
    user_error_text,
    route: text ? 'TEXT' : 'AUDIO_FAILED',
  },
}];
```

- [ ] **Step 2: Update Send STT Failed `textBody`**

Set:

```json
"textBody": "={{ $('Merge Transcript into Flow').item.json.user_error_text }}"
```

- [ ] **Step 3: Validate JSON + classifier tests still pass**

```bash
node n8n/lib/build_error_message.test.js
node -e "JSON.parse(require('fs').readFileSync('n8n/workflows/whatsapp-trip-creation.json','utf8')); console.log('OK')"
```

Expected: both OK.

---

### Task 5: Operator docs + import checklist

**Files:**
- Modify: `N8N_ERROR_FIX.md` (append a short section at end)

- [ ] **Step 1: Append section**

```markdown
## Fault-tolerant n8n workflow (2026-08-29)

HTTP nodes use `onError: continueErrorOutput` → `Build Error Message` → `Send Error to User`.
WhatsApp send nodes do **not** continue on fail (no error loops).

### Re-import after pulling this repo

1. n8n → Workflows → open **Freight AI - WhatsApp Trip Creation (Text + Voice)** (or Import from file).
2. Import / replace from `n8n/workflows/whatsapp-trip-creation.json`.
3. Re-select WhatsApp credentials on Trigger + all Send / Graph nodes if import cleared them.
4. **Publish** (keep Active).
5. Smoke test: stop FastAPI, send a WhatsApp text → should receive *Service temporarily unavailable...* (or generic), not silence.
6. Smoke test: voice with bad token → *Voice processing unavailable...* or *WhatsApp access expired...*
```

- [ ] **Step 2: Manual smoke checklist (after user imports)**

- [ ] Text happy path still returns confirmation buttons  
- [ ] FastAPI down → English error WhatsApp message  
- [ ] Soft STT fail → `Send STT Failed` with correct English copy  
- [ ] Execution may show “success” with error branch taken — that is intended; user was notified  

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `onError` on listed HTTP nodes | Task 3 |
| No continue-on-fail on WhatsApp sends | Task 3 assert |
| Build Error Message + Send Error to User | Task 2 |
| Exact English messages | Task 1 + 2 + 4 |
| Soft STT message by `stt_error` | Task 4 |
| Out of scope: retry, global error workflow, URL refactor | Not in plan |
| Re-import docs | Task 5 |

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-08-29-n8n-fault-tolerant-workflow.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — run tasks in this session with checkpoints  

Which approach?
`}