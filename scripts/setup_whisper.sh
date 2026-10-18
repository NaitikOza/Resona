#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODEL_NAME="${1:-medium.en}"
MODEL_DIR="${REPO_DIR}/local_data/models"

case "${MODEL_NAME}" in
  medium.en)
    MODEL_FILE="ggml-medium.en.bin"
    EXPECTED_SHA1="8c30f0e44ce9560643ebd10bbe50cd20eafd3723"
    ;;
  small.en)
    MODEL_FILE="ggml-small.en.bin"
    EXPECTED_SHA1="db8a495a91d927739e50b3fc1cc4c6b8f6c2d022"
    ;;
  base.en)
    MODEL_FILE="ggml-base.en.bin"
    EXPECTED_SHA1="137c40403d78fd54d454da0f9bd998f78703390c"
    ;;
  tiny.en)
    MODEL_FILE="ggml-tiny.en.bin"
    EXPECTED_SHA1="c78c86eb1a8faa21b369bcd33207cc90d64ae9df"
    ;;
  *)
    echo "Supported models: medium.en (default), small.en, base.en, or tiny.en" >&2
    exit 2
    ;;
esac

mkdir -p "${MODEL_DIR}"
MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL_FILE}"

verify_model() {
  local actual
  actual="$(LC_ALL=C shasum -a 1 "${MODEL_PATH}" | awk '{print $1}')"
  if [[ "${actual}" != "${EXPECTED_SHA1}" ]]; then
    echo "Checksum mismatch for ${MODEL_PATH}" >&2
    echo "Expected ${EXPECTED_SHA1}; received ${actual}" >&2
    return 1
  fi
}

if [[ -f "${MODEL_PATH}" ]] && verify_model; then
  echo "Verified existing ${MODEL_NAME} model: ${MODEL_PATH}"
else
  rm -f "${MODEL_PATH}.partial"
  echo "Downloading the official whisper.cpp ${MODEL_NAME} model..."
  curl --fail --location --retry 3 --output "${MODEL_PATH}.partial" "${MODEL_URL}"
  mv "${MODEL_PATH}.partial" "${MODEL_PATH}"
  verify_model
  echo "Downloaded and verified ${MODEL_PATH}"
fi

if command -v whisper-cli >/dev/null 2>&1; then
  BINARY_PATH="$(command -v whisper-cli)"
  echo "whisper.cpp CLI found: ${BINARY_PATH}"
else
  echo "whisper-cli is not installed." >&2
  echo "macOS: brew install whisper-cpp" >&2
  echo "Other platforms: build the official https://github.com/ggml-org/whisper.cpp repository." >&2
  exit 3
fi

cat <<EOF

Resona local ASR is ready. Add these values to apps/api/.env if your paths differ:
WHISPER_BINARY_PATH=${BINARY_PATH}
WHISPER_MODEL_PATH=${MODEL_PATH}
EOF
