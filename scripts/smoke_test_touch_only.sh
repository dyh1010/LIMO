#!/usr/bin/env bash

set -euo pipefail

readonly LEGACY_EXIT=64
readonly OFFLINE_DOMAIN_ID=221
readonly OFFLINE_RMW=rmw_fastrtps_cpp

echo 'FIELD_RUNTIME_AUTHORITY=ROS1_NOETIC'
echo 'LEGACY_ROS2_OFFLINE_ONLY'
echo 'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'

if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE-}" != '1' ]]; then
  echo 'BLOCKED: set LIMO_ALLOW_LEGACY_ROS2_OFFLINE=1 for this isolated historical mock only.' >&2
  exit "${LEGACY_EXIT}"
fi
if [[ "$#" -ne 0 ]]; then
  echo 'BLOCKED: legacy offline smoke accepts no command-line overrides.' >&2
  exit "${LEGACY_EXIT}"
fi

reject_set_environment() {
  local variable
  for variable in "$@"; do
    if [[ -v "${variable}" ]]; then
      echo "BLOCKED: environment override is forbidden: ${variable}" >&2
      exit "${LEGACY_EXIT}"
    fi
  done
}

if [[ -v ROS_LOCALHOST_ONLY && "${ROS_LOCALHOST_ONLY}" != '1' ]]; then
  echo 'BLOCKED: ROS_LOCALHOST_ONLY must be exactly 1.' >&2
  exit "${LEGACY_EXIT}"
fi
if [[ -v ROS_DOMAIN_ID && "${ROS_DOMAIN_ID}" != "${OFFLINE_DOMAIN_ID}" ]]; then
  echo "BLOCKED: ROS_DOMAIN_ID must be the dedicated offline domain ${OFFLINE_DOMAIN_ID}." >&2
  exit "${LEGACY_EXIT}"
fi
if [[ -v RMW_IMPLEMENTATION && "${RMW_IMPLEMENTATION}" != "${OFFLINE_RMW}" ]]; then
  echo "BLOCKED: RMW_IMPLEMENTATION must be ${OFFLINE_RMW}." >&2
  exit "${LEGACY_EXIT}"
fi
reject_set_environment \
  ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE \
  FASTDDS_DEFAULT_PROFILES_FILE ROS_SETUP TRACKED_SMOKE_SETUP \
  USE_TRACKED_BASE_CONTROLLER ALLOW_BASE_MOTION USE_REAL_PERCEPTION \
  USE_MOCK_PERCEPTION USE_MOCK_EXECUTOR EXECUTOR_DRY_RUN \
  USE_GRIPPER_CONTROLLER ALLOW_GRIPPER_MOTION ALLOW_ARM_MOTION \
  GRIPPER_BACKEND BASE_OUTPUT_TOPIC RGB_TOPIC DEPTH_TOPIC \
  CAMERA_INFO_TOPIC DEPTH_CAMERA_INFO_TOPIC DETECTOR_DEVICE \
  PERCEPTION_PYTHON TRACKED_BASE_PORT

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "${script_dir}/.." && pwd)"
ros_setup=/opt/ros/humble/setup.bash
if [[ ! -f "${ros_setup}" ]]; then
  echo "BLOCKED: fixed legacy setup is missing: ${ros_setup}" >&2
  exit 2
fi
if [[ ! -f "${workspace}/install/setup.bash" ]]; then
  echo 'BLOCKED: built workspace setup is missing.' >&2
  exit 2
fi

export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=221
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
source "${ros_setup}"
source "${workspace}/install/setup.bash"

# Setup files are not trusted to preserve isolation. Reassert and verify the
# fixed offline values before the first graph or Python operation.
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=221
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
reject_set_environment \
  ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE \
  FASTDDS_DEFAULT_PROFILES_FILE
if [[ "${ROS_LOCALHOST_ONLY}" != '1' \
    || "${ROS_DOMAIN_ID}" != '221' \
    || "${RMW_IMPLEMENTATION}" != 'rmw_fastrtps_cpp' ]]; then
  echo 'BLOCKED: legacy offline isolation could not be proven.' >&2
  exit "${LEGACY_EXIT}"
fi

test_dir=$(mktemp -d /tmp/limo_cleanup_touch_only.XXXXXX)
log_file="${test_dir}/launch.log"
nodes_file="${test_dir}/nodes.txt"
launch_pid=''

stop_launch() {
  if [[ -n "${launch_pid}" ]] && kill -0 -- "-${launch_pid}" 2>/dev/null; then
    kill -INT -- "-${launch_pid}" 2>/dev/null || true
    for _ in {1..60}; do
      if ! kill -0 -- "-${launch_pid}" 2>/dev/null; then
        break
      fi
      sleep 0.10
    done
    if kill -0 -- "-${launch_pid}" 2>/dev/null; then
      kill -TERM -- "-${launch_pid}" 2>/dev/null || true
    fi
    wait "${launch_pid}" 2>/dev/null || true
  fi
}

cleanup() {
  stop_launch
  rm -rf -- "${test_dir}"
}
trap cleanup EXIT

setsid ros2 launch \
  limo_cleanup_bringup cleanup_system.launch.py \
  use_real_perception:=false \
  use_mock_perception:=true \
  use_mock_executor:=true \
  use_detection_gate:=true \
  use_gripper_controller:=false \
  allow_gripper_motion:=false \
  gripper_backend:=dry_run \
  executor_dry_run:=true \
  allow_arm_motion:=false \
  use_tracked_base_controller:=false \
  allow_base_motion:=false \
  base_output_topic:=/test/legacy_ros2_offline/touch_only/base_output \
  mock_step_duration:=0.05 \
  mock_detection_delay:=0.05 \
  detection_timeout:=3.0 >"${log_file}" 2>&1 &
launch_pid=$!

ready=false
for _ in {1..120}; do
  if grep -q 'Mock perception ready' "${log_file}" \
      && grep -q 'Mock executor ready' "${log_file}" \
      && grep -q 'Waiting for commands' "${log_file}"; then
    ready=true
    break
  fi
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    break
  fi
  sleep 0.10
done

if [[ "${ready}" != true ]]; then
  sed -n '1,240p' "${log_file}"
  echo 'BLOCKED: isolated legacy mock system did not become ready.' >&2
  exit 1
fi

ros2 node list --no-daemon --spin-time 1.0 >"${nodes_file}"
if grep -q -e cleanup_gripper_controller -e cleanup_dual_model_detector \
    -e cleanup_tracked_base_controller "${nodes_file}"; then
  sed -n '1,240p' "${nodes_file}"
  echo 'BLOCKED: a hardware-facing or base-controller node was started.' >&2
  exit 1
fi

python3 "${workspace}/scripts/touch_only_smoke_probe.py"

if grep -q \
    -e Traceback \
    -e ModuleNotFoundError \
    -e ImportError \
    -e 'process has died' \
    "${log_file}"; then
  sed -n '1,240p' "${log_file}"
  echo 'BLOCKED: isolated legacy mock raised a runtime error.' >&2
  exit 1
fi

echo 'LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS'
echo 'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'
