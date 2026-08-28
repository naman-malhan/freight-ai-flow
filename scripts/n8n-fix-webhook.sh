#!/usr/bin/env bash
# Manage n8n workflows via API — run AFTER creating API key in n8n Settings → API
#
# Usage:
#   export N8N_API_KEY="your-key-here"
#   ./scripts/n8n-fix-webhook.sh

set -euo pipefail

N8N_BASE="${N8N_BASE:-https://namanmlhan.app.n8n.cloud}"
KEEP_WORKFLOW_NAME="${KEEP_WORKFLOW_NAME:-Freight AI - WhatsApp Trip Creation}"

if [[ -z "${N8N_API_KEY:-}" ]]; then
  echo "ERROR: Set N8N_API_KEY first."
  echo "  n8n → Settings → n8n API → Create API key"
  exit 1
fi

echo "=== Active workflows on ${N8N_BASE} ==="
curl -s "${N8N_BASE}/api/v1/workflows?active=true" \
  -H "X-N8N-API-KEY: ${N8N_API_KEY}" | python3 -m json.tool 2>/dev/null || \
curl -s "${N8N_BASE}/api/v1/workflows?active=true" -H "X-N8N-API-KEY: ${N8N_API_KEY}"

echo ""
echo "=== All workflows ==="
WORKFLOWS=$(curl -s "${N8N_BASE}/api/v1/workflows" -H "X-N8N-API-KEY: ${N8N_API_KEY}")

echo "$WORKFLOWS" | python3 -c "
import json, sys, os
data = json.load(sys.stdin)
items = data.get('data', data) if isinstance(data, dict) else data
keep = os.environ.get('KEEP_WORKFLOW_NAME', '')
for w in items:
    active = w.get('active', False)
    print(f\"{'ACTIVE' if active else 'inactive':8} | {w.get('id')} | {w.get('name')}\")
"

echo ""
read -p "Deactivate ALL workflows except '${KEEP_WORKFLOW_NAME}'? (y/N) " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

echo "$WORKFLOWS" | python3 -c "
import json, sys, os, urllib.request

data = json.load(sys.stdin)
items = data.get('data', data) if isinstance(data, dict) else data
keep = os.environ.get('KEEP_WORKFLOW_NAME', '')
base = os.environ.get('N8N_BASE', 'https://namanmlhan.app.n8n.cloud')
key = os.environ['N8N_API_KEY']

for w in items:
    if not w.get('active'):
        continue
    if w.get('name') == keep:
        print(f\"Keeping active: {w['name']} ({w['id']})\")
        continue
    wid = w['id']
    name = w.get('name')
    req = urllib.request.Request(
        f'{base}/api/v1/workflows/{wid}/deactivate',
        method='POST',
        headers={'X-N8N-API-KEY': key},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f\"Deactivated: {name} ({wid})\")
    except Exception as e:
        print(f\"Failed to deactivate {name}: {e}\")
"

echo ""
echo "Done. Now in n8n: activate ONLY '${KEEP_WORKFLOW_NAME}' and retry."
