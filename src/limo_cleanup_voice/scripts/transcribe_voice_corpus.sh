#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 DECODE_MANIFEST USER_PROVIDED_MODEL_DIRECTORY NEW_REPORT_JSON" >&2
  exit 2
fi

python3 -m limo_cleanup_voice.voice_wav_transcription_run \
  --manifest "$1" \
  --model-path "$2" \
  --json-output "$3"
