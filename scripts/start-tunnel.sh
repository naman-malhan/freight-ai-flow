#!/usr/bin/env bash
# Start Docker API + ngrok tunnel (leave this terminal running).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

docker compose up -d
echo "Waiting for API on :8000..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null; then
    echo "API healthy."
    break
  fi
  sleep 1
done

if ! curl -sf http://localhost:8000/health >/dev/null; then
  echo "ERROR: API not healthy on http://localhost:8000/health" >&2
  echo "If port 8000 is busy (another app), stop that process first." >&2
  exit 1
fi

echo "Starting ngrok (Ctrl+C to stop). Copy the https://....ngrok-free.app URL into n8n HTTP nodes."
exec ngrok http 8000
