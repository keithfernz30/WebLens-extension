#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/weblens-backend"

cd "$BACKEND_DIR"
source venv/bin/activate

uvicorn main:app --host 127.0.0.1 --port 8000 >/tmp/weblens_smoke.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID >/dev/null 2>&1 || true' EXIT

for _ in {1..20}; do
  if curl -sS http://127.0.0.1:8000/ >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "[1/3] Health check"
curl -sS -f http://127.0.0.1:8000/ >/tmp/weblens_health.json
cat /tmp/weblens_health.json

echo "[2/3] Validation check (generate mode without task should fail with 400)"
HTTP_CODE=$(curl -sS -o /tmp/weblens_generate_error.json -w "%{http_code}" -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"mode":"generate","task":"","content":"Example content"}')
cat /tmp/weblens_generate_error.json
if [[ "$HTTP_CODE" != "400" ]]; then
  echo "Expected 400 but got $HTTP_CODE"
  exit 1
fi

echo "[3/3] Optional live summarize check"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  curl -sS -f -X POST http://127.0.0.1:8000/analyze \
    -H "Content-Type: application/json" \
    -d '{"mode":"summarize","task":"","content":"WebLens helps users understand web pages quickly."}'
else
  echo "Skipping summarize check because GEMINI_API_KEY is not set in shell."
fi

echo "Smoke tests passed."
