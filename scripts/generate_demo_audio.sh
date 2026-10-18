#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]] || ! command -v say >/dev/null 2>&1; then
  echo "This optional synthetic-audio helper requires the built-in macOS 'say' command." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_DIR="${REPO_DIR}/local_data/demo"
AIFF_PATH="${OUTPUT_DIR}/synthetic-trauma-demo.aiff"
WAV_PATH="${OUTPUT_DIR}/synthetic-trauma-demo.wav"

mkdir -p "${OUTPUT_DIR}"
say -r 165 -o "${AIFF_PATH}" \
  "Blood pressure is ninety over sixty. Can somebody get an I V? Starting the I V now. I V is established. Prepare two units of blood. Did the blood arrive?"
afconvert -f WAVE -d LEI16@16000 -c 1 "${AIFF_PATH}" "${WAV_PATH}"
rm -f "${AIFF_PATH}"

echo "Created clearly synthetic, uncommitted demo audio: ${WAV_PATH}"
