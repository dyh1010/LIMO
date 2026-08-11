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

set -eo pipefail

workspace="${1:-/home/dyh/robotics/workspaces/limo_cleanup_ws}"
temp_dir="$(mktemp -d)"
launch_pid=''
ros_setup="${ROS_SETUP:-}"

cleanup() {
  result=$?
  if [[ -n "${launch_pid}" ]]; then
    kill "${launch_pid}" 2>/dev/null || true
    wait "${launch_pid}" 2>/dev/null || true
  fi
  if [[ "${result}" -ne 0 ]]; then
    echo 'Voice smoke test diagnostics:' >&2
    for diagnostic_file in "${temp_dir}"/*; do
      if [[ -f "${diagnostic_file}" ]]; then
        echo "--- ${diagnostic_file} ---" >&2
        sed -n '1,160p' "${diagnostic_file}" >&2
      fi
    done
  fi
  rm -rf -- "${temp_dir}"
  return "${result}"
}
trap cleanup EXIT

if [[ -z "${ros_setup}" ]]; then
  if [[ -f /opt/ros/foxy/setup.bash ]]; then
    ros_setup=/opt/ros/foxy/setup.bash
  else
    ros_setup=/opt/ros/humble/setup.bash
  fi
fi

source "${ros_setup}"
source "${workspace}/install/setup.bash"
set -u
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=137

timeout 35s ros2 launch limo_cleanup_voice full_system_with_voice.launch.py \
  mock_step_duration:=0.4 require_wake_word:=true \
  > "${temp_dir}/launch.log" 2>&1 &
launch_pid=$!
sleep 2
timeout 25s ros2 run limo_cleanup_voice voice_smoke_probe
