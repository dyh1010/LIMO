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

# LEGACY_ROS2_OFFLINE_ONLY: validates the retained ament/ROS2 package layout;
# it cannot authorize a ROS1/Noetic deployment.

workspace="${1:-/home/agilex/limo_cleanup_ws}"
output_path="${2:-}"

if [[ ! -f "${workspace}/install/setup.bash" ]]; then
  echo "workspace install is missing: ${workspace}/install/setup.bash" >&2
  exit 1
fi

source "${workspace}/install/setup.bash"

arguments=()
if [[ -n "${output_path}" ]]; then
  arguments+=(--json-output "${output_path}")
fi

python3 -m limo_cleanup_voice.voice_preflight "${arguments[@]}"

echo 'SAFETY: preflight completed without ROS nodes, audio devices, or motion.'
