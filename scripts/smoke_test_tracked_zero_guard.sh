#!/usr/bin/env bash

set -euo pipefail

readonly LEGACY_EXIT=64
readonly OFFLINE_DOMAIN_ID=223
readonly OFFLINE_RMW=rmw_cyclonedds_cpp
readonly TEST_PREFIX=/test/legacy_ros2_offline/tracked_zero_guard
readonly TEST_OUTPUT_TOPIC=/test/cleanup/tracked_zero_output

echo 'FIELD_RUNTIME_AUTHORITY=ROS1_NOETIC'
echo 'LEGACY_ROS2_OFFLINE_ONLY'
echo 'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'

if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE-}" != '1' ]]; then
  echo 'BLOCKED: set LIMO_ALLOW_LEGACY_ROS2_OFFLINE=1 for this isolated historical zero guard only.' >&2
  exit "${LEGACY_EXIT}"
fi
if [[ "$#" -ne 0 ]]; then
  echo 'BLOCKED: legacy offline zero guard accepts no command-line overrides.' >&2
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
  TRACKED_BASE_PORT BASE_OUTPUT_TOPIC INPUT_TOPIC OUTPUT_TOPIC \
  AUTHORIZATION_TOPIC SAFETY_TOPIC TOPOLOGY_READY_TOPIC RGB_TOPIC \
  DEPTH_TOPIC CAMERA_INFO_TOPIC DETECTOR_DEVICE PERCEPTION_PYTHON

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd "${script_dir}/.." && pwd)"
ros_setup=''
for candidate in /opt/ros/foxy/setup.bash /opt/ros/humble/setup.bash; do
  if [[ -f "${candidate}" ]]; then
    ros_setup="${candidate}"
    break
  fi
done
if [[ -z "${ros_setup}" ]]; then
  echo 'BLOCKED: no fixed legacy ROS2 setup was found.' >&2
  exit 2
fi
if [[ ! -f "${workspace_root}/install/setup.bash" ]]; then
  echo 'BLOCKED: built workspace setup is missing.' >&2
  exit 2
fi

export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=223
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
source "${ros_setup}"
source "${workspace_root}/install/setup.bash"

export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID=223
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
reject_set_environment \
  ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE \
  FASTDDS_DEFAULT_PROFILES_FILE
if [[ "${ROS_LOCALHOST_ONLY}" != '1' \
    || "${ROS_DOMAIN_ID}" != '223' \
    || "${RMW_IMPLEMENTATION}" != 'rmw_cyclonedds_cpp' ]]; then
  echo 'BLOCKED: legacy offline isolation could not be proven.' >&2
  exit "${LEGACY_EXIT}"
fi

launch_log="$(mktemp)"
launch_pid=''

cleanup() {
  if [[ -n "${launch_pid}" ]]; then
    if kill -0 "${launch_pid}" 2>/dev/null; then
      kill -INT -- "-${launch_pid}" 2>/dev/null || true
      for _ in {1..10}; do
        kill -0 "${launch_pid}" 2>/dev/null || break
        sleep 0.2
      done
    fi
    if kill -0 "${launch_pid}" 2>/dev/null; then
      kill -TERM -- "-${launch_pid}" 2>/dev/null || true
      for _ in {1..5}; do
        kill -0 "${launch_pid}" 2>/dev/null || break
        sleep 0.2
      done
    fi
    if kill -0 "${launch_pid}" 2>/dev/null; then
      kill -KILL -- "-${launch_pid}" 2>/dev/null || true
    fi
    wait "${launch_pid}" 2>/dev/null || true
  fi
  rm -f -- "${launch_log}"
}
trap cleanup EXIT INT TERM

setsid ros2 launch limo_cleanup_bringup tracked_base_zero_output.launch.py \
  input_topic:="${TEST_PREFIX}/request" \
  output_topic:="${TEST_OUTPUT_TOPIC}" \
  authorization_topic:="${TEST_PREFIX}/authorized" \
  safety_topic:="${TEST_PREFIX}/safety" \
  topology_ready_topic:="${TEST_PREFIX}/topology_ready" \
  >"${launch_log}" 2>&1 &
launch_pid=$!

if ! timeout -k 2 15 \
    python3 "${script_dir}/verify_tracked_zero_output.py"; then
  echo '===== isolated legacy zero-output guard log =====' >&2
  sed -n '1,160p' "${launch_log}" >&2
  exit 1
fi

if ! kill -0 "${launch_pid}" 2>/dev/null; then
  echo 'BLOCKED: zero-output launch exited before verification completed.' >&2
  sed -n '1,160p' "${launch_log}" >&2
  exit 1
fi

echo 'LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS'
echo 'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'
