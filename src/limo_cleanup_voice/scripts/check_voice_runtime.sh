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

set -e

model_path="${1:-/home/agilex/limo_cleanup_ws/models/vosk-model-small-cn-0.22}"

echo "architecture=$(uname -m)"
echo "python=$(python3 --version 2>&1)"
echo "ros_distro=${ROS_DISTRO:-unset}"

python3 -c 'import importlib.util; print("vosk=" + str(importlib.util.find_spec("vosk") is not None)); print("sounddevice=" + str(importlib.util.find_spec("sounddevice") is not None))'

if command -v arecord > /dev/null 2>&1; then
  echo "arecord=$(command -v arecord)"
  arecord -l || true
else
  echo 'arecord=missing'
fi

if command -v espeak-ng > /dev/null 2>&1; then
  echo "espeak_ng=$(command -v espeak-ng)"
else
  echo 'espeak_ng=missing'
fi

if [[ -d "${model_path}" ]]; then
  echo "vosk_model=present:${model_path}"
else
  echo "vosk_model=missing:${model_path}"
fi

echo 'SAFETY: this script does not record audio or publish ROS motion commands.'
