#!/usr/bin/env bash

set -eo pipefail

workspace="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ros_setup="${ROS_SETUP:-}"
underlay_setup="${ROS_UNDERLAY_SETUP:-}"

if [[ -z "${ros_setup}" ]]; then
  if [[ -f /opt/ros/foxy/setup.bash ]]; then
    ros_setup=/opt/ros/foxy/setup.bash
  else
    ros_setup=/opt/ros/humble/setup.bash
  fi
fi

source "${ros_setup}"
if [[ -n "${underlay_setup}" ]]; then
  source "${underlay_setup}"
elif [[ -f /home/agilex/limo_ros2_ws/install/setup.bash ]]; then
  source /home/agilex/limo_ros2_ws/install/setup.bash
fi
source "${workspace}/install/setup.bash"

export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-137}"
if [[ -z "${RMW_IMPLEMENTATION:-}" ]]; then
  export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
fi
if [[ "${RMW_IMPLEMENTATION}" != rmw_cyclonedds_cpp ]]; then
  unset CYCLONEDDS_URI
fi

set -u

test_dir=$(mktemp -d /tmp/limo_cleanup_mock.XXXXXX)
log_file="$test_dir/launch.log"
pre_shutdown_log="$test_dir/pre_shutdown.log"
launch_pid=''

stop_launch() {
  if [[ -n "$launch_pid" ]] && kill -0 -- "-$launch_pid" 2>/dev/null; then
    kill -INT -- "-$launch_pid" 2>/dev/null || true
    for _ in {1..60}; do
      if ! kill -0 -- "-$launch_pid" 2>/dev/null; then
        break
      fi
      sleep 0.10
    done
    if kill -0 -- "-$launch_pid" 2>/dev/null; then
      kill -TERM -- "-$launch_pid" 2>/dev/null || true
    fi
    wait "$launch_pid" 2>/dev/null || true
  fi
}

cleanup() {
  stop_launch
  rm -rf "$test_dir"
}
trap cleanup EXIT

setsid ros2 launch \
  limo_cleanup_bringup cleanup_system.launch.py \
  use_real_perception:=false \
  use_mock_perception:=true \
  use_mock_executor:=true \
  use_gripper_controller:=false >"$log_file" 2>&1 &
launch_pid=$!

ready=false
for _ in {1..100}; do
  if grep -q 'Mock perception ready' "$log_file" \
      && grep -q 'Mock executor ready' "$log_file" \
      && grep -q 'Detection gate ready' "$log_file" \
      && grep -q 'Waiting for commands' "$log_file"; then
    ready=true
    break
  fi
  if ! kill -0 "$launch_pid" 2>/dev/null; then
    break
  fi
  sleep 0.10
done

cp "$log_file" "$pre_shutdown_log"
cat "$pre_shutdown_log"

if grep -q \
    -e Traceback \
    -e ModuleNotFoundError \
    -e ImportError \
    -e 'process has died' \
    "$pre_shutdown_log"; then
  echo 'FAIL: mock cleanup system raised a launch/runtime error' >&2
  exit 1
fi

if [[ "$ready" != true ]]; then
  echo 'FAIL: mock cleanup system did not become ready' >&2
  exit 1
fi

if ! grep -q 'cleanup_mock_perception' "$pre_shutdown_log"; then
  echo 'FAIL: mock perception did not start' >&2
  exit 1
fi

if grep -q 'cleanup_dual_model_detector' "$pre_shutdown_log"; then
  echo 'FAIL: real perception started during the mock-only smoke test' >&2
  exit 1
fi

echo 'PASS: mock cleanup system ran without hardware nodes or runtime errors'
