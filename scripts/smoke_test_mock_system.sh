#!/usr/bin/env bash

# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY
# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN
# NOT_NOETIC_BUILD_INSTALL_FIELD_OR_DELIVERY_EVIDENCE
#
# Retained only for an isolated ROS2 pure-mock graph.  It never authorizes
# real perception/execution, base/arm/gripper motion, camera/device access,
# field evidence, or delivery.  Current operations begin at
# docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md.

set -euo pipefail

readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'
readonly isolated_domain='194'

if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE:-}" != '1' ]]; then
  echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2
  echo "Read ${operations_index}." >&2
  exit 64
fi

if [[ "$#" -ne 0 ]]; then
  echo 'BLOCKED_LEGACY_ROS2_UNDERLAY_OR_WORKSPACE_OVERRIDE_FORBIDDEN' >&2
  echo "Read ${operations_index}." >&2
  exit 66
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
workspace="$(cd -- "${script_dir}/.." && pwd -P)"
source /opt/ros/foxy/setup.bash
source "${workspace}/install/setup.bash"

# Reassert isolation after every sourced environment so neither Foxy nor the
# local install can widen the graph scope of this legacy-only mock harness.
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="${isolated_domain}"
unset ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE

readonly -a mock_safety_args=(
  use_mock_perception:=true
  use_real_perception:=false
  use_mock_executor:=true
  use_detection_gate:=true
  executor_dry_run:=true
  allow_arm_motion:=false
  use_gripper_controller:=false
  gripper_backend:=dry_run
  allow_gripper_motion:=false
  confirmed_gripper_model:=UNRESOLVED_DO_NOT_CONNECT
  use_tracked_base_controller:=false
  allow_base_motion:=false
)

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
  "${mock_safety_args[@]}" >"$log_file" 2>&1 &
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
