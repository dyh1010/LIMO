#!/usr/bin/env bash

set -eo pipefail

workspace="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ros_setup="${ROS_SETUP:-}"
underlay_setup="${ROS_UNDERLAY_SETUP:-}"
perception_python="${PERCEPTION_PYTHON:-python3}"
bottle_model_path="${BOTTLE_MODEL_PATH:-${workspace}/models/nongfu_yolov8n_best.pt}"
bin_model_path="${BIN_MODEL_PATH:-${workspace}/models/trash_bin_yolov8n_best.pt}"
detector_device="${DETECTOR_DEVICE:-cpu}"

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

test_dir=$(mktemp -d /tmp/limo_real_perception_startup.XXXXXX)
launch_log="$test_dir/launch.log"
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

trap stop_launch EXIT

setsid ros2 launch limo_cleanup_bringup real_perception_only.launch.py \
  start_camera:=false \
  perception_python:="${perception_python}" \
  bottle_model_path:="${bottle_model_path}" \
  bin_model_path:="${bin_model_path}" \
  detector_device:="${detector_device}" >"$launch_log" 2>&1 &
launch_pid=$!

ready=false
for _ in {1..120}; do
  if grep -q 'Dual-model detector ready' "$launch_log"; then
    ready=true
    break
  fi
  if ! kill -0 "$launch_pid" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

if grep -Eq 'Traceback|ModuleNotFoundError|ImportError' "$launch_log"; then
  cat "$launch_log"
  echo 'FAIL: real perception startup raised an import/runtime error' >&2
  exit 1
fi

if [[ "$ready" != true ]]; then
  cat "$launch_log"
  echo 'FAIL: real perception node did not become ready' >&2
  exit 1
fi

if ! grep -q 'always_active=True' "$launch_log"; then
  cat "$launch_log"
  echo 'FAIL: read-only perception did not enable always_active' >&2
  exit 1
fi

echo 'PASS: read-only perception loaded both models in always-active mode'
echo "Smoke-test log: $launch_log"
