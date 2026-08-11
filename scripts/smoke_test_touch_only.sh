#!/usr/bin/env bash

set -eo pipefail

workspace="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ros_setup="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
source "${ros_setup}"
source "${workspace}/install/setup.bash"

export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-137}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

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
  rm -rf "${test_dir}"
}
trap cleanup EXIT

setsid ros2 launch \
  limo_cleanup_bringup cleanup_system.launch.py \
  use_real_perception:=false \
  use_mock_perception:=true \
  use_mock_executor:=true \
  use_detection_gate:=true \
  use_gripper_controller:=false \
  executor_dry_run:=true \
  allow_arm_motion:=false \
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
  cat "${log_file}"
  echo 'FAIL: touch_only mock system did not become ready' >&2
  exit 1
fi

ros2 node list --no-daemon --spin-time 1.0 >"${nodes_file}"
if grep -q -e cleanup_gripper_controller -e cleanup_dual_model_detector \
    "${nodes_file}"; then
  cat "${nodes_file}"
  echo 'FAIL: a gripper or real-perception node was started' >&2
  exit 1
fi

python3 "${workspace}/scripts/touch_only_smoke_probe.py"

if grep -q \
    -e Traceback \
    -e ModuleNotFoundError \
    -e ImportError \
    -e 'process has died' \
    "${log_file}"; then
  cat "${log_file}"
  echo 'FAIL: touch_only mock system raised a runtime error' >&2
  exit 1
fi

echo 'PASS: touch_only mock smoke completed without hardware nodes'
