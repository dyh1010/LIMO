#!/usr/bin/env bash
# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

manifest="${1:?usage: evaluate_voice_wav.sh MANIFEST [MODEL_PATH] [REPORT_JSON]}"
model_path="${2:-}"
report_path="${3:-}"

arguments=(--manifest "${manifest}")
if [[ -n "${model_path}" ]]; then
  arguments+=(--model-path "${model_path}")
fi
if [[ -n "${report_path}" ]]; then
  arguments+=(--json-output "${report_path}")
fi

python3 -m limo_cleanup_voice.voice_offline_eval "${arguments[@]}"

echo 'SAFETY: evaluated prerecorded WAV files; no microphone was opened.'
