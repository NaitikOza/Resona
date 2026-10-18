#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "${RESONA_WHISPER_PID:-}" ]]; then kill "${RESONA_WHISPER_PID}" 2>/dev/null || true; fi
  if [[ -n "${API_PID:-}" ]]; then kill "${API_PID}" 2>/dev/null || true; fi
  if [[ -n "${WEB_PID:-}" ]]; then kill "${WEB_PID}" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

RESONA_WHISPER_MODEL="${REPO_DIR}/local_data/models/ggml-medium.en.bin"
RESONA_WHISPER_URL="${WHISPER_SERVER_URL:-http://127.0.0.1:8081}"
if [[ -z "${WHISPER_SERVER_URL:-}" ]] && command -v whisper-server >/dev/null 2>&1 && [[ -f "${RESONA_WHISPER_MODEL}" ]]; then
  if ! curl --silent --fail "${RESONA_WHISPER_URL}/" >/dev/null 2>&1; then
    whisper-server \
      -m "${RESONA_WHISPER_MODEL}" \
      -t "${WHISPER_THREADS:-4}" \
      -l en \
      -sns \
      --host 127.0.0.1 \
      --port 8081 \
      >"${REPO_DIR}/local_data/whisper-server.log" 2>&1 &
    RESONA_WHISPER_PID=$!
    for _ in {1..40}; do
      if curl --silent --fail "${RESONA_WHISPER_URL}/" >/dev/null 2>&1; then break; fi
      sleep 0.25
    done
  fi
  export WHISPER_SERVER_URL="${RESONA_WHISPER_URL}"
fi

(
  cd "${REPO_DIR}/apps/api"
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
API_PID=$!

(
  cd "${REPO_DIR}/apps/web"
  pnpm dev --hostname 127.0.0.1
) &
WEB_PID=$!

echo "Resona local services starting:"
echo "  Website: http://127.0.0.1:3000"
echo "  API:     http://127.0.0.1:8000/api/health"
wait
